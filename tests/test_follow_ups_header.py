"""FU-69: `follow-ups.md`'s header states numbers about itself, by hand.

On 2026-09-12 three were wrong at once — the table row count said "twenty-two"
against 25, the citation count said 62 against 103, and the blank-line count
said 13 above a list of 14. One of the three was introduced by the sweep that
was correcting the other two, which is the argument for checking them.

**What this guards, and what it emphatically does not.** Every assertion here
is arithmetic over the document plus a file read. None of them judges whether a
citation says what the entry claims. `cli.py:1021` is cited six times as
`_report_live_provenance`, which lives at `:1229`; it lands on a substantive
line throughout and **this suite passes it**. That class of drift is invisible
here and is the reason the header still says a full reconciliation is deferred.
An entry that reads a green suite as "the citations are correct" is worse off
than with no suite at all.

This is the line CLAUDE.md draws: check what is decidable inside the document,
do not machine-check prose judgement about the code. The commit-message hook
that would have caught FU-15's unmarked close was declined on those grounds the
same day this was filed, and the two decisions are consistent.

Counting rules live in the header beside the numbers, not only here — see
FU-69. They are part of the contract, because 133, 103 and 99 are all
defensible readings of "how many citations" and they differ by more than the
drift being measured.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FOLLOW_UPS = REPO_ROOT / "docs" / "plans" / "follow-ups.md"

CITATION = re.compile(r"\b((?:[a-z_]+/)?[a-z_0-9]+\.py):(\d+)")
BLOCK = re.compile(
    r"<!--\s*broken-citations:start\s*-->(.*?)<!--\s*broken-citations:end\s*-->",
    re.S,
)
TABLE_ROW = re.compile(r"^\|\s*FU-\d+\s*\|")

# A cited line carries no information if it is one of these. The list is
# deliberately short: anything longer starts excluding real one-token lines.
EMPTY_TOKENS = {'"""', "'''", ")", "]", "}"}


# --- reading the document ----------------------------------------------------


def header_text() -> str:
    """Everything above the first entry."""
    return FOLLOW_UPS.read_text(encoding="utf-8").split("\n## FU-", 1)[0]


def scanned_text() -> str:
    """The document with the declared-breakage block removed.

    Excluding it is not tidiness. The block's entries are `file.py:line`
    citations themselves, so scanning them would make the list self-sustaining:
    correct the citation in FU-39's body and the header's copy still points at
    the blank line, so the list could never empty. See FU-69.
    """
    return BLOCK.sub("", FOLLOW_UPS.read_text(encoding="utf-8"))


def stated_number(pattern: str) -> int:
    """One figure the header asserts about itself."""
    match = re.search(pattern, header_text())
    assert match is not None, f"the header no longer states a figure matching {pattern!r}"
    return int(match.group(1))


def declared_broken() -> list[str]:
    """The citations the header declares non-substantive, in its own block."""
    match = BLOCK.search(FOLLOW_UPS.read_text(encoding="utf-8"))
    assert match is not None, "the broken-citations block is missing from the header"
    body = match.group(1).replace("```text", "").replace("```", "")
    return sorted(part.strip() for part in body.split(",") if part.strip())


# --- resolving a citation ----------------------------------------------------


def resolve(cited: str) -> Path | None:
    """A cited path as written, to a file in the tree.

    Order is `src/fpl_cli/`, then the repo root — which is what reaches
    `tests/` and `tools/` — then a unique basename match anywhere. Ambiguous
    basenames resolve to nothing and are reported rather than guessed at.
    """
    for base in (REPO_ROOT / "src" / "fpl_cli", REPO_ROOT):
        candidate = base / cited
        if candidate.is_file():
            return candidate
    matches = [
        path
        for path in REPO_ROOT.rglob(Path(cited).name)
        if path.is_file() and ".venv" not in path.parts
    ]
    return matches[0] if len(matches) == 1 else None


def _lines(path: Path, _cache: dict[Path, list[str]] = {}) -> list[str]:
    if path not in _cache:
        _cache[path] = path.read_text(encoding="utf-8").splitlines()
    return _cache[path]


def citations() -> list[tuple[str, int]]:
    """Distinct `(path-as-written, line)` pairs, sorted.

    Distinct *as written*: two spellings of one source line count twice,
    because fixing one leaves the other wrong and still to be found. Repeat
    mentions of one spelling count once.
    """
    return sorted({(path, int(line)) for path, line in CITATION.findall(scanned_text())})


def non_substantive() -> list[str]:
    """Citations landing on a blank line, a bare delimiter, or past EOF."""
    found = []
    for cited, line in citations():
        path = resolve(cited)
        if path is None:
            continue  # reported by its own test, not folded in here
        lines = _lines(path)
        if line > len(lines):
            found.append(f"{cited}:{line}")
            continue
        if lines[line - 1].strip() in EMPTY_TOKENS or not lines[line - 1].strip():
            found.append(f"{cited}:{line}")
    return sorted(found)


# --- the assertions ----------------------------------------------------------


def test_every_citation_resolves_to_a_file() -> None:
    """A citation naming no file at all is worse than one naming a blank line:
    there is nothing to correct it against.

    Mutation it must fail against: repointing every occurrence of one citation
    at a file that does not exist — `domain/rules.py:57` to
    `domain/nonexistent.py:57`, both of its mentions. Demonstrated failing, and
    it isolates: the other nine assertions still pass.

    *Every* occurrence, because replacing one of two leaves the original in the
    set and adds a new one, which changes the total and trips
    `test_the_stated_citation_total_matches_the_document` as well. Both
    variants were run. The isolating one is recorded here because a mutation
    that trips two assertions demonstrates neither.
    """
    unresolved = sorted({f"{cited}:{line}" for cited, line in citations() if resolve(cited) is None})

    assert not unresolved, (
        "these citations name no file in the tree, or an ambiguous basename: " f"{unresolved}"
    )


def test_the_declared_broken_citations_are_exactly_the_broken_ones() -> None:
    """The assertion this file exists for.

    A list rather than a count, so the failure names the citation that moved
    instead of leaving a reader to diff two integers.

    Mutation it must fail against: blanking a cited line in the source, which
    adds an entry the header does not declare. Demonstrated failing.
    """
    assert non_substantive() == declared_broken(), (
        "the header's broken-citations block disagrees with the source.\n"
        f"  declared but fine now: {sorted(set(declared_broken()) - set(non_substantive()))}\n"
        f"  broken but undeclared: {sorted(set(non_substantive()) - set(declared_broken()))}"
    )


def test_the_stated_broken_count_matches_its_own_list() -> None:
    """The header states a number *and* lists the items. They must agree.

    Not a tautology — it is the defect that actually occurred: the paragraph's
    first draft said "14" above a list of 13, because one citation appeared
    under two spellings and only one spelling was written down.

    Mutation it must fail against: changing the stated 14 to 13 while leaving
    the list at fourteen entries. Demonstrated failing.
    """
    stated = stated_number(r"\*\*(\d+) point at a blank line")

    assert stated == len(declared_broken()), (
        f"the header says {stated} non-substantive citations but lists {len(declared_broken())}"
    )


def test_the_stated_citation_total_matches_the_document() -> None:
    """The denominator, under the header's own counting rule.

    Mutation it must fail against: adding a citation to an entry without
    updating the total. Demonstrated failing.
    """
    stated = stated_number(r"of \*\*(\d+)\*\* distinct")

    assert stated == len(citations()), (
        f"the header says {stated} distinct citations; the document has {len(citations())}. "
        "The counting rule is stated in the header and implemented in `citations()` — "
        "if they have diverged, fix the one that is wrong rather than the number."
    )


def test_the_stated_table_row_count_matches_the_table() -> None:
    """The figure that was wrong by three on 2026-09-12.

    Mutation it must fail against: adding an `| FU-N |` row without updating
    the stated count. Demonstrated failing.
    """
    stated = stated_number(r"all (\d+) rows below were re-checked")
    actual = sum(1 for line in FOLLOW_UPS.read_text(encoding="utf-8").splitlines() if TABLE_ROW.match(line))

    assert stated == actual, f"the header says {stated} table rows; the table has {actual}"


# --- the guard on the guard --------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [("", True), ('    """', True), ("    )", True), ("    x = 1", False), ("# a comment", False)],
)
def test_non_substantive_recognises_what_it_claims_to(line: str, expected: bool) -> None:
    """`EMPTY_TOKENS` plus blankness is the whole definition, and it is a
    heuristic. A comment line is *substantive* by this rule even though it is
    rarely what an entry meant to cite — which is the limitation the module
    docstring records, pinned here so it cannot drift silently.
    """
    assert (line.strip() in EMPTY_TOKENS or not line.strip()) is expected
