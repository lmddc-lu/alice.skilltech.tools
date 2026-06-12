"""Tests for the span merge pass.

Cases drawn from real model output observed locally:
  - `marie@example.fr` returns 3 EMAIL spans split at `.` and within tokens.
  - `Martine` returns FIRSTNAME `Martin` + MIDDLENAME `e`.
"""

from pii_filter.detector import Entity
from pii_filter.postprocess import (
    expand_to_word_boundaries,
    merge_adjacent_spans,
)


def _ent(type_: str, start: int, end: int, text: str, score: float = 0.9) -> Entity:
    return Entity(
        type=type_,
        start=start,
        end=end,
        score=score,
        surface=text[start:end],
    )


def test_no_entities_returns_empty() -> None:
    assert merge_adjacent_spans([], "anything") == []


# --- word-boundary expansion ------------------------------------------------


def test_expand_subword_to_full_word() -> None:
    # Model labelled only "main" inside "Romain" -> expand to the whole word.
    text = "je m'appelle Romain"
    ent = _ent("FIRSTNAME", 15, 19, text)  # "main"
    assert ent["surface"] == "main"
    (out,) = expand_to_word_boundaries([ent], text)
    assert out["surface"] == "Romain"
    assert (out["start"], out["end"]) == (13, 19)


def test_expand_leaves_full_word_untouched() -> None:
    text = "je m'appelle Romain"
    ent = _ent("FIRSTNAME", 13, 19, text)  # already "Romain"
    (out,) = expand_to_word_boundaries([ent], text)
    assert out is ent  # unchanged object when nothing to expand


def test_expand_stops_at_separators() -> None:
    # Expansion must not swallow neighbouring words across spaces/punctuation.
    text = "Marie et Paul"
    ent = _ent("FIRSTNAME", 9, 11, text)  # "Pa"
    (out,) = expand_to_word_boundaries([ent], text)
    assert out["surface"] == "Paul"


def test_expand_handles_accented_letters() -> None:
    text = "ich heisse Müller"
    ent = _ent("LASTNAME", 13, 17, text)  # "ller"
    (out,) = expand_to_word_boundaries([ent], text)
    assert out["surface"] == "Müller"


def test_expand_then_merge_recovers_full_name() -> None:
    # End to end: a truncated first name expands and fuses with the surname.
    text = "Romain Dupont"
    ents = [
        _ent("FIRSTNAME", 2, 6, text),
        _ent("LASTNAME", 7, 13, text),
    ]  # "main","Dupont"
    expanded = expand_to_word_boundaries(ents, text)
    merged = merge_adjacent_spans(expanded, text)
    assert len(merged) == 1
    assert merged[0]["surface"] == "Romain Dupont"


def test_single_entity_returned_unchanged() -> None:
    text = "Hello Marie"
    spans = [_ent("FIRSTNAME", 6, 11, text)]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 1
    assert out[0]["surface"] == "Marie"


def test_split_email_is_merged_back() -> None:
    text = "Mon email est marie@example.fr aujourd'hui"
    spans = [
        _ent("EMAIL", 14, 22, text, score=0.99),  # "marie@ex"
        _ent("EMAIL", 23, 27, text, score=0.99),  # "mple"  (gap of 1 char "a"... wait)
    ]
    # Adjusting offsets: real model split was at `.`. Let's mirror that.
    text = "marie@example.fr"
    spans = [
        _ent("EMAIL", 0, 13, text, score=0.99),  # "marie@example"
        _ent("EMAIL", 14, 16, text, score=0.99),  # "fr", gap=1 (the dot)
    ]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 1
    assert out[0]["type"] == "EMAIL"
    assert out[0]["surface"] == "marie@example.fr"
    assert out[0]["start"] == 0
    assert out[0]["end"] == 16


def test_three_way_split_email_merges_into_one() -> None:
    text = "marie@example.fr"
    spans = [
        _ent("EMAIL", 0, 8, text, score=0.99),  # "marie@ex"
        _ent(
            "EMAIL", 9, 13, text, score=0.99
        ),  # "mple", gap "a"... hmm need real positions
    ]
    # Easier: synthetic three-fragment split with clean punctuation gaps.
    text = "abc.def.ghi"
    spans = [
        _ent("EMAIL", 0, 3, text),
        _ent("EMAIL", 4, 7, text),
        _ent("EMAIL", 8, 11, text),
    ]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 1
    assert out[0]["surface"] == "abc.def.ghi"


def test_name_family_fragments_merged() -> None:
    text = "Martine"
    spans = [
        _ent("FIRSTNAME", 0, 6, text, score=0.73),  # "Martin"
        _ent("MIDDLENAME", 6, 7, text, score=0.40),  # "e"
    ]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 1
    # Higher-scoring fragment's type wins.
    assert out[0]["type"] == "FIRSTNAME"
    assert out[0]["surface"] == "Martine"


def test_first_middle_last_collapse_into_one_person() -> None:
    text = "Marie Curie Sklodowska"
    spans = [
        _ent("FIRSTNAME", 0, 5, text, score=0.99),
        _ent("MIDDLENAME", 6, 11, text, score=0.80),
        _ent("LASTNAME", 12, 22, text, score=0.95),
    ]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 1
    assert out[0]["surface"] == "Marie Curie Sklodowska"
    # Highest-scoring of the three is FIRSTNAME at 0.99.
    assert out[0]["type"] == "FIRSTNAME"


def test_unrelated_types_not_merged() -> None:
    text = "Marie marie@x.fr"
    spans = [
        _ent("FIRSTNAME", 0, 5, text),
        _ent("EMAIL", 6, 16, text),
    ]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 2  # name + email stay separate


def test_gap_too_large_not_merged() -> None:
    text = "Marie est sympa et Paul aussi"
    spans = [
        _ent("FIRSTNAME", 0, 5, text),
        _ent("FIRSTNAME", 19, 23, text),  # 14-char gap full of letters
    ]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 2
    assert {s["surface"] for s in out} == {"Marie", "Paul"}


def test_alphanumeric_gap_blocks_merge() -> None:
    # Two same-type spans separated by a single letter: don't merge — that
    # letter is text the model didn't tag, not a separator.
    text = "abXcd"
    spans = [
        _ent("EMAIL", 0, 2, text),
        _ent("EMAIL", 3, 5, text),
    ]
    out = merge_adjacent_spans(spans, text)
    assert len(out) == 2


def test_merged_span_score_is_max_of_fragments() -> None:
    text = "abc.def"
    spans = [
        _ent("EMAIL", 0, 3, text, score=0.55),
        _ent("EMAIL", 4, 7, text, score=0.95),
    ]
    out = merge_adjacent_spans(spans, text)
    assert out[0]["score"] == 0.95


def test_max_gap_respected() -> None:
    # default max_gap=2: a 3-char punctuation gap should NOT merge.
    text = "a   b"  # 3 spaces between
    spans = [
        _ent("EMAIL", 0, 1, text),
        _ent("EMAIL", 4, 5, text),
    ]
    assert len(merge_adjacent_spans(spans, text)) == 2
    # Bumping max_gap=3 lets it through.
    out = merge_adjacent_spans(spans, text, max_gap=3)
    assert len(out) == 1
