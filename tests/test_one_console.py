"""FU-12: every line of CLI output goes through `presentation`'s consoles.

`cli.py` used to shadow the builtin with `from rich import print` and mix it with
`console.print`, sometimes within one command, so width detection, capture and
colour handling differed line by line. Checked on the source rather than on
output, because the two channels print identical text in a test terminal.
"""

from __future__ import annotations

import ast
from pathlib import Path

import fpl_cli.cli as cli


def test_cli_makes_no_bare_print_calls() -> None:
    """Mutation: adding back any bare `print(...)` call in cli.py."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    bare = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
    ]
    assert not bare, f"bare print() at cli.py lines {bare}; use console.print or error_console.print"


def test_cli_does_not_shadow_the_builtin_print() -> None:
    """Mutation: restoring `from rich import print`."""
    assert "print" not in vars(cli)
