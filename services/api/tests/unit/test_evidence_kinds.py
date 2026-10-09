"""The evidence vocabulary has one definition, in three places that must agree.

`NAMING.md` promised this file existed. It did not, and its absence cost a real bug: the
`control_mappings.evidence_kind` CHECK constraint in migration 0002 stopped at sixteen
values while the `evidence_kind` enum type in 0003 reached twenty-five, so the mappings
0005 adds for the newer kinds were rejected by a constraint written three migrations
earlier. Nothing caught it until the migrations met a real Postgres.

The three definitions:

  * ``EvidenceKind`` — the Python enum the API validates against;
  * ``CREATE TYPE evidence_kind`` in 0003 — what the database will store;
  * ``control_mappings`` seed rows — which kinds actually answer a control.

These tests read the migrations as text rather than through a database connection, so
they run in the unit suite and fail on a laptop before anyone waits on a container.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domains.evidence.schemas import DetectedBy, EvidenceKind, EvidenceOutcome

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _migration(name: str) -> str:
    return (VERSIONS / name).read_text(encoding="utf-8")


def _enum_labels(sql: str, type_name: str) -> list[str]:
    match = re.search(
        rf"CREATE TYPE {type_name} AS ENUM\s*\((.*?)\);",
        sql,
        re.S,
    )
    assert match, f"no CREATE TYPE {type_name} found"
    return re.findall(r"'([a-z0-9_]+)'", match.group(1))


# ----------------------------------------------------------------------
# Python enum vs database type
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("python_enum", "type_name"),
    [
        (EvidenceKind, "evidence_kind"),
        (EvidenceOutcome, "evidence_outcome"),
    ],
)
def test_python_and_database_vocabularies_are_identical(
    python_enum: type[EvidenceKind] | type[EvidenceOutcome], type_name: str
) -> None:
    """A value the API accepts but the database rejects is a 500 on ingest.

    A value the database allows but the API does not know is evidence that can never be
    written through a supported path, which is worse: it looks like a feature.
    """
    in_db = _enum_labels(_migration("0003_evidence.py"), type_name)
    in_python = [member.value for member in python_enum]

    assert sorted(in_db) == sorted(in_python), (
        f"{type_name}: only in DB {sorted(set(in_db) - set(in_python))}, "
        f"only in Python {sorted(set(in_python) - set(in_db))}"
    )


def test_the_database_type_has_no_duplicate_labels() -> None:
    labels = _enum_labels(_migration("0003_evidence.py"), "evidence_kind")
    assert len(labels) == len(set(labels))


def test_detected_by_values_match_the_migration_check() -> None:
    """``detected_by`` is a CHECK rather than an enum, so it drifts just as easily."""
    sql = _migration("0003_evidence.py")
    match = re.search(r"evidence_events_detected_valid[^)]*?detected_by IN \((.*?)\)", sql, re.S)
    assert match, "no detected_by CHECK found in 0003"
    in_db = set(re.findall(r"'([a-z0-9_]+)'", match.group(1)))

    assert in_db == {member.value for member in DetectedBy}


# ----------------------------------------------------------------------
# Every kind answers some control, and every mapping names a real kind
# ----------------------------------------------------------------------


#: A kind is always written immediately before its strength, in both seed shapes:
#: a VALUES tuple ``('iso-42001','A.3.2','ownership_record','satisfies',...)`` and a
#: direct ``SELECT fc.id, NULL, 'residency_proof', 'satisfies', ...``.
_KIND_BEFORE_STRENGTH = re.compile(
    r"'([a-z0-9_]+)',\s*\n?\s*'(?:satisfies|partially_satisfies|supports)'"
)


_SQL_BLOCK = re.compile(r'op\.execute\(\s*"""(.*?)"""\s*\)', re.S)


def _mapped_kinds() -> set[str]:
    """Evidence kinds referenced by a control_mappings seed row.

    Scoped to the ``op.execute`` blocks that insert mappings. Two narrower attempts were
    wrong in opposite directions: scanning whole files matched the
    ``CREATE TYPE mapping_strength AS ENUM ('satisfies',...)`` declaration and reported
    "satisfies" as a kind, and cutting each statement at the first semicolon truncated
    0005 at a semicolon inside a narrative string, hiding ten real mappings.
    """
    kinds: set[str] = set()
    for path in VERSIONS.glob("*.py"):
        for block in _SQL_BLOCK.findall(path.read_text(encoding="utf-8")):
            if "INSERT INTO control_mappings" in block:
                kinds.update(_KIND_BEFORE_STRENGTH.findall(block))
    return kinds


def test_every_mapping_names_a_known_evidence_kind() -> None:
    """The direction that broke. A mapping naming an unknown kind is a migration that
    fails on a database nobody has run it against yet."""
    known = {member.value for member in EvidenceKind}
    unknown = _mapped_kinds() - known
    assert not unknown, f"control_mappings reference unknown evidence kinds: {sorted(unknown)}"


def test_every_evidence_kind_answers_at_least_one_control() -> None:
    """Per NAMING.md: a kind with no mapping is evidence nobody asked for.

    We would collect it, store it for years, and never be able to point at a control it
    satisfies — cost with no coverage to show for it.
    """
    unmapped = {member.value for member in EvidenceKind} - _mapped_kinds()
    assert not unmapped, f"evidence kinds with no control mapping: {sorted(unmapped)}"
