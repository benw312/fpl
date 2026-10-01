"""FU-75 §5: the points criterion's harness is frozen until the GW11-13 leg is decided.

The measurement code is part of the criterion. A change to it between
registration and decision makes the two legs measure different things, and the
criterion becomes unsatisfiable in principle (FU-60 §7's argument, applied to
the instrument rather than the model). If this fails, do not update the hash:
revert the change, or wait until FU-75 is decided.

Mutation it must fail against: any edit to either file (demonstrated by
appending a comment).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"

FROZEN = {
    "points_criterion.py": "7521328b78464aec4872e22fb5aab4558805cf93e76400db4f2449f0fa96660e",
    "fu72_plan_oracle.py": "a6725370a0c563b6b8b864544965f8ced66212f3b842458f004e120b5efe10d4",
}


def test_the_fu75_harness_is_unchanged_since_registration() -> None:
    for name, expected in FROZEN.items():
        actual = hashlib.sha256((TOOLS / name).read_bytes()).hexdigest()
        assert actual == expected, f"tools/{name} changed after FU-75 froze it (§5)"
