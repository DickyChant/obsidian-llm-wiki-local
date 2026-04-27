"""Unit tests for the seeded concept-taxonomy loader and classifier."""

from __future__ import annotations

from pathlib import Path

from obsidian_llm_wiki.concepts import (
    classify_concept,
    is_synonym,
    load_concept_synonyms,
    load_concept_taxonomy,
)


def _write(vault: Path, body: str) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "vault-concepts.md").write_text(body, encoding="utf-8")


def test_load_concept_taxonomy_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_concept_taxonomy(tmp_path) == {}


def test_load_concept_taxonomy_empty_file_returns_empty(tmp_path: Path) -> None:
    _write(tmp_path, "")
    assert load_concept_taxonomy(tmp_path) == {}


def test_load_concept_taxonomy_parses_top_level_bullets(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
- Run
- DQM
- Calibration Entry
""",
    )
    tax = load_concept_taxonomy(tmp_path)
    assert tax == {"Run": None, "DQM": None, "Calibration Entry": None}


def test_load_concept_taxonomy_parses_nested_bullets(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
- Run
- DQM
  - DQM digest
- HGCAL
  - High Granularity Calorimeter
""",
    )
    tax = load_concept_taxonomy(tmp_path)
    assert tax == {
        "Run": None,
        "DQM": None,
        "DQM digest": "DQM",
        "HGCAL": None,
        "High Granularity Calorimeter": "HGCAL",
    }


def test_load_concept_taxonomy_ignores_comments_and_blanks(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """# leading comment
# another comment

- Run

  # comment-style line that begins with hash after whitespace is also fine
- DQM
""",
    )
    tax = load_concept_taxonomy(tmp_path)
    assert tax == {"Run": None, "DQM": None}


def test_load_concept_taxonomy_handles_tab_indent(tmp_path: Path) -> None:
    _write(tmp_path, "- Run\n\t- Run nested\n")
    tax = load_concept_taxonomy(tmp_path)
    assert tax == {"Run": None, "Run nested": "Run"}


def test_load_concept_taxonomy_strips_trailing_inline_comment(tmp_path: Path) -> None:
    _write(tmp_path, "- Run    # the canonical type\n  - Run instance # nested\n")
    tax = load_concept_taxonomy(tmp_path)
    assert tax == {"Run": None, "Run instance": "Run"}


def test_classify_concept_empty_taxonomy_no_match(tmp_path: Path) -> None:
    assert classify_concept("Run 115808", {}) == (None, False, False)


def test_classify_concept_verbatim_top_level_type() -> None:
    tax = {"Run": None, "DQM": None}
    assert classify_concept("Run", tax) == (None, False, True)
    assert classify_concept("DQM", tax) == (None, False, True)


def test_classify_concept_verbatim_explicit_instance() -> None:
    tax = {"DQM": None, "DQM digest": "DQM"}
    assert classify_concept("DQM digest", tax) == ("DQM", True, False)


def test_classify_concept_prefix_implicit_instance() -> None:
    tax = {"Run": None, "Calibration Entry": None}
    # "Run 115808" starts with "Run " → implicit instance of Run
    assert classify_concept("Run 115808", tax) == ("Run", True, False)
    # "Calibration Entry MH_F1W" starts with "Calibration Entry " → instance
    assert classify_concept("Calibration Entry MH_F1W", tax) == ("Calibration Entry", True, False)


def test_classify_concept_longest_prefix_wins() -> None:
    """Avoid mis-classifying 'Calibration Entry 0123' as instance of 'Calibration'."""
    tax = {"Calibration": None, "Calibration Entry": None}
    parent, is_instance, is_type = classify_concept("Calibration Entry 0123", tax)
    assert (parent, is_instance, is_type) == ("Calibration Entry", True, False)


def test_classify_concept_no_match_when_not_a_prefix() -> None:
    tax = {"Run": None}
    # "Runtime" doesn't have a space after Run → not an instance.
    assert classify_concept("Runtime", tax) == (None, False, False)
    # "Run" alone matches verbatim as a type, not an instance.
    assert classify_concept("Run", tax) == (None, False, True)


def test_classify_concept_unknown_returns_no_branch() -> None:
    tax = {"Run": None, "DQM": None}
    assert classify_concept("Random concept name", tax) == (None, False, False)


# ── ":" inline-synonym syntax ──────────────────────────────────────────────


def test_load_concept_taxonomy_inline_syntax_excludes_synonyms_from_taxonomy(tmp_path: Path) -> None:
    """Synonyms after `:` are NOT canonical concepts — they must not appear in the taxonomy keys."""
    _write(
        tmp_path,
        """
- HGCAL : High Granularity Calorimeter, HGC
- Run
- Calibration Entry : CE
""",
    )
    tax = load_concept_taxonomy(tmp_path)
    # Only the canonical names appear as keys.
    assert tax == {"HGCAL": None, "Run": None, "Calibration Entry": None}
    # Synonyms should NOT be misread as canonicals.
    for syn in ("High Granularity Calorimeter", "HGC", "CE"):
        assert syn not in tax


def test_load_concept_synonyms_returns_canonical_to_aliases_map(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
- HGCAL : High Granularity Calorimeter, HGC
- Run
- Calibration Entry : CE
""",
    )
    syns = load_concept_synonyms(tmp_path)
    assert syns == {
        "HGCAL": ["High Granularity Calorimeter", "HGC"],
        "Calibration Entry": ["CE"],
    }
    assert "Run" not in syns  # no synonyms for Run


def test_load_concept_synonyms_handles_nested_with_synonyms(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
- DQM : Data Quality Monitoring
  - DQM digest
""",
    )
    tax = load_concept_taxonomy(tmp_path)
    syns = load_concept_synonyms(tmp_path)
    assert tax == {"DQM": None, "DQM digest": "DQM"}
    assert syns == {"DQM": ["Data Quality Monitoring"]}


def test_load_concept_synonyms_empty_when_no_colons(tmp_path: Path) -> None:
    _write(tmp_path, "- Run\n- DQM\n")
    assert load_concept_synonyms(tmp_path) == {}


def test_load_concept_synonyms_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_concept_synonyms(tmp_path) == {}


def test_is_synonym_resolves_to_canonical(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
- HGCAL : High Granularity Calorimeter, HGC
- DQM : Data Quality Monitoring
- Run
""",
    )
    assert is_synonym("High Granularity Calorimeter", tmp_path) == "HGCAL"
    assert is_synonym("HGC", tmp_path) == "HGCAL"
    assert is_synonym("Data Quality Monitoring", tmp_path) == "DQM"
    # Canonicals are NOT their own synonym.
    assert is_synonym("HGCAL", tmp_path) is None
    assert is_synonym("Run", tmp_path) is None
    # Not declared at all → not a synonym.
    assert is_synonym("Random concept", tmp_path) is None


def test_strip_inline_comment_does_not_eat_colons(tmp_path: Path) -> None:
    """Make sure `:` in synonyms isn't mistaken for a comment delimiter."""
    _write(tmp_path, "- HGCAL : High Granularity Calorimeter # the canonical type\n")
    tax = load_concept_taxonomy(tmp_path)
    syns = load_concept_synonyms(tmp_path)
    assert tax == {"HGCAL": None}
    assert syns == {"HGCAL": ["High Granularity Calorimeter"]}
