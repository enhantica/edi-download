# SPDX-License-Identifier: BSD-3-Clause
"""Check the download host's redirects of component archives to edi's release assets.

An index release attaches ``repoindex-stable-<platform>.tar.gz`` instead of the full repositories:
each platform's Updates.xml, meta.7z and .sha1 files, and in ``repository/<platform>/`` a
``redirect.htaccess`` that sends its archives to the release holding them. build_site.py joins
those rules into the site's .htaccess. This checks what they do, before and after the push:

    python redirects.py check site       # every archive reaches a release asset
    python redirects.py readback site --host https://download.easydiffraction.org/
"""

import argparse
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET  # noqa: S405 - edi's own Updates.xml, which promote checks
from pathlib import Path
from typing import override

RULE_FILE = 'redirect.htaccess'
RELEASES = 'https://github.com/enhantica/edi/releases/download/'
ASSET = re.compile(re.escape(RELEASES) + r'[^/]+/[A-Za-z0-9._-]+')
NOT_A_FILE = ['RewriteCond', '%{REQUEST_FILENAME}', '!-f']
FLAGS = ('[R=302,L]', '[L,R=302]')
HEADERS = {'User-Agent': 'edi-download'}

Rules = list[tuple[re.Pattern, str]]


def parse_rules(text: str, where: str) -> Rules:
    """The rules in `text`, each a pattern and the URL it sends a match to.

    Only what the checks here can follow is accepted: ``RewriteEngine On``, comments, and pairs of
    ``RewriteCond %{REQUEST_FILENAME} !-f`` and ``RewriteRule ^repository/... <release URL>
    [R=302,L]``. The condition keeps every file on the host served as it is, the .sha1 files above
    all: IFW fetches an archive from wherever its .sha1 came from.
    """
    rules, condition = [], False
    for number, line in enumerate(text.splitlines(), 1):
        words = line.split()
        if not words or words[0].startswith('#') or words == ['RewriteEngine', 'On']:
            continue
        if words == NOT_A_FILE and not condition:
            condition = True
            continue
        if condition and len(words) == 4 and words[0] == 'RewriteRule':
            rule = _rule(*words[1:])
            if rule:
                rules.append(rule)
                condition = False
                continue
        raise SystemExit(f'{where}:{number}: not a rule the download site takes: {line.strip()}')
    if condition or not rules:
        raise SystemExit(f'{where}: expected pairs of RewriteCond and RewriteRule')
    return rules


def _rule(pattern: str, url: str, flags: str) -> tuple[re.Pattern, str] | None:
    """A redirect of paths under repository/ to edi's releases, or None."""
    if not pattern.startswith('^repository/') or not url.startswith(RELEASES):
        return None
    if flags not in FLAGS or re.search(r'[%\\{}]', url):
        return None
    try:
        compiled = re.compile(pattern)
    except re.error:
        return None
    groups = [int(n) for n in re.findall(r'\$([0-9])', url)]
    return (compiled, url) if max(groups, default=0) <= compiled.groups else None


def target(rules: Rules, site: Path, path: str) -> str | None:
    """Where the host sends `path`, as LiteSpeed applies the rules; None when it serves it."""
    if (site / path).exists():
        return None
    for pattern, url in rules:
        if match := pattern.search(path):
            return re.sub(r'\$([0-9])', lambda m: match[int(m[1])] or '', url)
    return None


def listed_archives(site: Path) -> list[str]:
    """Each archive the site's Updates.xml files list, by its path in the site."""
    paths = []
    for updates in sorted((site / 'repository').rglob('Updates.xml')):
        folder = updates.parent.relative_to(site).as_posix()
        for package in ET.parse(updates).getroot().iter('PackageUpdate'):  # noqa: S314
            name, version = package.findtext('Name'), package.findtext('Version')
            archives = (package.findtext('DownloadableArchives') or '').split(',')
            paths += [f'{folder}/{name}/{version}{a.strip()}' for a in archives if a.strip()]
    return paths


def archive_redirects(site: Path) -> dict[str, str]:
    """Each listed archive, by path, and the URL the host sends it to.

    Refused when an archive has no .sha1 on the host, or no rule sends it to a release asset, or a
    rule would send its .sha1 away.
    """
    rules = parse_rules((site / '.htaccess').read_text(encoding='utf-8'), '.htaccess')
    redirects, problems = {}, []
    for path in listed_archives(site):
        url = target(rules, site, path)
        if not (site / f'{path}.sha1').is_file():
            problems.append(f'{path}: no .sha1 on the host')
        elif any(pattern.search(f'{path}.sha1') for pattern, _ in rules):
            problems.append(f'{path}.sha1: a rule matches it')
        elif url is None or not ASSET.fullmatch(url):
            problems.append(f'{path}: not sent to a release asset ({url})')
        else:
            redirects[path] = url
    if problems or not redirects:
        raise SystemExit('The redirects do not cover the archives:\n' + '\n'.join(problems))
    return redirects


def head(url: str) -> int | str:
    """The status of an anonymous HEAD of `url` after its redirects; network errors retried."""
    request = urllib.request.Request(url, method='HEAD', headers=HEADERS)  # noqa: S310
    result: int | str = ''
    for delay in (10, 30, 0):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                return response.status
        except urllib.error.HTTPError as error:
            if error.code < 500:
                return error.code
            result = error.code
        except OSError as error:
            result = str(error)
        time.sleep(delay)
    return result


def check(site: Path) -> None:
    """Refuse unless every redirected archive is on its release, asked anonymously as IFW asks."""
    redirects = archive_redirects(site)
    missing = [
        f'{path} -> {url}: {status}'
        for path, url in sorted(redirects.items())
        if (status := head(url)) != 200
    ]
    if missing:
        raise SystemExit('Archives the host would send nowhere:\n' + '\n'.join(missing))
    print(f'{len(redirects)} redirected archives are on their releases')


class _Stay(urllib.request.HTTPRedirectHandler):
    """Report a redirect instead of following it."""

    @override
    def redirect_request(self, *_args: object) -> None:
        return None


def answer(url: str, method: str) -> tuple[int | str, str, bytes]:
    """Status, Location and body of `url`, its redirect not followed."""
    request = urllib.request.Request(url, method=method, headers=HEADERS)  # noqa: S310
    try:
        with urllib.request.build_opener(_Stay).open(request, timeout=30) as response:
            return response.status, response.headers.get('Location', ''), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get('Location', ''), b''
    except OSError as error:
        return str(error), '', b''


def readback(site: Path, host: str, wait: float = 600, every: float = 15) -> None:
    """Wait for `host` to serve the pushed site: one archive's 302 and its .sha1.

    The host pulls the branch through a webhook, so it gets `wait` seconds. The .sha1 shows the
    pull happened; the archive shows LiteSpeed applies the rules as the check above read them.
    """
    path, url = min(archive_redirects(site).items())
    expected = (site / f'{path}.sha1').read_bytes()
    host = host.rstrip('/') + '/'
    deadline = time.monotonic() + wait
    while True:
        status, location, _ = answer(host + path, 'HEAD')
        sha1_status, _, sha1 = answer(f'{host}{path}.sha1', 'GET')
        problems = []
        if (status, location) != (302, url):
            problems.append(f'{path} gave {status} {location}, not a 302 to {url}')
        if (sha1_status, sha1) != (200, expected):
            problems.append(f'its .sha1 gave {sha1_status}, not 200 with the release hash')
        if not problems:
            print(f'{host} sends {path} to {url} and serves its .sha1')
            return
        if time.monotonic() > deadline:
            raise SystemExit(
                f'{host} does not serve this site after {wait / 60:.0f} min: '
                + '; '.join(problems)
                + '. Check that the host pulled deploy-download and applies the .htaccess rules.'
            )
        time.sleep(every)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=['check', 'readback'])
    parser.add_argument('site', type=Path)
    parser.add_argument('--host', default='https://download.easydiffraction.org/')
    args = parser.parse_args()
    if args.action == 'check':
        check(args.site)
    else:
        readback(args.site, args.host)


if __name__ == '__main__':
    main()
