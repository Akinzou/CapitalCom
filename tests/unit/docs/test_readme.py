"""The README's contents list and coverage badge point at things that exist."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parents[3]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PAGES_WORKFLOW = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
SITE_URL = re.search(
    r"^site_url: (\S+)$", (ROOT / "mkdocs.yml").read_text(encoding="utf-8"), re.MULTILINE
)
BADGE_FILE = "badges/coverage.json"


def github_anchor(heading: str) -> str:
    # GitHub's slug: lower case, punctuation dropped, each space a hyphen.
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def outside_code(text: str) -> str:
    # A "# comment" inside a code block is not a heading.
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def headings(level: str) -> list[str]:
    return re.findall(rf"^{level} (.+)$", outside_code(README), re.MULTILINE)


def contents_links() -> list[str]:
    section = re.search(r"^## Contents\n(.*?)^## ", README, re.DOTALL | re.MULTILINE)
    assert section is not None, "README has no Contents section"
    return re.findall(r"\]\(#([^)]+)\)", section.group(1))


def test_every_in_page_link_reaches_a_heading() -> None:
    anchors = {github_anchor(h) for h in headings("##") + headings("###")}
    assert set(re.findall(r"\]\(#([^)]+)\)", outside_code(README))) <= anchors


def test_every_section_is_in_the_contents() -> None:
    sections = {github_anchor(h) for h in headings("##") + headings("###")} - {"contents"}
    assert sections <= set(contents_links())


def test_coverage_badge_reads_the_file_the_site_publishes() -> None:
    # The number comes from the test run in the site build; a badge pointing anywhere else
    # would show "resource not found" on the project page instead of the coverage.
    assert SITE_URL is not None
    badge = re.search(
        r"\[!\[Code Coverage\]\((https://img\.shields\.io/badge/dynamic/json\?[^)\s]+)\)\]"
        r"\(([^)]+)\)",
        README,
    )
    assert badge is not None, "README has no linked dynamic coverage badge"
    # The link leads to the runs that measured the number, so a reader can check it.
    assert badge.group(2).endswith("/actions/workflows/pages.yml")
    query = parse_qs(urlparse(badge.group(1)).query)
    assert query["url"] == [SITE_URL.group(1) + BADGE_FILE]
    assert query["query"] == ["$.percent_covered_display"]
    assert query["label"] == ["Code Coverage"]
    assert f"site/{BADGE_FILE}" in PAGES_WORKFLOW


def test_the_title_carries_the_coverage_badge_alone() -> None:
    # The other badges sit on the lines below the title.
    title = README.splitlines()[0]
    assert title.startswith("# CapitalCom [![Code Coverage](")
    assert title.count("[![") == 1


def test_docs_badge_shows_the_site_build_from_master_and_links_the_site() -> None:
    # The site is published on every push to master, so the badge follows that branch.
    assert SITE_URL is not None
    badge = re.search(
        r"\[!\[Docs\]\((https://img\.shields\.io/github/actions/workflow/status/[^)\s]+)\)\]"
        r"\(([^)]+)\)",
        README,
    )
    assert badge is not None, "README has no linked docs badge"
    url = urlparse(badge.group(1))
    assert url.path.endswith("/Akinzou/CapitalCom/pages.yml")
    assert parse_qs(url.query)["branch"] == ["master"]
    assert badge.group(2) == SITE_URL.group(1)


def test_licence_badge_leads_to_the_section_with_the_additional_permission() -> None:
    # LICENSE alone reads "noncommercial"; the section also names the permission for
    # individuals trading their own accounts. Absolute, so it works on PyPI too.
    badge = re.search(r"\[!\[License\]\([^)]+\)\]\(([^)]+)\)", README)
    assert badge is not None
    assert badge.group(1) == "https://github.com/Akinzou/CapitalCom#license"
