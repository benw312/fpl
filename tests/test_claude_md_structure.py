"""Two hand-maintained module lists must agree with the tree (FU-19).

`CLAUDE.md`'s Structure block and the README's Architecture table both name
every module in `src/fpl_cli/`, and both are maintained by hand.

The block is a hand-maintained list of every module in `src/fpl_cli/`, and
nothing checked it, so it was wrong by default: right only while someone
remembered, wrong from the moment a module landed. It went wrong twice the same
way — `b522572` added `builder.py` while writing *"Not yet written: … interactive
squad builder"* in the same diff, and the `plan optimise` work added
`domain/optimizer.py` while leaving *"Not yet written: domain/optimizer.py"*
standing. Both times the commit that created the module was the commit that
falsified the line describing it as missing, which is why no later commit caught
it: there is nothing to notice unless something reads both.

So this reads both. It follows FU-3's AST scan (`test_cli_exit_codes.py`): scan
the source rather than the behaviour, and name the drift in the failure so the
message says what to change rather than that something is wrong.

**Two documents, two parsers, one checker.** The formats differ more than a
single parser can absorb: `CLAUDE.md` groups modules under a package heading and
wraps across lines (``​`domain/` — rules.py, squad.py,`` …), while the README
gives one fully-qualified path per table row (``| `domain/rules.py` | … |``). A
parser accepting both shapes would accept either shape in either document, which
is a worse guarantee than the one being bought. So each document gets a small
reader that produces the same `{group: {modules}}` mapping, and `structure_drift`
— the part that actually decides anything — is shared and takes the reader as an
argument. Aligning the two formats instead would mean rewriting one document's
list into the other's shape: the README table carries a per-module description
column that `CLAUDE.md`'s comma-separated lines have nowhere to put, so alignment
means either losing those descriptions or expanding `CLAUDE.md` from 8 lines to
17 rows in a file loaded into context every session. Neither is worth one parser.

`__init__.py` is excluded throughout. Neither document lists any, they carry no
implementation in this repo, and listing four empty files would be noise that
made both harder to keep true — the opposite of the point.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
README_MD = REPO_ROOT / "README.md"
SRC_ROOT = REPO_ROOT / "src" / "fpl_cli"

TOP_LEVEL = "top level"

# A module name as the block writes it: `snapshots.py`, optionally qualified by
# its package as `domain/optimizer.py`. Matching tokens rather than splitting on
# commas is what lets the block carry prose — the parenthetical after
# `presentation.py` mentions a `presentation/` package and an FU number, and
# neither looks like a module.
_MODULE = re.compile(r"(?:([a-z_][a-z0-9_]*)/)?([a-z_][a-z0-9_]*\.py)")

_DIR_HEADING = re.compile(r"^`([a-z_][a-z0-9_]*)/`\s*—")
_TOP_HEADING = re.compile(r"^Top level\s*—")
_ABSENT_HEADING = re.compile(r"^Not yet written:")


def structure_section(text: str) -> str:
    """The `## Structure` section of `CLAUDE.md`, up to the next heading."""
    match = re.search(r"^## Structure$(.*?)^## ", text, flags=re.M | re.S)
    assert match is not None, "CLAUDE.md has no `## Structure` section"
    return match.group(1)


def parse_structure(text: str) -> tuple[dict[str, set[str]], set[str]]:
    """`({group: {module, …}}, {modules claimed not yet written})`.

    Groups are package names plus `top level`. A heading line opens a group and
    every following line accumulates into it until the next heading or a **blank
    line**, which is what makes the wrapped `domain/` list parse as one group
    rather than losing `evaluation.py` off the end of it.

    Terminating on a blank line rather than on a list of known prose openings is
    deliberate. The block is followed by sentences that mention paths — the
    pointer to this very test names `tests/test_claude_md_structure.py` — and a
    parser that had to recognise each such sentence would need updating whenever
    the surrounding prose changed. That is the hand-maintenance this test exists
    to remove, reintroduced one level down. Nothing before the first heading
    accumulates either, since no group is open yet.
    """
    groups: dict[str, set[str]] = {}
    absent: set[str] = set()
    current: set[str] | None = None

    for raw in structure_section(text).splitlines():
        line = raw.strip()
        if not line:
            current = None
            continue
        if (heading := _DIR_HEADING.match(line)) is not None:
            current = groups.setdefault(heading.group(1), set())
        elif _TOP_HEADING.match(line):
            current = groups.setdefault(TOP_LEVEL, set())
        elif _ABSENT_HEADING.match(line):
            current = absent
        if current is None:
            continue
        for package, module in _MODULE.findall(line):
            current.add(f"{package}/{module}" if package else module)

    return groups, absent


_TABLE_ROW = re.compile(r"^\|(?P<first>[^|]*)\|")


def architecture_section(text: str) -> str:
    """The `## Architecture` section of the README, up to the next heading."""
    match = re.search(r"^## Architecture$(.*?)^## ", text, flags=re.M | re.S)
    assert match is not None, "README.md has no `## Architecture` section"
    return match.group(1)


def parse_architecture(text: str) -> tuple[dict[str, set[str]], set[str]]:
    """The README's Architecture table, in `parse_structure`'s shape.

    One fully-qualified path per row, so the grouping comes from the path rather
    than from a heading. Only the **first cell** of each row is read: the
    description column is prose, and the prose below the table names
    `tests/test_claude_md_structure.py`, which a laxer reader would invent a
    `tests/` package from — the same trap that broke the first draft of the
    CLAUDE.md parser, arriving by a different route.

    The second element is always empty: the README has no "Not yet written"
    line, and inventing one so both parsers return the same tuple would be
    symmetry for its own sake. It is returned so `structure_drift` can take
    either reader without caring which document it is reading.
    """
    groups: dict[str, set[str]] = {}
    for raw in architecture_section(text).splitlines():
        row = _TABLE_ROW.match(raw.strip())
        if row is None:
            continue
        for package, module in _MODULE.findall(row.group("first")):
            groups.setdefault(package or TOP_LEVEL, set()).add(module)
    return groups, set()


def tree_structure() -> dict[str, set[str]]:
    """The same shape, read off the filesystem."""
    groups: dict[str, set[str]] = {
        TOP_LEVEL: {path.name for path in SRC_ROOT.glob("*.py") if path.name != "__init__.py"}
    }
    for directory in sorted(SRC_ROOT.iterdir()):
        if not directory.is_dir() or directory.name.startswith((".", "__")):
            continue
        groups[directory.name] = {
            path.name for path in directory.glob("*.py") if path.name != "__init__.py"
        }
    return groups


def structure_drift(
    text: str,
    actual: dict[str, set[str]] | None = None,
    *,
    parser: Callable[[str], tuple[dict[str, set[str]], set[str]]] = parse_structure,
    document: str = "CLAUDE.md",
) -> list[str]:
    """Every disagreement between a document's module list and the tree, named.

    Returned as a list rather than raised on the first one so a single run
    reports everything that needs changing — the block is edited by hand, and
    being sent back three times for three modules is how it stops being edited.

    `parser` and `document` are what let one checker serve both documents: the
    reader turns each format into the same mapping, and `document` names which
    file a message is about — necessary now that a module can be missing from
    two places, and a message saying only "does not list it" would send the
    reader to the wrong file.

    `actual` is injectable so the self-checks below can describe a fixed tree.
    They used to read the real one, which meant adding any module to
    `src/fpl_cli/` failed six of them alongside the guard — a check that noisy
    is a check someone deletes, which is the failure this whole entry is about.
    Only `test_claude_md_structure_matches_the_tree` touches the filesystem.
    """
    documented, absent = parser(text)
    actual = tree_structure() if actual is None else actual
    drift: list[str] = []

    for group in sorted(set(documented) | set(actual)):
        listed = documented.get(group)
        present = actual.get(group)
        if present is None:
            drift.append(f"{document}: `{group}/` is listed but is not a package in src/fpl_cli/")
            continue
        if listed is None:
            drift.append(
                f"{document}: `{group}/` exists in src/fpl_cli/ but nothing in it lists the package "
                f"(contains: {', '.join(sorted(present))})"
            )
            continue
        where = TOP_LEVEL if group == TOP_LEVEL else f"`{group}/`"
        for module in sorted(present - listed):
            drift.append(f"{document}: {where}: {module} exists but is not listed")
        for module in sorted(listed - present):
            drift.append(f"{document}: {where}: {module} is listed but does not exist")

    for entry in sorted(absent):
        # Resolved against the same mapping as everything else rather than by
        # stat-ing the path, so one source of truth answers "does this exist"
        # and the self-checks can exercise this branch too.
        group, _, module = entry.rpartition("/")
        searched = [actual.get(group, set())] if group else list(actual.values())
        if any(module in members for members in searched):
            drift.append(
                f'{document}: "Not yet written" names {entry}, which exists — remove it from that line'
            )

    return drift


def test_claude_md_structure_matches_the_tree() -> None:
    """The guard. Two regressions by the same mechanism is a missing check, not
    a third correction to make by hand."""
    drift = structure_drift(CLAUDE_MD.read_text(encoding="utf-8"))

    assert not drift, "CLAUDE.md's Structure block disagrees with src/fpl_cli/:\n  " + "\n  ".join(
        drift
    )


def test_readme_architecture_matches_the_tree() -> None:
    """The third instance, and the second document.

    The README's table went stale within two days of being written, by exactly
    the mechanism FU-19 closed for `CLAUDE.md`: the merge that added
    `domain/variants.py` did not touch the table naming every module. That is
    twice for one document and three times overall, which is a missing check
    rather than three corrections to make by hand.
    """
    drift = structure_drift(
        README_MD.read_text(encoding="utf-8"),
        parser=parse_architecture,
        document="README.md",
    )

    assert not drift, "README.md's Architecture table disagrees with src/fpl_cli/:\n  " + "\n  ".join(
        drift
    )


# --- the guard is only worth having if it fails ------------------------------


def _block(domain_line: str, absent_line: str = "") -> str:
    """A minimal Structure block in the shape CLAUDE.md uses, for the checks
    below to mutate one line of.

    The blank line before the trailing prose is load-bearing and mirrors the
    real block: it is what closes the last group. The prose deliberately names a
    path (`tests/…`) so these checks cover the case that broke the first draft
    of this parser.
    """
    return (
        "## Structure\n"
        "All paths under `src/fpl_cli/`:\n"
        "`api/` — official.py, models.py, snapshots.py\n"
        f"{domain_line}\n"
        "`storage/` — cache.py, capture.py\n"
        "Top level — cli.py, transport.py, builder.py, presentation.py (one file by\n"
        "decision, not by drift — see FU-18)\n"
        "\n"
        f"{absent_line}"
        "This block is checked by `tests/test_claude_md_structure.py`.\n"
        "See `docs/plans/` for written plans.\n"
        "\n## Rules\n"
    )


_TRUE_DOMAIN = (
    "`domain/` — rules.py, squad.py, transfers.py, projections.py, strength.py,\n"
    "evaluation.py, optimizer.py"
)

# The tree `_block()` describes. Fixed, not read from disk: these checks are
# about the comparison, not about what happens to be in `src/fpl_cli/` today.
_FAKE_TREE: dict[str, set[str]] = {
    "api": {"official.py", "models.py", "snapshots.py"},
    "domain": {
        "rules.py",
        "squad.py",
        "transfers.py",
        "projections.py",
        "strength.py",
        "evaluation.py",
        "optimizer.py",
    },
    "storage": {"cache.py", "capture.py"},
    TOP_LEVEL: {"cli.py", "transport.py", "builder.py", "presentation.py"},
}


def test_the_guard_passes_on_a_block_that_matches() -> None:
    """The control. Every mutation below is only evidence if this baseline is
    clean — a guard that failed on everything would 'catch' them all."""
    assert structure_drift(_block(_TRUE_DOMAIN), _FAKE_TREE) == []


def test_the_guard_catches_a_module_missing_from_the_block() -> None:
    """FU-19's actual regression, twice over: a module lands and the block is
    not updated."""
    dropped = _TRUE_DOMAIN.replace(", optimizer.py", "")

    drift = structure_drift(_block(dropped), _FAKE_TREE)

    assert drift == ["CLAUDE.md: `domain/`: optimizer.py exists but is not listed"]


def test_the_guard_catches_a_not_yet_written_line_naming_a_module_that_exists() -> None:
    """The other half of the same regression, and the half that misleads rather
    than merely omits — the block asserted `optimizer.py` was absent while it
    was 960 lines."""
    drift = structure_drift(_block(_TRUE_DOMAIN, "Not yet written: domain/optimizer.py.\n"), _FAKE_TREE)

    assert drift == [
        'CLAUDE.md: "Not yet written" names domain/optimizer.py, which exists — '
        "remove it from that line"
    ]


def test_the_guard_catches_a_module_listed_that_does_not_exist() -> None:
    """The opposite drift: a module is deleted or renamed and the block keeps
    naming it. Untested, this direction would go unnoticed — the two regressions
    so far were both omissions."""
    invented = _TRUE_DOMAIN + ", chips.py"

    drift = structure_drift(_block(invented), _FAKE_TREE)

    assert drift == ["CLAUDE.md: `domain/`: chips.py is listed but does not exist"]


def test_the_guard_catches_a_whole_package_the_block_never_mentions() -> None:
    """A new package is the case a per-module diff would miss entirely, because
    there is no group to compare its contents against."""
    block = _block(_TRUE_DOMAIN).replace("`storage/` — cache.py, capture.py\n", "")

    drift = structure_drift(block, _FAKE_TREE)

    assert drift == [
        "CLAUDE.md: `storage/` exists in src/fpl_cli/ but nothing in it lists the package "
        "(contains: cache.py, capture.py)"
    ]


def test_every_drift_is_reported_not_just_the_first() -> None:
    """Three faults, three lines. The block is edited by hand; being sent back
    once per module is how it stops being edited at all."""
    block = _block(_TRUE_DOMAIN.replace(", optimizer.py", "") + ", chips.py")

    drift = structure_drift(block.replace("`storage/` — cache.py, capture.py\n", ""), _FAKE_TREE)

    assert sorted(drift) == sorted(
        [
            "CLAUDE.md: `domain/`: optimizer.py exists but is not listed",
            "CLAUDE.md: `domain/`: chips.py is listed but does not exist",
            "CLAUDE.md: `storage/` exists in src/fpl_cli/ but nothing in it lists the package "
            "(contains: cache.py, capture.py)",
        ]
    )


def test_the_wrapped_domain_list_parses_as_one_group() -> None:
    """`domain/`'s list wraps onto a second line in CLAUDE.md. If continuation
    lines were dropped, `evaluation.py` would read as missing and the guard
    would fail for a reason that has nothing to do with the tree."""
    documented, _ = parse_structure(_block(_TRUE_DOMAIN))

    assert "evaluation.py" in documented["domain"]
    assert "optimizer.py" in documented["domain"]


def test_prose_in_the_block_is_not_parsed_as_modules() -> None:
    """Two ways prose could be mistaken for modules, both real.

    The `Top level` line carries a parenthetical naming an FU number, which a
    parser splitting on commas would invent a module from. And the sentences
    *after* the block name `tests/test_claude_md_structure.py` — the pointer to
    this file — which the first draft of this parser swept into the top-level
    group, failing with `CLAUDE.md lists tests/test_claude_md_structure.py but
    it does not exist`. The exact set equality below catches both."""
    documented, _ = parse_structure(_block(_TRUE_DOMAIN))

    assert documented[TOP_LEVEL] == {"cli.py", "transport.py", "builder.py", "presentation.py"}


# --- the README reader, checked the same way ---------------------------------


def _table(rows: str, trailing_prose: str = "") -> str:
    """A minimal Architecture section in the README's shape.

    The trailing prose is not decoration: the real section ends with sentences
    naming `tests/test_claude_md_structure.py` and `CLAUDE.md`, and a reader
    that swept those in would invent a `tests/` package. That is the same trap
    the CLAUDE.md parser hit, arriving by a different route.
    """
    return (
        "## Architecture\n\n"
        "All paths under `src/fpl_cli/`:\n\n"
        "| Module | |\n|---|---|\n"
        f"{rows}"
        "\n"
        f"{trailing_prose}"
        "\n## Development\n"
    )


_TRUE_ROWS = (
    "| `cli.py` | Typer commands. |\n"
    "| `api/models.py` | Pydantic models. |\n"
    "| `domain/rules.py` | Rules from the snapshot. |\n"
    "| `domain/squad.py` | Squad validation. |\n"
)

_SMALL_TREE: dict[str, set[str]] = {
    TOP_LEVEL: {"cli.py"},
    "api": {"models.py"},
    "domain": {"rules.py", "squad.py"},
}


def test_the_readme_reader_passes_on_a_table_that_matches() -> None:
    """The control, without which none of the mutations below is evidence."""
    assert (
        structure_drift(
            _table(_TRUE_ROWS), _SMALL_TREE, parser=parse_architecture, document="README.md"
        )
        == []
    )


def test_the_readme_reader_groups_by_path_not_by_heading() -> None:
    """`CLAUDE.md` groups under a package heading; the README qualifies each
    path instead. The two readers exist because of this difference, so it is
    worth asserting rather than assuming.

    Mutation: grouping everything under TOP_LEVEL fails on `api/models.py`.
    """
    documented, absent = parse_architecture(_table(_TRUE_ROWS))

    assert documented == _SMALL_TREE
    assert absent == set()


def test_the_readme_reader_ignores_the_description_column() -> None:
    """A description naming a module must not be read as a module. Real rows do
    this — `presentation.py`'s mentions FU-18, and `api/official.py`'s names
    three endpoints.

    Mutation: matching the whole row instead of the first cell invents
    `domain/chips.py` here and fails.
    """
    rows = _TRUE_ROWS + "| `storage/cache.py` | Superseded by `domain/chips.py` one day. |\n"
    documented, _ = parse_architecture(_table(rows))

    assert documented["storage"] == {"cache.py"}
    assert "chips.py" not in documented.get("domain", set())


def test_the_readme_reader_ignores_prose_after_the_table() -> None:
    """The trap that broke the first CLAUDE.md parser, in the second document.

    Mutation: reading every line rather than only table rows sweeps
    `tests/test_claude_md_structure.py` into a `tests/` group, which then reads
    as a package that exists nowhere.
    """
    prose = (
        "This table is checked by `tests/test_claude_md_structure.py`, which walks\n"
        "`src/fpl_cli/` and also reads `CLAUDE.md`. See `docs/plans/follow-ups.md`.\n"
    )
    documented, _ = parse_architecture(_table(_TRUE_ROWS, prose))

    assert documented == _SMALL_TREE
    assert "tests" not in documented


def test_the_readme_reader_ignores_the_header_and_separator_rows() -> None:
    """Both are table rows and neither names a module. They are skipped because
    nothing in them matches a `*.py` token, not by counting lines — a
    line-counting reader would break the moment a column was added.

    Mutation: dropping the `.py` requirement from `_MODULE` would pick up
    `Module` and `---`, and the exact equality above and here would fail.
    """
    documented, _ = parse_architecture(_table(_TRUE_ROWS))

    assert all(module.endswith(".py") for modules in documented.values() for module in modules)


def test_the_readme_reader_reports_drift_naming_the_readme() -> None:
    """The message must say which document, now that a module can be missing
    from two.

    Mutation: leaving `document` hardcoded to "CLAUDE.md" in `structure_drift`
    sends a reader to the wrong file, and fails here.
    """
    dropped = _TRUE_ROWS.replace("| `domain/squad.py` | Squad validation. |\n", "")

    drift = structure_drift(
        _table(dropped), _SMALL_TREE, parser=parse_architecture, document="README.md"
    )

    assert drift == ["README.md: `domain/`: squad.py exists but is not listed"]


def test_dropping_a_packages_last_row_reads_as_a_missing_package() -> None:
    """An asymmetry between the two documents, asserted rather than papered over.

    `CLAUDE.md` names a package in a heading, so a package survives its last
    module being deleted from the list and the drift reads "module missing". The
    README derives groups from the paths themselves, so removing the last
    `domain/` row removes the package from the document entirely, and the drift
    reads "package missing" instead.

    Both are true and both name the fault; the messages differ because the
    documents differ. Worth pinning, because someone comparing the two readers'
    output would otherwise read this as a bug in one of them.
    """
    without_domain = "".join(
        row + "\n" for row in _TRUE_ROWS.splitlines() if "domain/" not in row
    )

    drift = structure_drift(
        _table(without_domain), _SMALL_TREE, parser=parse_architecture, document="README.md"
    )

    assert drift == [
        "README.md: `domain/` exists in src/fpl_cli/ but nothing in it lists the package "
        "(contains: rules.py, squad.py)"
    ]


def test_one_checker_serves_both_documents() -> None:
    """`structure_drift` is shared; only the reader differs. If a second checker
    were ever written, this is the test that would look wrong first.

    The same fault in both documents must produce the same finding, differing
    only in the document named.
    """
    claude = structure_drift(
        _block(_TRUE_DOMAIN.replace(", optimizer.py", "")), _FAKE_TREE, document="CLAUDE.md"
    )
    readme_rows = _TRUE_ROWS.replace("| `domain/squad.py` | Squad validation. |\n", "")
    readme = structure_drift(
        _table(readme_rows), _SMALL_TREE, parser=parse_architecture, document="README.md"
    )

    assert claude == ["CLAUDE.md: `domain/`: optimizer.py exists but is not listed"]
    assert readme == ["README.md: `domain/`: squad.py exists but is not listed"]


def test_a_missing_architecture_section_is_an_error_not_an_empty_parse() -> None:
    """A reader that returns nothing when it finds nothing guards nothing.

    If the section were renamed, an empty parse would read as "the document
    lists no modules", which is drift the guard would report against every
    module in the tree — noise that buries the real cause. Failing on the
    heading names the actual problem.

    This mirrors `structure_section`'s assertion for `CLAUDE.md`, which was
    equally untested until the mutation run for this branch found the hole:
    every other mutation of that function was unreachable from the existing
    tests, because they all supply a well-formed document.

    Mutation: `if match is None: return ""` in either function stops this
    raising.
    """
    with pytest.raises(AssertionError, match="no `## Architecture` section"):
        parse_architecture("## Something Else\n\n| `cli.py` | x |\n\n## Next\n")

    with pytest.raises(AssertionError, match="no `## Structure` section"):
        parse_structure("## Something Else\n\n`api/` — official.py\n\n## Next\n")
