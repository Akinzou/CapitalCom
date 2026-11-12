"""What the installed package declares to the tools that consume it."""

from importlib.resources import files


def test_the_package_declares_its_inline_types() -> None:
    # PEP 561: without the marker a user's type checker ignores every annotation and reports
    # the import as untyped. CI installs the wheel (not the source tree) before running this,
    # so a marker left out of the wheel fails here too.
    assert files("capitalcom").joinpath("py.typed").is_file()
