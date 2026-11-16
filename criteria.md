# Acceptance criteria — Provenance Guard

These targets were drafted by Codex at the author's explicit request before
running detector examples, calibration, or acceptance checks. They require the
author's review; they are not claimed to be independently author-written.
Keep these original targets unchanged when evaluating them in the next unit.

## 1. Limit false accusations on human writing

In each of three trials on the same 10 human-written English passages (50–300
words each), at most one passage may receive the high-confidence AI label.
The set must include at least three plainly worded passages, two formal
passages, and two passages written by people using English as an additional
language. Record provenance and fix the set before the first trial; AI-created
imitations do not count as human writing.

**Why this target:** A wrong accusation harms a writer more than a missed AI
submission harms this prototype. Including plain and second-language writing
checks the model's known predictability bias instead of testing only prose it
finds easy to classify as human.

## 2. Separate known human and generated samples

For a fixed set of 10 known human passages and 10 unedited AI-generated passages
of 50–300 words, the mean combined score for AI passages must exceed the human
mean by at least 0.20 in each of three trials. Record origins and freeze the
sample set before scoring. The human set may be the set from criterion 1.

**Why this target:** Different scores should represent a useful signal rather
than tiny numerical differences. A 0.20 mean gap demands separation while not
assuming that every individual passage can be identified correctly.

## 3. Make all labels reachable and cover every valid score

`score_to_label` must return exactly one of `human`, `unsure`, or `ai` for every
finite score in [0, 1], including both thresholds and endpoints. Scores 0.51 and
0.95 must receive different labels. In addition, at least one real `/submit`
request per label must demonstrate all three labels without mocked signals.

**Why this target:** A label that only exists in a branch of code is not useful
to a writer. Checking boundaries and actual requests catches both range errors
and a combining rule that never reaches one of its labels.

## 4. Preserve every appeal and the original decision

For 10 successful submissions, appeal each content ID once. All 10 appeals must
return HTTP 200 with `status: under_review`. After a fresh read of the audit
file, each ID must have its unchanged original decision followed by an appeal
event containing the exact supplied reasoning and the original creator ID.
An unknown ID must return HTTP 404 and create no appeal event.

**Why this target:** A writer's challenge must survive beyond the response in
memory. Keeping the original decision makes the dispute traceable and checking
unknown IDs prevents confirmations for reviews that cannot happen.

## 5. Reject bad input before scoring

For both `/submit` and `/appeal`, malformed JSON and JSON null, arrays, strings,
and numbers must return HTTP 400 with JSON `error` and `message` fields. Missing,
blank, or non-string required fields must also return HTTP 400. Submissions
above 20,000 text characters, creator IDs above 128 characters, appeal reasoning
above 5,000 characters, and bodies above 128 KiB must return HTTP 413. None of
these cases may invoke the model or create a decision or appeal. Valid required
fields exactly at their maximum lengths must pass validation.

**Why this target:** Bad requests should have predictable, readable responses
and must not spend model time or create misleading decisions. Exact boundary
checks catch size limits that reject valid input or allow an oversized request.
