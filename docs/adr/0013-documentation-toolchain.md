# 13. Documentation toolchain

- Status: accepted
- Date: 2026-11-12

## Context

Version 2.0 needs a documentation site: guides, the migration guide, the ADRs and an API
reference generated from the docstrings. The repository already keeps its documents in
Markdown. The ecosystem around MkDocs, read on 2026-11-12:

- Material for MkDocs is in maintenance mode. Its 9.8 release notes say: "Material for MkDocs
  reaches end of life on May 5, 2027. Critical fixes and security updates continue until that
  date." Its team now builds Zensical.
- MkDocs 2.0 has no announced release date. It is incompatible with Material and drops
  plugins.
- mkdocstrings is in maintenance mode too. Zensical supports it (since 0.0.11), so the API
  reference engine is the same on either path.
- Zensical reads `mkdocs.yml` but is not yet at 1.0.

## Decision

- **MkDocs 1.6 with Material 9.8 and `mkdocstrings-python`**, in the `docs` dependency group,
  pinned `mkdocs>=1.6,<2` so a MkDocs 2 release cannot break the build. It is mature today,
  and `mkdocs build --strict` turns a broken link or an unresolved reference into a failed
  build.
- **Configuration stays inside what Zensical documents as compatible**: the Material theme,
  `admonition`, `pymdownx.superfences`, `pymdownx.snippets` and mkdocstrings. Moving to
  Zensical then changes the build command and the dependencies, not the pages.
- **Examples are code.** The pages include `docs/examples/*.py` through snippets with
  `check_paths: true`; those files are linted, type-checked and run by the unit tests, so a
  page cannot show code that no longer works.
- **The API reference documents the package-root names** and the `CapitalCom` namespaces. A
  test asserts a docstring on each of them and on their public methods and properties.
- **Hosting: GitHub Pages at `https://akinzou.github.io/CapitalCom/`.** A separate workflow
  deploys on every `v*` tag after the PyPI upload succeeded, or when started by hand. It is
  not deployed on every push to `master`, because the site would then describe code that is
  not on PyPI.
- `docs/superpowers/` (design notes and plans) is excluded from the site.

## Alternatives

- **Sphinx** was rejected: the Markdown guides and ADRs would have to be rewritten or run
  through a bridge, for no gain a reader sees.
- **Zensical now** was rejected while it is below 1.0; the site would depend on a tool still
  changing its configuration.
- **MkDocs 2** is not released and has no plugins, so it cannot generate the reference.

## Consequences

- **Follow-up before 2027-05-05:** move the build to Zensical, when Material stops receiving
  fixes. The pages and `mkdocs.yml` are expected to carry over unchanged.
- The `docs` CI job builds the site with `--strict` on every pull request.
- A public name without a docstring fails the test suite.
