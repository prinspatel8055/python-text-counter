"""
analytics.py
------------
Pure text-analysis engine for the 3D Text Counter.

Contains no database or web-framework code, so every function here is
trivially unit-testable and can be reused from a script, a notebook or
another service.

Main entry point:  analyze(text) -> dict
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Average adult silent-reading speed (words per minute) used for "reading time".
READING_WPM = 200

# Average speaking speed (words per minute) used for "speaking time".
SPEAKING_WPM = 130

VOWELS = set("aeiou")

# Small, dependency-free English stop-word list used for keyword extraction.
STOP_WORDS = {
    "a", "about", "above", "after", "again", "all", "am", "an", "and", "any",
    "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "could", "did", "do", "does",
    "doing", "don", "down", "during", "each", "few", "for", "from", "further",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it",
    "its", "itself", "just", "me", "more", "most", "my", "myself", "no",
    "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other",
    "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should",
    "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "we",
    "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "will", "with", "would", "you", "your", "yours", "yourself", "yourselves",
}

WORD_RE = re.compile(r"[A-Za-z0-9']+")
TOKEN_RE = re.compile(r"\S+")
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _count_syllables(word: str) -> int:
    """
    Cheap heuristic syllable counter (good enough for readability scoring).
    Counts vowel groups, drops a silent trailing 'e', floors at 1.
    """
    word = word.lower().strip("'")
    if not word:
        return 0

    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)

    if word.endswith("e") and count > 1 and not word.endswith(("le", "ee", "ye")):
        count -= 1

    return max(count, 1)


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def top_keywords(text: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Most frequent meaningful words (stop-words and 1-char tokens removed)."""
    words = [w.lower() for w in WORD_RE.findall(text)]
    meaningful = [w for w in words if len(w) > 2 and w not in STOP_WORDS]

    total = len(meaningful) or 1
    counter = Counter(meaningful)

    return [
        {"word": word, "count": count, "share": _round(count * 100 / total, 1)}
        for word, count in counter.most_common(limit)
    ]


def analyze(text: str) -> Dict[str, Any]:
    """
    Produce the full metric set for a piece of text.

    Returns a flat dictionary so it can be stored as DB columns and rendered
    directly by the frontend without further shaping.
    """
    text = text or ""

    # --- raw character metrics -------------------------------------------
    char_count = len(text)
    spaces = sum(1 for ch in text if ch.isspace())
    char_no_space = char_count - spaces

    letters = sum(1 for ch in text if ch.isalpha())
    digits = sum(1 for ch in text if ch.isdigit())
    uppercase = sum(1 for ch in text if ch.isupper())
    lowercase = sum(1 for ch in text if ch.islower())
    vowels = sum(1 for ch in text.lower() if ch in VOWELS)
    consonants = letters - sum(1 for ch in text.lower() if ch in VOWELS and ch.isalpha())
    punctuation = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    emoji_like = sum(1 for ch in text if ord(ch) > 0x2100)

    # --- word metrics -----------------------------------------------------
    tokens = TOKEN_RE.findall(text)
    word_count = len(tokens)

    clean_words = [w.lower() for w in WORD_RE.findall(text)]
    unique_words = len(set(clean_words))

    longest_word = max(clean_words, key=len) if clean_words else ""
    shortest_word = min(clean_words, key=len) if clean_words else ""
    avg_word_len = (sum(len(w) for w in clean_words) / len(clean_words)) if clean_words else 0.0

    lexical_diversity = (unique_words / len(clean_words) * 100) if clean_words else 0.0

    # --- structure metrics ------------------------------------------------
    sentences = [s.strip() for s in SENTENCE_RE.findall(text) if s.strip()]
    sentence_count = len(sentences)

    lines = text.split("\n")
    line_count = len(lines) if text else 0
    non_empty_lines = sum(1 for ln in lines if ln.strip())
    paragraph_count = len([p for p in re.split(r"\n\s*\n", text) if p.strip()])

    avg_sentence_len = (len(clean_words) / sentence_count) if sentence_count else 0.0

    # --- readability ------------------------------------------------------
    syllables = sum(_count_syllables(w) for w in clean_words)
    if clean_words and sentence_count:
        flesch = (
            206.835
            - 1.015 * (len(clean_words) / sentence_count)
            - 84.6 * (syllables / len(clean_words))
        )
    else:
        flesch = 0.0
    flesch = max(0.0, min(100.0, flesch))

    if flesch >= 80:
        readability_label = "Very Easy"
    elif flesch >= 60:
        readability_label = "Easy"
    elif flesch >= 50:
        readability_label = "Fairly Hard"
    elif flesch >= 30:
        readability_label = "Difficult"
    else:
        readability_label = "Very Difficult"

    # --- time estimates ---------------------------------------------------
    reading_seconds = (word_count / READING_WPM) * 60 if word_count else 0.0
    speaking_seconds = (word_count / SPEAKING_WPM) * 60 if word_count else 0.0

    return {
        # counts
        "char_count": char_count,
        "char_no_space": char_no_space,
        "word_count": word_count,
        "unique_word_count": unique_words,
        "sentence_count": sentence_count,
        "line_count": line_count,
        "non_empty_lines": non_empty_lines,
        "paragraph_count": paragraph_count,
        "syllable_count": syllables,
        # composition
        "letters": letters,
        "digits": digits,
        "spaces": spaces,
        "punctuation": punctuation,
        "uppercase": uppercase,
        "lowercase": lowercase,
        "vowels": vowels,
        "consonants": max(consonants, 0),
        "emoji_like": emoji_like,
        # derived
        "avg_word_len": _round(avg_word_len),
        "avg_sentence_len": _round(avg_sentence_len),
        "lexical_diversity": _round(lexical_diversity, 1),
        "longest_word": longest_word,
        "shortest_word": shortest_word,
        "reading_seconds": _round(reading_seconds, 1),
        "speaking_seconds": _round(speaking_seconds, 1),
        "flesch_score": _round(flesch, 1),
        "readability": readability_label,
        # keywords
        "keywords": top_keywords(text, 10),
    }


# Columns that analyze() produces AND that we persist in SQLite.
PERSISTED_METRICS = [
    "char_count",
    "char_no_space",
    "word_count",
    "unique_word_count",
    "sentence_count",
    "line_count",
    "paragraph_count",
    "letters",
    "digits",
    "spaces",
    "punctuation",
    "uppercase",
    "vowels",
    "avg_word_len",
    "avg_sentence_len",
    "lexical_diversity",
    "longest_word",
    "reading_seconds",
    "flesch_score",
    "readability",
]


if __name__ == "__main__":  # quick manual check
    import json

    sample = "Hello world. This is a test of the analytics engine!\nIt handles lines, too."
    print(json.dumps(analyze(sample), indent=2))
