# edi-download

Downloads for [EasyDiffraction](https://github.com/enhantica/edi): the desktop installers' online component repositories,
the Python package index and the release feeds, served at https://enhantica.github.io/edi-download/. The release files
themselves are on [GitHub Releases](https://github.com/enhantica/edi/releases).

The `Publish downloads` workflow builds the site from a published edi release with edi's own release tools and deploys
it to GitHub Pages. It runs daily for the latest release, or by hand for a given tag:

    gh workflow run publish.yml -R enhantica/edi-download -f tag=v2026.11.0

The feeds are `releases/stable-v2.json`, the full history that apps from 26.17 read, and `releases/stable.json` for
2026.11.x apps: the old releases and the newest `YY.N` release under an alias they accept, written and checked by
edi's `tools/release/legacy_feed.py` at the release tag (edi ADR-0106). A tag without that file gets the history as
`stable.json` only.
