"""Smoke tests pinning the 1.0.4 import surface that existing users rely on."""


def test_root_import_exposes_legacy_client() -> None:
    from capitalcom import CapitalClient

    assert CapitalClient.__module__ == "capitalcom.client"


def test_legacy_module_names_importable() -> None:
    from capitalcom.client import (  # noqa: F401
        BLUE,
        GREEN,
        RED,
        RESET,
        CapitalClient,
        colored_log,
    )


def test_lot_to_size_unchanged() -> None:
    from capitalcom.client import CapitalClient

    # __new__ skips the constructor, which logs in eagerly over the network.
    client = CapitalClient.__new__(CapitalClient)
    assert client.lot_to_size(2, 100000) == 200000
    assert client.pips_to_profit_distance(15, 4) == 15 * 10**-4
    assert client.pips_to_profit_distance(0, 4) is None


def test_installed_version_matches_pyproject() -> None:
    # Compared with pyproject.toml rather than a literal, so a release bump cannot leave
    # this test behind, and a stale editable install is still caught.
    import tomllib
    from importlib.metadata import version
    from pathlib import Path

    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert version("capitalcom") == declared
