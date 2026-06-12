from pii_filter.detector import Entity
from pii_filter.redaction import _drop_overlaps, redact_with_placeholders


def _ent(type_: str, start: int, end: int, text: str, score: float = 0.99) -> Entity:
    return Entity(
        type=type_,
        start=start,
        end=end,
        score=score,
        surface=text[start:end],
    )


def _redact(text: str, entities: list[Entity]) -> str:
    """Return just the redacted text (drops the mapping)."""
    return redact_with_placeholders(text, entities)[0]


def test_no_entities_returns_text_unchanged() -> None:
    assert _redact("hello world", []) == "hello world"


def test_single_name_replaced_with_typed_placeholder() -> None:
    text = "Est-ce que Martine est sympa?"
    entities = [_ent("FIRST_NAME", 11, 18, text)]
    assert _redact(text, entities) == "Est-ce que [FIRST_NAME_1] est sympa?"


def test_two_distinct_names_get_different_numbers() -> None:
    text = "Martine et Paul"
    entities = [
        _ent("FIRST_NAME", 0, 7, text),
        _ent("FIRST_NAME", 11, 15, text),
    ]
    assert _redact(text, entities) == "[FIRST_NAME_1] et [FIRST_NAME_2]"


def test_repeated_surface_form_shares_placeholder_number() -> None:
    text = "Martine connaît Martine"
    entities = [
        _ent("FIRST_NAME", 0, 7, text),
        _ent("FIRST_NAME", 16, 23, text),
    ]
    assert _redact(text, entities) == "[FIRST_NAME_1] connaît [FIRST_NAME_1]"


def test_case_insensitive_dedup() -> None:
    text = "MARTINE et martine"
    entities = [
        _ent("FIRST_NAME", 0, 7, text),
        _ent("FIRST_NAME", 11, 18, text),
    ]
    # Both surface forms collapse to NAME_1 even though casing differs.
    assert _redact(text, entities) == "[FIRST_NAME_1] et [FIRST_NAME_1]"


def test_different_types_have_independent_counters() -> None:
    text = "Marie marie@example.com"
    entities = [
        _ent("FIRST_NAME", 0, 5, text),
        _ent("EMAIL", 6, 23, text),
    ]
    assert _redact(text, entities) == "[FIRST_NAME_1] [EMAIL_1]"


def test_offsets_unchanged_with_long_placeholder() -> None:
    # If we substituted left-to-right naively, later spans would shift.
    text = "A Marie B Paul"
    entities = [
        _ent("FIRST_NAME", 2, 7, text),
        _ent("FIRST_NAME", 10, 14, text),
    ]
    assert _redact(text, entities) == "A [FIRST_NAME_1] B [FIRST_NAME_2]"


def test_overlapping_spans_keep_highest_score() -> None:
    text = "Marie Dubois"
    overlapping = [
        _ent("FIRST_NAME", 0, 12, text, score=0.7),  # whole span, lower score
        _ent("FIRST_NAME", 0, 5, text, score=0.95),  # just first name, higher
    ]
    kept = _drop_overlaps(overlapping)
    assert len(kept) == 1
    assert kept[0]["score"] == 0.95
    assert kept[0]["end"] == 5


def test_empty_text() -> None:
    assert _redact("", []) == ""


# --- mapping (placeholder -> original surface, for un-redaction) -------------


def test_mapping_maps_placeholders_back_to_surface() -> None:
    text = "Marie marie@example.com"
    entities = [
        _ent("FIRST_NAME", 0, 5, text),
        _ent("EMAIL", 6, 23, text),
    ]
    _, mapping = redact_with_placeholders(text, entities)
    assert mapping == {
        "[FIRST_NAME_1]": "Marie",
        "[EMAIL_1]": "marie@example.com",
    }


def test_mapping_keeps_first_occurrence_casing() -> None:
    text = "MARTINE et martine"
    entities = [
        _ent("FIRST_NAME", 0, 7, text),
        _ent("FIRST_NAME", 11, 18, text),
    ]
    _, mapping = redact_with_placeholders(text, entities)
    # Shared placeholder maps to the first occurrence's surface form.
    assert mapping == {"[FIRST_NAME_1]": "MARTINE"}


def test_mapping_empty_when_no_entities() -> None:
    _, mapping = redact_with_placeholders("hello", [])
    assert mapping == {}
