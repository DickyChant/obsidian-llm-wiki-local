"""Optional pre-defined concept taxonomy loaded from `vault-concepts.md`.

Without this file, olw discovers concepts purely from raw notes during
ingest — that's how the original pipeline worked. With the file, the
maintainer pre-declares canonical concept names, optionally with
parent/child hierarchy, and optionally with surface-form synonyms that
should *never* become their own articles.

File format — minimal markdown:

    # Comments start with # at column 0 and are ignored.
    # Blank lines are ignored.

    - Type One                       # canonical type, no synonyms
    - HGCAL : High Granularity Calorimeter, HGC
                                     # `:` introduces comma-separated synonyms
                                     # — they're folded into the canonical's
                                     # `aliases:` list, never compiled as
                                     # standalone articles.
    - Run                            # canonical type
      - Run Registry                 # nested = explicit named entity related
                                     # to the parent (its own short article)
    - Calibration Entry : CE         # type with one synonym

Concepts not declared but matching `<Type> <suffix>` (e.g. "Run 115808"
matches type "Run") are auto-classified as instances at compile time.

Output API
----------
``load_concept_taxonomy`` returns ``dict[str, str | None]`` (canonical
name → parent or None). Synonyms are NOT keys here — call
``load_concept_synonyms`` to map a canonical to its declared surface
forms. ``is_synonym`` answers "should this name *not* get its own
article?" used by compile to skip dupes.
"""

from __future__ import annotations

import re
from pathlib import Path

# Match `- Concept name [: syn1, syn2]` (with up to N leading spaces).
_BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)-\s+(?P<rest>.+?)\s*$")


def _vault_concepts_path(vault: Path) -> Path:
    return vault / "vault-concepts.md"


def _strip_inline_comment(s: str) -> str:
    """Drop a trailing `# comment` not inside a (presumed) name."""
    # Heuristic: only strip a `#` that is preceded by whitespace.
    m = re.search(r"\s+#.*$", s)
    return s[: m.start()] if m else s


def _parse_entry(rest: str) -> tuple[str, list[str]]:
    """Split `Name [: syn1, syn2, ...]` → (name, [syn1, syn2])."""
    rest = _strip_inline_comment(rest).strip()
    if ":" in rest:
        name_part, _, syn_part = rest.partition(":")
        name = name_part.strip()
        syns = [s.strip() for s in syn_part.split(",") if s.strip()]
        return name, syns
    return rest, []


def _read(vault: Path) -> str | None:
    path = _vault_concepts_path(vault)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def load_concept_taxonomy(vault: Path) -> dict[str, str | None]:
    """Return {canonical_name: parent_or_None} for every declared concept.

    Top-level bullets map to None (they're types). Nested bullets map to
    their immediate parent (always the most recent top-level bullet — we
    cap the hierarchy at one level for v1 to keep prompt rules simple).

    Surface-form synonyms (right of `:`) are NOT included in this dict;
    they are not standalone concepts. Use ``load_concept_synonyms`` for
    that mapping.

    Empty/missing file → empty dict (taxonomy disabled, ingest behaves
    as if no seeding happened).
    """
    text = _read(vault)
    if not text:
        return {}

    taxonomy: dict[str, str | None] = {}
    current_top: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = _BULLET_RE.match(line)
        if not m:
            continue
        indent = m.group("indent").replace("\t", "    ")
        name, _ = _parse_entry(m.group("rest"))
        if not name:
            continue
        if not indent:
            taxonomy[name] = None
            current_top = name
        else:
            taxonomy[name] = current_top
    return taxonomy


def load_concept_synonyms(vault: Path) -> dict[str, list[str]]:
    """Return {canonical_name: [synonym1, synonym2, ...]}.

    Only entries with a `:` clause appear (others have no synonyms).
    Synonyms are passed to compile as additional names that should be
    folded into the canonical article's frontmatter `aliases:` and that
    should NEVER be compiled as standalone articles.
    """
    text = _read(vault)
    if not text:
        return {}

    syns: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = _BULLET_RE.match(line)
        if not m:
            continue
        name, entry_syns = _parse_entry(m.group("rest"))
        if name and entry_syns:
            syns[name] = entry_syns
    return syns


def is_synonym(concept: str, vault: Path) -> str | None:
    """Return the canonical name that this concept is a synonym of, or None.

    Used by compile to skip writing a separate article for known synonyms.
    """
    syns = load_concept_synonyms(vault)
    for canonical, synonyms in syns.items():
        if concept == canonical:
            return None  # the canonical itself, not a synonym
        if concept in synonyms:
            return canonical
    return None


def classify_concept(
    concept: str, taxonomy: dict[str, str | None]
) -> tuple[str | None, bool, bool]:
    """Return (parent, is_instance, is_declared_type) for a concept.

    Resolution order:
      1. Exact match in taxonomy with parent None → (None, False, True)
         — explicitly listed top-level type. Compile uses the overview
         prompt branch.
      2. Exact match in taxonomy with non-None parent → (parent, True, False)
         — explicitly listed nested instance. Compile uses the instance
         prompt branch.
      3. Concept starts with "<Type> " for some top-level Type in the
         taxonomy → (Type, True, False). Implicit instance — same instance
         branch as (2). The space separator avoids false matches (e.g.
         "Calibration" vs "Calibration Entry").
      4. Otherwise → (None, False, False) — not in taxonomy, no special
         prompt branch.
    """
    if concept in taxonomy:
        parent = taxonomy[concept]
        if parent is None:
            return (None, False, True)
        return (parent, True, False)

    # Top-level types only (those whose taxonomy value is None).
    types = [name for name, parent in taxonomy.items() if parent is None]
    # Longest-prefix wins, so "Calibration Entry 0123" prefers "Calibration Entry"
    # over "Calibration" if both are listed.
    for type_name in sorted(types, key=len, reverse=True):
        if concept.startswith(type_name + " ") and len(concept) > len(type_name) + 1:
            return (type_name, True, False)
    return (None, False, False)
