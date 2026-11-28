# SPDX-License-Identifier: BSD-3-Clause
"""Build the download site from one published edi release and edi's own release tools.

Run as ``python build_site.py --edi edi --assets assets --output site --pages pages
--previous current``: ``edi`` is edi checked out at the release tag, ``assets`` that release's
downloaded assets, ``site`` the tree for download.easydiffraction.org, ``pages`` the copy for
GitHub Pages and ``current`` the tree the download host serves now.

A release attaches its component repositories in full (``repository-stable-<platform>.tar.gz``),
and newer releases also as an index (``repoindex-stable-<platform>.tar.gz``): Updates.xml, the
meta.7z and .sha1 files, and the rules that send each archive to the release asset holding it
(redirects.py). The index is used whenever ``assets`` holds one. An index release keeps the
previous release's files from ``current``, for updates in progress. Pages cannot redirect, so its
copy of an index release has no repository/.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from redirects import RULE_FILE, archive_redirects, listed_archives, parse_rules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--edi', required=True, type=Path)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--pages', type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    edi = args.edi.resolve()
    sys.path[:0] = [str(edi / 'tools/release'), str(edi / 'website')]
    from distribution import manifest  # noqa: PLC0415 - edi's own tools, at the release tag
    from render_package_index import REPOSITORY, write_package_index  # noqa: PLC0415

    release = json.loads((args.assets / 'release.json').read_text(encoding='utf-8'))
    site = args.output
    shutil.rmtree(site, ignore_errors=True)
    site.mkdir(parents=True)
    redirected = write_repositories(args.assets, site, args.previous, release['version'])
    # From 26.17 apps read stable-v2.json, and stable.json is the checked feed for 2026.11.x apps,
    # which drop a whole feed over one YY.N version (edi ADR-0106). write_feeds refuses a feed they
    # would drop, so the build fails and the site in place stays. Older tags copy the history.
    if (edi / 'tools/release/legacy_feed.py').is_file():
        from legacy_feed import write_feeds  # noqa: PLC0415

        write_feeds(args.assets / 'release-history.json', site / 'releases')
    else:
        (site / 'releases').mkdir()
        shutil.copy2(args.assets / 'release-history.json', site / 'releases/stable.json')
    # The current wheels are served beside the index, older ones link their GitHub releases.
    pages = json.loads(
        subprocess.check_output(
            ['gh', 'api', '--paginate', '--slurp', f'repos/{REPOSITORY}/releases?per_page=100']
        )
    )
    write_package_index(site, pages)
    wheels = sorted(p.name for p in (site / 'pypi/simple/easydiffraction').glob('*.whl'))
    if not wheels or any(release['version'] not in name for name in wheels):
        raise SystemExit(f'The index does not serve the {release["version"]} wheels: {wheels}')
    trees = [site]
    if args.pages:
        # Without the archives Pages would list components it cannot serve, so it carries no
        # repository at all and the installers skip it for the download host.
        shutil.rmtree(args.pages, ignore_errors=True)
        skip = None if redirected is None else shutil.ignore_patterns('repository', '.htaccess')
        shutil.copytree(site, args.pages, ignore=skip, copy_function=os.link)
        trees.append(args.pages)
    for tree in trees:
        (tree / 'SHA256SUMS').write_text(manifest(tree), encoding='utf-8')
        (tree / '.nojekyll').write_text('')
        (tree / 'index.html').write_text(
            '<!doctype html>\n<html><body>\n'
            f'<p>EasyDiffraction {release["version"]} downloads: '
            '<a href="https://github.com/enhantica/edi/releases">GitHub Releases</a>, '
            '<a href="pypi/simple/">Python package index</a>.</p>\n'
            '</body></html>\n',
            encoding='utf-8',
        )
    redirects = '' if redirected is None else f', {redirected} archives on the release'
    print(f'site for {release["version"]}: {len(wheels)} wheels, 3 repositories{redirects}')


def write_repositories(
    assets: Path, site: Path, previous: Path | None, version: str
) -> int | None:
    """Write the component repositories; for an index, return how many archives redirect."""
    # Each archive holds repository/<platform>/ at the path the installers read. A release with
    # an index still attaches the full repositories, for a rollback (publish.yml's format input).
    full = sorted(assets.glob('repository-stable-*.tar.gz'))
    index = sorted(assets.glob('repoindex-stable-*.tar.gz'))
    archives = index or full
    if len(archives) != 3:
        raise SystemExit(f'Expected three stable component repositories, found {len(archives)}')
    for archive in archives:
        with tarfile.open(archive) as opened:
            check_members(opened.getmembers(), archive.name, index=bool(index))
            opened.extractall(site, filter='data')
    if not index:
        # An index under the full name would leave every archive missing on the host.
        missing = [path for path in listed_archives(site) if not (site / path).is_file()]
        if missing:
            raise SystemExit(f'The repositories lack archives they list: {", ".join(missing[:3])}')
        return None
    install_redirects(site)
    if previous:
        keep_previous(previous, site, version)
    return len(archive_redirects(site))


# The parts of a component repository's paths, as edi's repogen writes them.
PLATFORM = r'[a-z0-9]+(?:[-_][a-z0-9]+)*'
COMPONENT = r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*'
VERSION = r'[0-9]+(?:\.[0-9]+)+'
ARCHIVE = r'[A-Za-z][A-Za-z0-9._-]*\.7z'


def check_members(members: list[tarfile.TarInfo], archive: str, *, index: bool) -> None:
    """Refuse a repository archive holding anything but its platform's repository files.

    The host serves every file in it, so anything else, another .htaccess above all, would go out
    unchecked. An index holds no component archives and must hold its redirect rules.
    """
    platform = archive.removesuffix('.tar.gz').split('-stable-', 1)[-1]
    if not re.fullmatch(PLATFORM, platform):
        raise SystemExit(f'{archive}: not a platform repository')
    where = f'repository/{platform}'
    # An index serves only meta.7z itself; the other archives stay on the release.
    seven = r'meta\.7z' if index else ARCHIVE
    folder = re.compile(rf'repository(?:/{platform}(?:/{COMPONENT})?)?')
    file = re.compile(
        rf'{where}/(?:Updates\.xml|{COMPONENT}/{VERSION}(?:{seven}|{ARCHIVE}\.sha1))'
    )
    allowed = {f'{where}/{RULE_FILE}'} if index else set()
    stray = [
        member.name
        for member in members
        if not (member.isdir() and folder.fullmatch(member.name.rstrip('/')))
        and not (member.isfile() and (file.fullmatch(member.name) or member.name in allowed))
    ]
    if stray:
        raise SystemExit(f'{archive} holds what the site must not serve: {", ".join(stray[:3])}')
    if index and not any(member.name in allowed for member in members):
        raise SystemExit(f'{archive} has no {RULE_FILE}')


def install_redirects(site: Path) -> None:
    """Move each platform's redirect rules into the site's .htaccess, which only the host reads."""
    parts = ['RewriteEngine On\n']
    for rules in sorted((site / 'repository').rglob(RULE_FILE)):
        where = rules.relative_to(site).as_posix()
        text = rules.read_text(encoding='utf-8')
        parse_rules(text, where)
        parts.append(f'# {where}\n{text.strip()}\n')
        rules.unlink()
    (site / '.htaccess').write_text(''.join(parts), encoding='utf-8')


def keep_previous(current: Path, site: Path, version: str) -> None:
    """Keep the previous release's files from the tree the host serves now.

    An update that read the previous Updates.xml still asks for its .sha1 and meta.7z files. Its
    archives redirect like any other, except after a full release: those are not on the release,
    so the ones the host holds are kept too. They are in edi-sites already. Only the newest older
    version is kept, so the files of one release ride along.
    """
    from versions import PATTERN, version_key  # noqa: PLC0415

    previous = re.compile(rf'({PATTERN})[A-Za-z][A-Za-z0-9._-]*\.(?:7z|sha1)')
    found: dict[str, list[Path]] = {}
    for path in sorted((current / 'repository').rglob('*')):
        if path.is_file() and (match := previous.fullmatch(path.name)):
            found.setdefault(match[1], []).append(path)
    older = [v for v in found if version_key(v) < version_key(version)]
    for path in found[max(older, key=version_key)] if older else []:
        kept = site / path.relative_to(current)
        if not kept.exists():
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, kept)


if __name__ == '__main__':
    main()
