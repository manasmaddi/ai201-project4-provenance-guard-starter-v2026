# Provenance Guard

## What This Does

1. A writer sends JSON containing `text` and `creator_id` to `POST /submit`.
2. The service validates the JSON object, field types, and size limits before running a model.
3. `detector.model_signal` measures how predictable the text is to a local GPT-2 language model.
4. `stylometry.style_signal` measures sentence length variation, vocabulary variety, and punctuation density.
5. `scoring.py::combine_signals` combines the two signals into a continuous score from 0 (human-like) to 1 (AI-like).
6. `scoring.score_to_label` chooses a full-sentence label. The decision, creator, both signals, combined score, and status are appended to `logs/audit.jsonl` before the service responds.
7. The writer can challenge the result with `POST /appeal`. An append-only appeal event records their reasoning and changes the item's latest status to `under_review`, without rerunning the detector.

Only required unit features are planned; no stretch features are included.

**API contract, decided before implementation:**

- `POST /submit`: JSON object with nonblank string `text` (at most 20,000 characters, at least three words) and nonblank string `creator_id` (at most 128 characters). Success: HTTP 200 with `content_id` (UUID string), `guess` (`ai`, `human`, or `unsure`), `confidence` (combined AI-likeness score in [0, 1]), `label` (full sentence), `model_score`, `style_score`, and `status` (`decided`).
- `POST /appeal`: JSON object with nonblank string `content_id` and nonblank string `reasoning` (at most 5,000 characters). Success: HTTP 200 with `content_id`, `status: under_review`, and a confirmation `message`. Creator identity is taken from the original logged decision. Repeated appeals are each recorded.
- Invalid JSON, non-object bodies, wrong field types, and blank or too-short fields return HTTP 400 with `error` and `message`. Oversize fields or a request body above 128 KiB return HTTP 413. An unknown appeal ID returns HTTP 404. An unavailable detector returns HTTP 503 rather than a fabricated score. Failed requests do not create decisions.
- `GET /log` returns append-only events in chronological order. For an item's current status, use its last event; its original decision remains visible. `/ping` stays the starter control route, and `/health` reports whether the detector is in memory.

A false positive follows the same path: for example, a real writer receiving score 0.86 sees the AI label and appeal instructions, can submit their reasoning, and receives confirmation of `under_review`. A score is an estimate of textual patterns, not proof of authorship.

## Signals and Scoring

The following rule and constants were selected before running calibration results.

`detector.py::model_signal` uses GPT-2 next-token perplexity, mapped to [0, 1] by the starter. Predictable language may resemble generated writing. It does not verify facts, intent, or authorship. Plain human prose and second-language writing can look predictable; rare vocabulary can make AI prose look human. It only reads the first 400 model tokens.

`stylometry.py::style_signal` will combine three independent surface measurements: sentence length spread (population standard deviation divided by mean word count), type-token ratio (unique lowercase words / total words), and punctuation density (Unicode punctuation characters / all characters). These measurements cannot understand meaning. Editing punctuation or sentence lengths can change the result; vocabulary variety also depends on length and language.

Planned style rule: `0.50 * (1 - min(spread, 1)) + 0.30 * (1 - type_token_ratio) + 0.20 * (1 - min(punctuation_density / 0.10, 1))`. Lower spread, more repetition, and sparse punctuation increase AI-likeness. Fewer than 20 words or three word-bearing sentences gives neutral style score 0.5, because there is too little evidence for variation. The word splitter supports Unicode letters and digits.

**Combining rule:** `scoring.py::combine_signals` uses `0.60 * model_score + 0.40 * style_score`. When the signals differ by at least 0.50, clamp the result to [0.35, 0.65] so strong disagreement remains unsure. All weights, scales, and boundaries live in `config.py`.

**Thresholds:** human at scores <= 0.20; unsure at 0.20 < score < 0.80; AI at scores >= 0.80. The wide unsure band prioritizes avoiding confident accusations. These are heuristic scores, not calibrated probabilities. Confidence here means the combined AI-likeness score: 0.51 is unsure and 0.95 is AI.

Calibration observations will be recorded after the author's criteria are committed.

## Label Variants

| Label | Score range | The exact text a reader sees |
|---|---|---|
| high-confidence human | 0 <= score <= 0.20 | We think this was written by a person. This estimate cannot verify who wrote it. |
| unsure | 0.20 < score < 0.80 | We cannot tell whether this was written by a person or AI. This result is not evidence of wrongdoing. You can request a review if you disagree. |
| high-confidence AI | 0.80 <= score <= 1 | We think this may be AI-generated. This estimate can be wrong; if you wrote this, you can appeal and explain your process. |

The unsure label states the uncertainty directly and gives the writer a next step without accusing them.

## Sample Run

Pending a real local-model run after the author's acceptance criteria are committed. No sample responses have been fabricated.

Run locally with Python 3.11, 3.12, or 3.13:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python detector.py
python app.py
```

See [RUNNING.md](RUNNING.md) for platform-specific commands. No API key is needed. The first model download is about 550 MB.

## How I Used AI

The implementation and documentation in this repository were produced with Codex in response to the request “do this” and the pasted assignment. This is an AI-assisted draft; the author still needs to review it and supply their own acceptance criteria.

1. **Endpoint work:** The request supplied the assignment's `/submit` and `/appeal` requirements. Codex inspected the starter and drafted an API contract, validation, and an append-only appeal design. The proposed changes connect decisions to the existing audit helpers. No independent author edits or review are claimed.
2. **Scoring work:** The same request asked for two signals and three labels. Codex proposed Unicode-aware style measurements, a 60/40 combination, and a disagreement guard with a wide unsure band. These are implementation choices, not measured accuracy claims or author-written acceptance criteria.
