# Provenance Guard

## What This Does

1. A writer sends JSON containing `text` and `creator_id` to `POST /submit`.
2. The service validates the JSON object, field types, and size limits before running a model.
3. `detector.model_signal` measures how predictable the text is to a local GPT-2 language model.
4. `stylometry.style_signal` measures sentence length variation, vocabulary variety, and punctuation density.
5. `scoring.py::combine_signals` combines the two signals into a continuous score from 0 (human-like) to 1 (AI-like).
6. `scoring.score_to_label` chooses a full-sentence label. The decision, creator, both signals, combined score, and status are appended to `logs/audit.jsonl` before the service responds.
7. The writer can challenge the result with `POST /appeal`. An append-only appeal event records their reasoning and changes the item's latest status to `under_review`, without rerunning the detector.

Only required unit features are implemented; no stretch features are included.

**API contract, decided before implementation:**

- `POST /submit`: JSON object with nonblank string `text` (at most 20,000 characters, at least three words) and nonblank string `creator_id` (at most 128 characters). Success: HTTP 200 with `content_id` (UUID string), `guess` (`ai`, `human`, or `unsure`), `confidence` (combined AI-likeness score in [0, 1]), `label` (full sentence), `model_score`, `style_score`, and `status` (`decided`).
- `POST /appeal`: JSON object with nonblank string `content_id` and nonblank string `reasoning` (at most 5,000 characters). Success: HTTP 200 with `content_id`, `status: under_review`, and a confirmation `message`. Creator identity is taken from the original logged decision. Repeated appeals are each recorded.
- Invalid JSON, non-object bodies, wrong field types, and blank or too-short fields return HTTP 400 with `error` and `message`. Oversize fields or a request body above 128 KiB return HTTP 413. An unknown appeal ID returns HTTP 404. An unavailable detector returns HTTP 503 rather than a fabricated score. Failed requests do not create decisions.
- `GET /log` returns append-only events in chronological order. For an item's current status, use its last event; its original decision remains visible. `/ping` stays the starter control route, and `/health` reports whether the detector is in memory.

A false positive follows the same path: for example, a real writer receiving score 0.86 sees the AI label and appeal instructions, can submit their reasoning, and receives confirmation of `under_review`. A score is an estimate of textual patterns, not proof of authorship.

## Signals and Scoring

The following rule and constants were selected before running calibration results.

`detector.py::model_signal` uses GPT-2 next-token perplexity, mapped to [0, 1] by the starter. Predictable language may resemble generated writing. It does not verify facts, intent, or authorship. Plain human prose and second-language writing can look predictable; rare vocabulary can make AI prose look human. It only reads the first 400 model tokens.

`stylometry.py::style_signal` combines three surface measurements: sentence length spread (population standard deviation divided by mean word count), type-token ratio (unique lowercase words / total words), and punctuation density (Unicode punctuation characters / all characters). These measurements cannot understand meaning. Editing punctuation or sentence lengths can change the result; vocabulary variety also depends on length and language.

Style rule: `0.50 * (1 - min(spread, 1)) + 0.30 * (1 - type_token_ratio) + 0.20 * (1 - min(punctuation_density / 0.10, 1))`. Lower spread, more repetition, and sparse punctuation increase AI-likeness. Fewer than 20 words or three word-bearing sentences gives neutral style score 0.5, because there is too little evidence for variation. The word splitter supports Unicode letters and digits.

**Combining rule:** `scoring.py::combine_signals` uses `0.60 * model_score + 0.40 * style_score`. When the signals differ by at least 0.50, clamp the result to [0.35, 0.65] so strong disagreement remains unsure. All weights, scales, and boundaries live in `config.py`.

**Thresholds:** human at scores <= 0.20; unsure at 0.20 < score < 0.80; AI at scores >= 0.80. The wide unsure band prioritizes avoiding confident accusations. These are heuristic scores, not calibrated probabilities. Confidence here means the combined AI-likeness score: 0.51 is unsure and 0.95 is AI.

Real local-model observations from `results/calibration.json` (all inputs are Codex-generated demonstrations, not a human benchmark):

| Input | Model | Style | Combined | Label |
|---|---:|---:|---:|---|
| regular AI-style prose | 0.9591 | 0.8053 | 0.8976 | ai |
| irregular human-like stress input | 0.1265 | 0.1624 | 0.1408 | human |
| formal human-like prose | 0.4577 | 0.6420 | 0.5314 | unsure |
| lightly edited AI-style prose | 0.7687 | 0.5684 | 0.6886 | unsure |
| borderline short prose | 0.6722 | 0.5215 | 0.6119 | unsure |
| deliberate signal disagreement | 0.0602 | 0.6779 | 0.3500 | unsure |

The deliberately unusual equal-length sentences split the signals: model 0.0602 versus style 0.6779. Their raw weighted average is about 0.3073; the disagreement guard returns 0.35, keeping the label unsure. The irregular prose gets a human label even though it was generated here, illustrating a real evasion limitation. Light edits moved the AI-style example into unsure. These runs demonstrate reachability and signal behavior; they do not establish detector accuracy. The false-positive and score-spread targets still need fixed samples with known human provenance in the next unit.

## Label Variants

| Label | Score range | The exact text a reader sees |
|---|---|---|
| high-confidence human | 0 <= score <= 0.20 | We think this was written by a person. This estimate cannot verify who wrote it. |
| unsure | 0.20 < score < 0.80 | We cannot tell whether this was written by a person or AI. This result is not evidence of wrongdoing. You can request a review if you disagree. |
| high-confidence AI | 0.80 <= score <= 1 | We think this may be AI-generated. This estimate can be wrong; if you wrote this, you can appeal and explain your process. |

The unsure label states the uncertainty directly and gives the writer a next step without accusing them.

## Sample Run

Captured from the running Flask service using curl and the real local GPT-2 model. All example text is AI-generated test data. IDs and timestamps below are actual recorded values. Audit timestamps are UTC.

**Submission — HTTP 200**

```bash
curl -X POST http://127.0.0.1:5000/submit \
  -H 'Content-Type: application/json' \
  -d '{"text": "The system is designed to help users complete their tasks. The system is designed to make the process easy to understand. The system is designed to provide clear and useful information. The system is designed to support users in their daily work. The system is designed to improve the quality of the results. The system is designed to help users achieve their goals.", "creator_id": "sample_writer"}'
```

```json
{
  "confidence": 0.8975833411397346,
  "content_id": "ff8b9773-dd52-49cd-864a-b75d26bc8faf",
  "guess": "ai",
  "label": "We think this may be AI-generated. This estimate can be wrong; if you wrote this, you can appeal and explain your process.",
  "model_score": 0.9591,
  "status": "decided",
  "style_score": 0.8053083528493364
}
```

**Appeal — HTTP 200**

```bash
curl -X POST http://127.0.0.1:5000/appeal \
  -H 'Content-Type: application/json' \
  -d '{"content_id": "ff8b9773-dd52-49cd-864a-b75d26bc8faf", "reasoning": "This is a demonstration appeal. Please review the drafting process before relying on this estimate."}'
```

```json
{
  "content_id": "ff8b9773-dd52-49cd-864a-b75d26bc8faf",
  "message": "Your appeal has been recorded. Your submission is under review.",
  "status": "under_review"
}
```

**Audit log after the appeal — HTTP 200**

```bash
curl "http://127.0.0.1:5000/log?limit=2"
```

```json
{
  "count": 2,
  "entries": [
    {
      "combined_score": 0.8975833411397346,
      "content_id": "ff8b9773-dd52-49cd-864a-b75d26bc8faf",
      "creator_id": "sample_writer",
      "guess": "ai",
      "label": "We think this may be AI-generated. This estimate can be wrong; if you wrote this, you can appeal and explain your process.",
      "model_score": 0.9591,
      "status": "decided",
      "style_score": 0.8053083528493364,
      "timestamp": "2026-11-16T05:12:59+00:00"
    },
    {
      "content_id": "ff8b9773-dd52-49cd-864a-b75d26bc8faf",
      "creator_id": "sample_writer",
      "event": "appeal",
      "reasoning": "This is a demonstration appeal. Please review the drafting process before relying on this estimate.",
      "status": "under_review",
      "timestamp": "2026-11-16T05:12:59+00:00"
    }
  ]
}
```

The full committed log also preserves a Milestone 3 one-signal entry with a null style score and temporary label. Subsequent decisions contain both real signals and final labels. `/health` reported `detector_loaded: true` after the requests; the model remains in memory.

Run locally with Python 3.11, 3.12, or 3.13:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python detector.py
python app.py
```

See [RUNNING.md](RUNNING.md) for platform-specific commands. No API key is needed. The first model download is about 550 MB. It is stored under the ignored `.cache/huggingface/hub` directory in this repository; downloaded files are reused without online checks. `HF_HUB_CACHE` can override that location.

**Verification:** `.venv/bin/python -m unittest discover -s tests -v` passes all eight checks, including invalid JSON and size boundaries, ten persisted appeals, unknown/repeated appeals, continuous scores, and exact label boundaries. Endpoint tests use explicit model test doubles and temporary audit files; the curl examples above use the real model and committed audit file. `python test.py` passes eight environment checks and fails only the 9 GB free-disk prerequisite (about 4.1 GB available during verification). The installed service and model run successfully; the disk prerequisite has not been lowered.

## How I Used AI

Codex wrote this implementation and documentation. The author has not yet independently reviewed or edited the generated work. AI assistance is disclosed rather than described as independent student work.

1. **Service implementation:** The author asked “do this” and supplied the assignment. Codex returned the API contract, validation, local-model integration, style measurements, combination rule, labels, appeal logging, tests, and live examples. Codex changed the starter stubs into working handlers and kept `/ping` unchanged. During verification, Codex also changed model loading to reuse cached files after network checks caused delays. No separate author revisions are claimed.
2. **Acceptance criteria:** Codex initially requested author-written criteria because the assignment requires them. The author replied “you do it and tell me.” Codex drafted five measurable targets with reasons, explicitly marked them AI-assisted, and committed them before running scoring examples. The criteria remain drafts for the author to review; this does not satisfy the assignment's requirement that all five be independently author-written.
