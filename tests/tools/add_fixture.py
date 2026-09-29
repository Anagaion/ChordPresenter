#!/usr/bin/env python3
"""
Save a song page as a local URL-mode test fixture.

    python3 tests/tools/add_fixture.py URL [URL ...]
    python3 tests/tools/add_fixture.py URL --html saved_page.html

Fetches the page once (or uses --html) and stores it under
tests/fixtures/local/pages/<site>/<slug>.html, recording the URL in
tests/fixtures/local/manifest.json. After that the tests never go online.

Then record what the app currently produces for it:

    UPDATE_SNAPSHOTS=1 python3 -m unittest discover tests

tests/fixtures/local/ is git-ignored: saved pages contain copyrighted lyrics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import ew_fetch  # noqa: E402

LOCAL = os.path.join(ROOT, 'tests', 'fixtures', 'local')
MANIFEST = os.path.join(LOCAL, 'manifest.json')


def slug_for(url: str) -> str:
    path = urlparse(url).path.strip('/')
    slug = re.sub(r'[^a-z0-9]+', '-', path.lower()).strip('-')
    return slug[-80:] or 'page'


def load_manifest() -> dict:
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict) -> None:
    os.makedirs(LOCAL, exist_ok=True)
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(manifest.items())), f, indent=2, ensure_ascii=False)
        f.write('\n')


def add(url: str, html: str | None = None) -> str:
    site = ew_fetch.detect_site(url)
    if html is None:
        html = ew_fetch.fetch_html(url)
    fid = f'{site}/{slug_for(url)}'
    path = os.path.join(LOCAL, 'pages', fid + '.html')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    manifest = load_manifest()
    manifest[fid] = {'url': url, 'site': site}
    save_manifest(manifest)
    return fid


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('urls', nargs='+')
    ap.add_argument('--html', help='use this saved HTML file instead of fetching (one URL only)')
    args = ap.parse_args()
    if args.html and len(args.urls) != 1:
        ap.error('--html takes exactly one URL')
    for url in args.urls:
        try:
            html = None
            if args.html:
                with open(args.html, encoding='utf-8') as f:
                    html = f.read()
            print(f'added  {add(url, html)}')
        except Exception as e:
            print(f'FAILED {url}: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
