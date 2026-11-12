"""How the documentation site is published and how it looks."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
PAGES_WORKFLOW = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
MKDOCS = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def test_the_site_is_published_on_every_push_to_master() -> None:
    trigger = re.search(r"^on:\n(.*?)^\S", PAGES_WORKFLOW, re.DOTALL | re.MULTILINE)
    assert trigger is not None
    assert re.search(r"^  push:\n    branches: \[master\]$", trigger.group(1), re.MULTILINE)


def test_the_site_opens_in_the_dark_scheme_with_a_switch_to_light() -> None:
    # Material shows the first palette entry until the reader picks another one.
    schemes = re.findall(r"^    - scheme: (\w+)$", MKDOCS, re.MULTILINE)
    assert schemes == ["slate", "default"]
