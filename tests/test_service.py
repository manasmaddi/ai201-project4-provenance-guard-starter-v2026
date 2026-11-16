"""Contract checks with isolated logs; model behavior uses explicit test doubles.

These checks do not claim detector accuracy. The README records real model runs.
"""

import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import audit
import config
import detector
import scoring
import stylometry


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        for name, value in (("LOG_DIR", root), ("AUDIT_LOG", root / "audit.jsonl")):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.app.test_client()
        self.payload = {"text": "Some ordinary words for the submission.", "creator_id": "writer"}

    def test_submit_and_appeal_persist_for_ten_items(self):
        with patch.object(detector, "model_signal", return_value=0.9) as model:
            for _ in range(10):
                result = self.client.post("/submit", json=self.payload)
                self.assertEqual(result.status_code, 200)
                data = result.get_json()
                self.assertEqual(data["status"], "decided")
                self.assertAlmostEqual(data["confidence"], scoring.combine_signals(0.9, 0.5))
                self.assertEqual(data["model_score"], 0.9)
                self.assertEqual(data["style_score"], 0.5)
                original = audit.entries_for(data["content_id"])[0]
                reasoning = "  I wrote this myself. Please review my drafts.  "
                appeal = self.client.post("/appeal", json={"content_id": data["content_id"], "reasoning": reasoning})
                self.assertEqual(appeal.status_code, 200)
                self.assertEqual(appeal.get_json()["status"], "under_review")
                entries = audit.entries_for(data["content_id"])
                self.assertEqual(len(entries), 2)
                self.assertEqual(entries[0], original)
                self.assertEqual(entries[-1]["reasoning"], reasoning)
                self.assertEqual(entries[-1]["creator_id"], "writer")
                self.assertEqual(entries[-1]["status"], "under_review")
            self.assertEqual(model.call_count, 10)  # appeals never rescore
        self.assertEqual(self.client.get("/log").get_json()["count"], 20)

    def test_unknown_and_repeated_appeals(self):
        with patch.object(detector, "model_signal", return_value=0.5):
            data = self.client.post("/submit", json=self.payload).get_json()
        for _ in range(2):
            self.assertEqual(self.client.post("/appeal", json={"content_id": data["content_id"], "reasoning": "Please review."}).status_code, 200)
        self.assertEqual(len(audit.entries_for(data["content_id"])), 3)
        result = self.client.post("/appeal", json={"content_id": "unknown", "reasoning": "Please review."})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(audit.entries_for("unknown"), [])

    def test_bad_inputs_never_score_or_create_decisions(self):
        with patch.object(detector, "model_signal") as model:
            for route in ("/submit", "/appeal"):
                for body in ("{", "null", "[]", '"hello"', "4", "true", ""):
                    with self.subTest(route=route, body=body):
                        response = self.client.post(route, data=body, content_type="application/json")
                        self.assertEqual(response.status_code, 400)
                        self.assertIn("error", response.get_json())
                        self.assertIn("message", response.get_json())
                fields = self.payload if route == "/submit" else {"content_id": "id", "reasoning": "My reason"}
                for key in fields:
                    for invalid in (None, "", " \n", 4, [], {}):
                        body = {**fields, key: invalid}
                        self.assertEqual(self.client.post(route, json=body).status_code, 400)
                    body = {k: v for k, v in fields.items() if k != key}
                    self.assertEqual(self.client.post(route, json=body).status_code, 400)
                self.assertEqual(self.client.post(route, data=" " * (config.MAX_REQUEST_BYTES + 1), content_type="application/json").status_code, 413)
            for field, maximum in (("text", config.MAX_TEXT_CHARS), ("creator_id", config.MAX_CREATOR_ID_CHARS)):
                self.assertEqual(self.client.post("/submit", json={**self.payload, field: "a" * (maximum + 1)}).status_code, 413)
            self.assertEqual(self.client.post("/appeal", json={"content_id": "id", "reasoning": "a" * (config.MAX_REASONING_CHARS + 1)}).status_code, 413)
            for text in ("x", "two words", "!!!", "--- ... !!!"):
                self.assertEqual(self.client.post("/submit", json={**self.payload, "text": text}).status_code, 400)
            model.assert_not_called()
        self.assertTrue(all(entry.get("event") == "rejected" for entry in audit.read_entries()))

    def test_exact_size_boundaries(self):
        with patch.object(detector, "model_signal", return_value=0.5):
            response = self.client.post("/submit", json={"text": "a b " + "c" * (config.MAX_TEXT_CHARS - 4), "creator_id": "c" * config.MAX_CREATOR_ID_CHARS})
        self.assertEqual(response.status_code, 200)
        result = self.client.post("/appeal", json={"content_id": response.get_json()["content_id"], "reasoning": "r" * config.MAX_REASONING_CHARS})
        self.assertEqual(result.status_code, 200)

    def test_detector_failure_is_explicit(self):
        with patch.object(detector, "model_signal", side_effect=detector.DetectorUnavailable("test")):
            with self.assertLogs(app.app.logger, level="ERROR"):
                result = self.client.post("/submit", json=self.payload)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.get_json()["error"], "detector_unavailable")
        self.assertTrue(all(entry.get("event") == "rejected" for entry in audit.read_entries()))


class ScoringTests(unittest.TestCase):
    def test_boundaries_and_coverage(self):
        cases = [(0, "human"), (0.2, "human"), (math.nextafter(0.2, 1), "unsure"), (0.51, "unsure"), (math.nextafter(0.8, 0), "unsure"), (0.8, "ai"), (0.95, "ai"), (1, "ai")]
        for score, guess in cases:
            self.assertEqual(scoring.score_to_label(score)[0], guess)
        for i in range(10001):
            self.assertIn(scoring.score_to_label(i / 10000)[0], {"human", "unsure", "ai"})
        for invalid in (float("nan"), float("inf"), -0.01, 1.01):
            with self.assertRaises(ValueError):
                scoring.score_to_label(invalid)

    def test_combination_reaches_labels_and_disagreement_abstains(self):
        for model, style, expected in ((0, 0, "human"), (0.5, 0.5, "unsure"), (1, 1, "ai"), (0.9, 0.1, "unsure"), (0.1, 0.9, "unsure")):
            self.assertEqual(scoring.score_to_label(scoring.combine_signals(model, style))[0], expected)
        self.assertAlmostEqual(scoring.combine_signals(0.8, 0.6), 0.72)

    def test_style_measurements(self):
        self.assertEqual(stylometry.sentence_length_spread("One two. Three four."), 0)
        self.assertAlmostEqual(stylometry.sentence_length_spread("One. Two three four."), 0.5)
        self.assertEqual(stylometry.type_token_ratio("One one TWO"), 2 / 3)
        self.assertEqual(stylometry.words("Café café — 你好!"), ["café", "café", "你好"])
        self.assertEqual(stylometry.punctuation_density("a—b!"), 0.5)
        self.assertEqual(stylometry.style_signal("A short sentence."), 0.5)
        repetitive = "The system works well for all users today. " * 5
        irregular = "Oops! " + " ".join(f"word{i}" for i in range(50)) + ". Why?"
        self.assertGreater(stylometry.style_signal(repetitive), stylometry.style_signal(irregular))
        for text in ("", "!!!", repetitive, irregular):
            self.assertTrue(0 <= stylometry.style_signal(text) <= 1)


if __name__ == "__main__":
    unittest.main()
