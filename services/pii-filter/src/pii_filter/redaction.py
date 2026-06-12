from collections import defaultdict

from pii_filter.detector import Entity


def redact_with_placeholders(
    text: str, entities: list[Entity]
) -> tuple[str, dict[str, str]]:
    """Replace entity spans in `text` with `[TYPE_N]` placeholders.

    Numbering is per-call and per-type, deduplicated by surface form
    (case-insensitive): two occurrences of "Martine" both become `[NAME_1]`,
    while "Martine" + "Paul" become `[NAME_1]` and `[NAME_2]`.

    Overlapping spans are resolved by keeping the highest-scoring one (the
    pipeline's `aggregation_strategy="simple"` already merges sub-tokens, but
    sliding-window chunking can occasionally surface duplicates at chunk
    boundaries).

    Returns the redacted text and a ``{placeholder: surface}`` mapping so callers
    can reverse the redaction (e.g. restore PII in an LLM response that echoes a
    placeholder). The surface stored is the first occurrence's original casing.
    """
    if not entities:
        return text, {}

    spans = _drop_overlaps(entities)

    counters: dict[str, dict[str, int]] = defaultdict(dict)
    mapping: dict[str, str] = {}
    for span in sorted(spans, key=lambda e: e["start"]):
        per_type = counters[span["type"]]
        key = span["surface"].lower()
        if key not in per_type:
            per_type[key] = len(per_type) + 1
            # First occurrence sets the placeholder; record its surface form.
            mapping[f"[{span['type']}_{per_type[key]}]"] = span["surface"]

    out = text
    for span in sorted(spans, key=lambda e: e["start"], reverse=True):
        n = counters[span["type"]][span["surface"].lower()]
        placeholder = f"[{span['type']}_{n}]"
        out = out[: span["start"]] + placeholder + out[span["end"] :]
    return out, mapping


def _drop_overlaps(entities: list[Entity]) -> list[Entity]:
    """Keep highest-scoring span when two entities overlap."""
    ordered = sorted(entities, key=lambda e: (e["start"], -e["score"]))
    kept: list[Entity] = []
    for span in ordered:
        if kept and span["start"] < kept[-1]["end"]:
            if span["score"] > kept[-1]["score"]:
                kept[-1] = span
            continue
        kept.append(span)
    return kept
