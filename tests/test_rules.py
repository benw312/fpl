from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.domain.rules import validate_squad


def test_valid_squad_passes(bootstrap_snapshot: BootstrapSnapshot) -> None:
    result = validate_squad(list(range(1, 16)), bootstrap_snapshot)
    assert result.valid


def test_budget_failure_is_actionable(bootstrap_snapshot: BootstrapSnapshot) -> None:
    bootstrap_snapshot.elements[0].now_cost = 1001
    result = validate_squad(list(range(1, 16)), bootstrap_snapshot)
    assert any("budget" in error.lower() for error in result.errors)


def test_duplicate_and_size_failures(bootstrap_snapshot: BootstrapSnapshot) -> None:
    result = validate_squad([1] * 15, bootstrap_snapshot)
    assert any("duplicate" in error.lower() for error in result.errors)
    assert any("GKP" in error for error in result.errors)
