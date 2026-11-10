# SPDX-License-Identifier: BSD-3-Clause
"""Build the download site from one published edi release and edi's own release tools.

Run as ``python build_site.py --edi edi --assets assets --output site``: ``edi`` is edi checked
out at the release tag and ``assets`` that release's downloaded assets.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--edi', required=True, type=Path)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    edi = args.edi.resolve()
    sys.path[:0] = [str(edi / 'tools/release'), str(edi / 'website')]
    from distribution import manifest  # noqa: PLC0415 - edi's own tools, at the release tag
    from render_package_index import REPOSITORY, write_package_index  # noqa: PLC0415

    release = json.loads((args.assets / 'release.json').read_text(encoding='utf-8'))
    site = args.output
    shutil.rmtree(site, ignore_errors=True)
    site.mkdir(parents=True)
    # Each archive holds repository/<platform>/ at the path the installers read.
    archives = sorted(args.assets.glob('repository-stable-*.tar.gz'))
    if len(archives) != 3:
        raise SystemExit(f'Expected three stable component repositories, found {len(archives)}')
    for archive in archives:
        with tarfile.open(archive) as opened:
            opened.extractall(site, filter='data')
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
    (site / 'SHA256SUMS').write_text(manifest(site), encoding='utf-8')
    (site / '.nojekyll').write_text('')
    (site / 'index.html').write_text(
        '<!doctype html>\n<html><body>\n'
        f'<p>EasyDiffraction {release["version"]} downloads: '
        '<a href="https://github.com/enhantica/edi/releases">GitHub Releases</a>, '
        '<a href="pypi/simple/">Python package index</a>.</p>\n'
        '</body></html>\n',
        encoding='utf-8',
    )
    print(f'site for {release["version"]}: {len(wheels)} wheels, {len(archives)} repositories')


if __name__ == '__main__':
    main()
