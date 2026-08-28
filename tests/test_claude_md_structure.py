"""`CLAUDE.md`'s Structure block must agree with the tree (FU-19).

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

`__init__.py` is excluded throughout. The block does not list any, they carry no
implementation in this repo, and listing four empty files would be noise that
made the block harder to keep true — the opposite of the point.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
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


def structure_drift(text: str, actual: dict[str, set[str]] | None = None) -> list[str]:
    """Every disagreement between the block and the tree, named.

    Returned as a list rather than raised on the first one so a single run
    reports everything that needs changing — the block is edited by hand, and
    being sent back three times for three modules is how it stops being edited.

    `actual` is injectable so the self-checks below can describe a fixed tree.
    They used to read the real one, which meant adding any module to
    `src/fpl_cli/` failed six of them alongside the guard — a check that noisy
    is a check someone deletes, which is the failure this whole entry is about.
    Only `test_claude_md_structure_matches_the_tree` touches the filesystem.
    """
    documented, absent = parse_structure(text)
    actual = tree_structure() if actual is None else actual
    drift: list[str] = []

    for group in sorted(set(documented) | set(actual)):
        listed = documented.get(group)
        present = actual.get(group)
        if present is None:
            drift.append(f"`{group}/` is listed in CLAUDE.md but is not a package in src/fpl_cli/")
            continue
        if listed is None:
            drift.append(
                f"`{group}/` exists in src/fpl_cli/ but no group in CLAUDE.md lists it "
                f"(contains: {', '.join(sorted(present))})"
            )
            continue
        where = TOP_LEVEL if group == TOP_LEVEL else f"`{group}/`"
        for module in sorted(present - listed):
            drift.append(f"{where}: {module} exists but CLAUDE.md does not list it")
        for module in sorted(listed - present):
            drift.append(f"{where}: CLAUDE.md lists {module} but it does not exist")

    for entry in sorted(absent):
        # Resolved against the same mapping as everything else rather than by
        # stat-ing the path, so one source of truth answers "does this exist"
        # and the self-checks can exercise this branch too.
        group, _, module = entry.rpartition("/")
        searched = [actual.get(group, set())] if group else list(actual.values())
        if any(module in members for members in searched):
            drift.append(
                f'"Not yet written" names {entry}, which exists — remove it from that line'
            )

    return drift


def test_claude_md_structure_matches_the_tree() -> None:
    """The guard. Two regressions by the same mechanism is a missing check, not
    a third correction to make by hand."""
    drift = structure_drift(CLAUDE_MD.read_text(encoding="utf-8"))

    assert not drift, "CLAUDE.md's Structure block disagrees with src/fpl_cli/:\n  " + "\n  ".join(
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

    assert drift == ["`domain/`: optimizer.py exists but CLAUDE.md does not list it"]


def test_the_guard_catches_a_not_yet_written_line_naming_a_module_that_exists() -> None:
    """The other half of the same regression, and the half that misleads rather
    than merely omits — the block asserted `optimizer.py` was absent while it
    was 960 lines."""
    drift = structure_drift(_block(_TRUE_DOMAIN, "Not yet written: domain/optimizer.py.\n"), _FAKE_TREE)

    assert drift == [
        '"Not yet written" names domain/optimizer.py, which exists — remove it from that line'
    ]


def test_the_guard_catches_a_module_listed_that_does_not_exist() -> None:
    """The opposite drift: a module is deleted or renamed and the block keeps
    naming it. Untested, this direction would go unnoticed — the two regressions
    so far were both omissions."""
    invented = _TRUE_DOMAIN + ", chips.py"

    drift = structure_drift(_block(invented), _FAKE_TREE)

    assert drift == ["`domain/`: CLAUDE.md lists chips.py but it does not exist"]


def test_the_guard_catches_a_whole_package_the_block_never_mentions() -> None:
    """A new package is the case a per-module diff would miss entirely, because
    there is no group to compare its contents against."""
    block = _block(_TRUE_DOMAIN).replace("`storage/` — cache.py, capture.py\n", "")

    drift = structure_drift(block, _FAKE_TREE)

    assert drift == [
        "`storage/` exists in src/fpl_cli/ but no group in CLAUDE.md lists it "
        "(contains: cache.py, capture.py)"
    ]


def test_every_drift_is_reported_not_just_the_first() -> None:
    """Three faults, three lines. The block is edited by hand; being sent back
    once per module is how it stops being edited at all."""
    block = _block(_TRUE_DOMAIN.replace(", optimizer.py", "") + ", chips.py")

    drift = structure_drift(block.replace("`storage/` — cache.py, capture.py\n", ""), _FAKE_TREE)

    assert sorted(drift) == sorted(
        [
            "`domain/`: optimizer.py exists but CLAUDE.md does not list it",
            "`domain/`: CLAUDE.md lists chips.py but it does not exist",
            "`storage/` exists in src/fpl_cli/ but no group in CLAUDE.md lists it "
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
