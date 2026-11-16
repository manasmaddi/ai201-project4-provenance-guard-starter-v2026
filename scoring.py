"""Combine independent signals and describe the result to a writer."""

import math

import config


def _validate_score(score: float) -> None:
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("Scores must be finite numbers between 0 and 1.")


def combine_signals(model_score: float, style_score: float) -> float:
    """60/40 weighted average; strong disagreement stays in the unsure band."""
    _validate_score(model_score)
    _validate_score(style_score)
    score = (
        config.WEIGHT_MODEL_SIGNAL * model_score
        + config.WEIGHT_STYLE_SIGNAL * style_score
    )
    if abs(model_score - style_score) >= config.DISAGREEMENT_THRESHOLD:
        score = min(max(score, config.DISAGREEMENT_SCORE_MIN), config.DISAGREEMENT_SCORE_MAX)
    return score


def score_to_label(score: float) -> tuple[str, str]:
    """Cover [0, 1] with inclusive human/AI boundaries and an open unsure band."""
    _validate_score(score)
    if score >= config.AI_THRESHOLD:
        return "ai", (
            "We think this may be AI-generated. This estimate can be wrong; "
            "if you wrote this, you can appeal and explain your process."
        )
    if score <= config.HUMAN_THRESHOLD:
        return "human", (
            "We think this was written by a person. "
            "This estimate cannot verify who wrote it."
        )
    return "unsure", (
        "We cannot tell whether this was written by a person or AI. "
        "This result is not evidence of wrongdoing. "
        "You can request a review if you disagree."
    )


def label_ranges() -> list[tuple[str, str]]:
    """Exact ranges, including endpoint ownership, for documentation."""
    return [
        ("high-confidence human", f"0.00 <= score <= {config.HUMAN_THRESHOLD:.2f}"),
        ("unsure", f"{config.HUMAN_THRESHOLD:.2f} < score < {config.AI_THRESHOLD:.2f}"),
        ("high-confidence AI", f"{config.AI_THRESHOLD:.2f} <= score <= 1.00"),
    ]
