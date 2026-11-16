"""Surface measurements independent of the model's next-token predictions."""

import re
import statistics
import unicodedata

import config


def sentences(text: str) -> list[str]:
    """Approximate sentence boundaries; abbreviations remain a blind spot."""
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def words(text: str) -> list[str]:
    """Lowercase Unicode words, including internal apostrophes."""
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text.lower())


def sentence_length_spread(text: str) -> float:
    """Population coefficient of variation; larger means more varied lengths."""
    lengths = [len(words(sentence)) for sentence in sentences(text)]
    lengths = [length for length in lengths if length]
    if len(lengths) < 2:
        return 0.0
    return statistics.pstdev(lengths) / statistics.mean(lengths)


def type_token_ratio(text: str) -> float:
    """Unique words divided by total words; empty text has ratio zero."""
    tokens = words(text)
    return len(set(tokens)) / len(tokens) if tokens else 0.0


def punctuation_density(text: str) -> float:
    """Unicode punctuation characters divided by all characters, including spaces."""
    if not text:
        return 0.0
    return sum(unicodedata.category(char).startswith("P") for char in text) / len(text)


def style_signal(text: str) -> float:
    """Return AI-likeness in [0, 1]; abstain at 0.5 on sparse samples."""
    count = len(words(text))
    sentence_count = sum(bool(words(sentence)) for sentence in sentences(text))
    if count < config.STYLE_MIN_WORDS or sentence_count < config.STYLE_MIN_SENTENCES:
        return 0.5
    uniformity = 1 - min(sentence_length_spread(text) / config.STYLE_SPREAD_SCALE, 1.0)
    repetition = 1 - type_token_ratio(text)
    sparse_punctuation = 1 - min(punctuation_density(text) / config.STYLE_PUNCTUATION_SCALE, 1.0)
    return (
        config.STYLE_WEIGHT_SPREAD * uniformity
        + config.STYLE_WEIGHT_VARIETY * repetition
        + config.STYLE_WEIGHT_PUNCTUATION * sparse_punctuation
    )


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or (
        "The system works well. It handles most cases correctly and provides "
        "good results. Users generally find it easy to use and understand."
    )
    print(f"{len(sentences(text))} sentences, {len(words(text))} words\n")
    print(f"sentence_length_spread   {sentence_length_spread(text):.4f}")
    print(f"type_token_ratio         {type_token_ratio(text):.4f}")
    print(f"punctuation_density      {punctuation_density(text):.4f}")
    print(f"style_signal             {style_signal(text):.4f}   (higher = more likely AI)")
