"""Span post-processing.

The XLM-R sentencepiece tokenizer plus the model's `aggregation_strategy=
"simple"` regularly fragment a single PII surface form into adjacent spans:

    "marie@example.fr"     →  EMAIL "marie@ex" + EMAIL "mple" + EMAIL "fr"
    "Martine"              →  FIRSTNAME "Martin" + MIDDLENAME "e"

Both are clearly the same logical entity. We fuse them in two passes:

    1. Same-type adjacency: handles the split email / phone / IBAN case.
    2. Name-family adjacency: FIRSTNAME / MIDDLENAME / LASTNAME spans that
       sit next to each other belong to one person; merge them too.

Two adjacent spans are considered mergeable when the text between them is
short (<= ``max_gap`` characters) and contains no alphanumeric characters
i.e. only whitespace or punctuation. That guards against accidentally
fusing two genuinely separate entities ("Marie est sympa et Paul aussi").
"""

from __future__ import annotations

from pii_filter.detector import Entity

NAME_FAMILY: frozenset[str] = frozenset({"FIRSTNAME", "MIDDLENAME", "LASTNAME"})


def merge_adjacent_spans(
    entities: list[Entity], original_text: str, max_gap: int = 2
) -> list[Entity]:
    if not entities:
        return entities
    ordered = sorted(entities, key=lambda e: e["start"])
    same = _fuse(ordered, original_text, max_gap, _same_type)
    family = _fuse(same, original_text, max_gap, _name_family)
    return family


def expand_to_word_boundaries(
    entities: list[Entity], original_text: str
) -> list[Entity]:
    """Grow each span to cover the whole word(s) it touches.

    The XLM-R subword tokenizer can label only part of a token, so the model
    sometimes returns ``main`` for ``Romain`` (the ``Ro`` subword was labelled
    ``O``). Redacting only ``main`` would leak ``Ro`` to the LLM and store a
    partial surface in the mapping. We extend each span left/right over
    contiguous word characters so the full word is always captured.

    Runs before merging so the expanded spans can then fuse with neighbours.
    """
    if not entities:
        return entities
    n = len(original_text)
    out: list[Entity] = []
    for e in entities:
        start, end = e["start"], e["end"]
        while start > 0 and _is_word_char(original_text[start - 1]):
            start -= 1
        while end < n and _is_word_char(original_text[end]):
            end += 1
        if start == e["start"] and end == e["end"]:
            out.append(e)
        else:
            out.append(
                Entity(
                    type=e["type"],
                    start=start,
                    end=end,
                    score=e["score"],
                    surface=original_text[start:end],
                )
            )
    return out


def _is_word_char(char: str) -> bool:
    # Unicode-aware: isalnum() is True for accented letters (é, ü, ...).
    return char.isalnum()


def _same_type(a: Entity, b: Entity) -> bool:
    return a["type"] == b["type"]


def _name_family(a: Entity, b: Entity) -> bool:
    return a["type"] in NAME_FAMILY and b["type"] in NAME_FAMILY


def _fuse(
    spans: list[Entity],
    text: str,
    max_gap: int,
    types_compatible,  # type: ignore[no-untyped-def]
) -> list[Entity]:
    out: list[Entity] = []
    for span in spans:
        if out:
            prev = out[-1]
            gap = span["start"] - prev["end"]
            if 0 <= gap <= max_gap and types_compatible(prev, span):
                gap_text = text[prev["end"] : span["start"]]
                if not any(ch.isalnum() for ch in gap_text):
                    out[-1] = _merge(prev, span, text)
                    continue
        out.append(span)
    return out


def _merge(a: Entity, b: Entity, text: str) -> Entity:
    # Pick the type from the higher-scoring fragment, it's the model's
    # most confident guess, and ties go to the earlier (left) span.
    type_ = a["type"] if a["score"] >= b["score"] else b["type"]
    return Entity(
        type=type_,
        start=a["start"],
        end=b["end"],
        score=max(a["score"], b["score"]),
        surface=text[a["start"] : b["end"]],
    )
