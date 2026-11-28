# edi-download

Downloads for [EasyDiffraction](https://github.com/enhantica/edi): the desktop installers' online component repositories,
the Python package index and the release feeds, served at https://enhantica.github.io/edi-download/. The release files
themselves are on [GitHub Releases](https://github.com/enhantica/edi/releases).

The `Publish downloads` workflow builds the site from a published edi release with edi's own release tools and deploys
it to GitHub Pages. It runs daily for the latest release, or by hand for a given tag:

    gh workflow run publish.yml -R enhantica/edi-download -f tag=v2026.11.0

The same files go to the edi-sites branch that download.easydiffraction.org pulls. A release attaches its component
repositories in full (`repository-stable-<platform>.tar.gz`), and newer releases also as an index
(`repoindex-stable-<platform>.tar.gz`): Updates.xml, the meta.7z and .sha1 files, and rules made at the release tag that
send each archive to the release asset holding it. The index is used whenever the release has one. For an index the
download host serves those files, keeps the previous release's files for updates in progress, and redirects the
archives. The workflow checks every redirect before the push and reads the host back after it; if the host does not
serve the new site, it puts the previous one back. GitHub Pages cannot redirect, so it then carries no component
repositories.

To roll back to full repositories, run the workflow with `-f format=full`. GitHub refuses a file over 100 MiB pushed to
edi-sites, so that works only for a release whose archives are all smaller.

The feeds are `releases/stable-v2.json`, the full history that apps from 26.17 read, and `releases/stable.json` for
2026.11.x apps: the old releases and the newest `YY.N` release under an alias they accept, written and checked by
edi's `tools/release/legacy_feed.py` at the release tag (edi ADR-0106). A tag without that file gets the history as
`stable.json` only.
