"""How the documentation site is published and how it looks."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
PAGES_WORKFLOW = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
MKDOCS = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
PUBLISH_WORKFLOW = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
SITE_URL = re.search(r"^site_url: (\S+)$", MKDOCS, re.MULTILINE)


def test_the_site_is_published_on_every_push_to_master() -> None:
    trigger = re.search(r"^on:\n(.*?)^\S", PAGES_WORKFLOW, re.DOTALL | re.MULTILINE)
    assert trigger is not None
    assert re.search(r"^  push:\n    branches: \[master\]$", trigger.group(1), re.MULTILINE)


def test_the_site_opens_in_the_dark_scheme_with_a_switch_to_light() -> None:
    # Material shows the first palette entry until the reader picks another one.
    schemes = re.findall(r"^    - scheme: (\w+)$", MKDOCS, re.MULTILINE)
    assert schemes == ["slate", "default"]


def test_only_master_publishes_the_site() -> None:
    # A release tag may point behind master; deploying it would roll the site back.
    assert "pages.yml" not in PUBLISH_WORKFLOW
    assert "workflow_call" not in PAGES_WORKFLOW
    assert "    if: github.ref == 'refs/heads/master'\n" in PAGES_WORKFLOW


def test_a_failed_measurement_keeps_the_published_coverage() -> None:
    # Each deploy replaces the whole site, so without a fresh number the old file is carried
    # over; a missing file would turn the README badge into "resource not found".
    assert SITE_URL is not None
    assert f"{SITE_URL.group(1)}badges/coverage.json" in PAGES_WORKFLOW
