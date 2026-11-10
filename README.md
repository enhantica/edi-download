# edi-download

Downloads for [EasyDiffraction](https://github.com/enhantica/edi): the desktop installers' online component repositories,
the Python package index and the release feed, served at https://enhantica.github.io/edi-download/. The release files
themselves are on [GitHub Releases](https://github.com/enhantica/edi/releases).

The `Publish downloads` workflow builds the site from a published edi release with edi's own release tools and deploys
it to GitHub Pages. It runs daily for the latest release, or by hand for a given tag:

    gh workflow run publish.yml -R enhantica/edi-download -f tag=v2026.11.0
