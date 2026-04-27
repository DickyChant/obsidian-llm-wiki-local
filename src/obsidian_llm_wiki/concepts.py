"""Optional pre-defined concept taxonomy loaded from `vault-concepts.md`.

Without this file, olw discovers concepts purely from raw notes during
ingest — that's how the original pipeline worked. With the file, the
maintainer pre-declares canonical concept names AND a one-level
parent/child hierarchy. Two effects:

1. Ingest's "existing concepts (reuse these names where applicable)"
   prompt hint includes the seeded names from the very first run, so
   the model doesn't invent variants like "Fixed-ADC" / "ADC (Fixed)" /
   "ADC fixed" when "Fixed ADC" is the canonical form.

2. Compile knows which articles are *types* and which are *instances*
   so it can route each through a different prompt branch (overview vs
   short instance article that links up).

File format — minimal markdown:

    # Comments start with # at column 0 and are ignored.
    # Blank lines are ignored.

    - Type One                 # top-level bullet → canonical type
    - Type Two
      - Named Instance A       # nested bullet (2- or 4-space indent) → child of Type Two
    - Run                      # types with no nested children are still types

Concepts not declared but matching `<Type> <suffix>` (e.g. "Run 115808"
matches type "Run") are auto-classified as instances at compile time.
"""

from __future__ import annotations

import re
from pathlib import Path

# Match `- Concept name` (with up to N leading spaces). Captures (indent, name).
_BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)-\s+(?P<name>.+?)\s*(?:#.*)?$")


def _vault_concepts_path(vault: Path) -> Path:
    return vault / "vault-concepts.md"


def load_concept_taxonomy(vault: Path) -> dict[str, str | None]:
    """Read vault-concepts.md and return {concept_name: parent_or_None}.

    Top-level bullets map to None (they're types). Nested bullets map to
    their immediate parent (always the most recent top-level bullet — we
    cap the hierarchy at one level for v1 to keep the prompt rules simple).

    Empty/missing file → empty dict (taxonomy disabled, ingest behaves as
    if no seeding happened).
    """
    path = _vault_concepts_path(vault)
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
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
        name = m.group("name").strip()
        if not name:
            continue
        if not indent:
            taxonomy[name] = None
            current_top = name
        else:
            # Nested → child of the most recent top-level bullet.
            taxonomy[name] = current_top
    return taxonomy


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
