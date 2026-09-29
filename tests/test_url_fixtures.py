"""
URL-mode tests: every saved song page goes through the same three stages the
app runs when someone pastes a link into the URL tab, and the result is
compared with the recorded snapshot for that page.

  1. site parser     scripts/ew_fetch.py parse_page()      page → title/key/capo/chart
  2. app key logic   src/music.ts + src/chart.ts (via node) chart → concert pitch, headers
  3. .pro builder    scripts/md_to_pro.py process_file()   chart → .pro, read back with parse_pro

Run:                      python3 -m unittest discover tests
Record / accept changes:  UPDATE_SNAPSHOTS=1 python3 -m unittest discover tests
Add a page:               python3 tests/tools/add_fixture.py URL

Pages and snapshots live in tests/fixtures/local/ (git-ignored — they contain
copyrighted lyrics). With no local fixtures the tests are skipped.
Snapshots are plain JSON so a future Rust port can be checked against them.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import ew_fetch     # noqa: E402
import md_to_pro    # noqa: E402
import parse_pro    # noqa: E402

LOCAL = os.path.join(ROOT, 'tests', 'fixtures', 'local')
MANIFEST = os.path.join(LOCAL, 'manifest.json')
UPDATE = os.environ.get('UPDATE_SNAPSHOTS') == '1'


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST):
        return {}
    with open(MANIFEST, encoding='utf-8') as f:
        return json.load(f)


def ui_stage(pages: list[dict]) -> list[dict]:
    """Run stage 2 (the app's TypeScript key logic) for many pages in one node call."""
    stdin = ''.join(json.dumps({'key': p.get('key', ''), 'capo': p.get('capo'),
                                'chart_text': p.get('chart_text', '')}) + '\n' for p in pages)
    out = subprocess.run(['node', '--no-warnings', os.path.join(ROOT, 'tests', 'ui_stage.ts')],
                         input=stdin, capture_output=True, text=True, check=True).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def build_pro(title: str, artist: str, chart: str, source_key: str, capo: int = 0,
              lyrics_only: bool = False) -> dict:
    """Stage 3: exactly what generate_from_url does, then read the .pro back."""
    with tempfile.TemporaryDirectory() as out_dir:
        md_path = os.path.join(out_dir, 'chart.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(ew_fetch.convert_chart_to_md(chart, title, artist))
        with contextlib.redirect_stdout(io.StringIO()):
            md_to_pro.process_file(md_path, output_dir=out_dir, lyrics_only=lyrics_only,
                                   source_key=source_key or None, capo=capo)
        pros = [n for n in os.listdir(out_dir) if n.endswith('.pro')]
        assert len(pros) == 1, pros
        parsed = parse_pro.parse_pro_file(os.path.join(out_dir, pros[0]))
    return {
        'file_name': pros[0],
        'slides': [{'group': s['group'], 'lines': s['lines'], 'chords': s['chords']}
                   for s in parsed['slides']],
    }


def run_pipeline(url: str, html: str) -> dict:
    page = ew_fetch.parse_page(url, html)
    ui = ui_stage([page])[0]
    stage1 = {k: page.get(k) for k in ('title', 'artist', 'key', 'capo', 'lyrics_only', 'chart_text')}
    stage3 = build_pro(page.get('title', ''), page.get('artist', ''), ui['chart'],
                       ui['concertKey'], lyrics_only=bool(page.get('lyrics_only')))
    return {'site': page.get('_site'), 'parse': stage1, 'ui': ui, 'pro': stage3}


class UrlFixtureTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.manifest = load_manifest()
        if not cls.manifest:
            raise unittest.SkipTest('no local fixtures — add some with tests/tools/add_fixture.py')

    def test_snapshots(self):
        for fid, meta in self.manifest.items():
            with self.subTest(fixture=fid):
                with open(os.path.join(LOCAL, 'pages', fid + '.html'), encoding='utf-8') as f:
                    html = f.read()
                result = run_pipeline(meta['url'], html)
                snap = os.path.join(LOCAL, 'snapshots', fid + '.json')
                if UPDATE or not os.path.exists(snap):
                    os.makedirs(os.path.dirname(snap), exist_ok=True)
                    with open(snap, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                        f.write('\n')
                    continue
                with open(snap, encoding='utf-8') as f:
                    expected = json.load(f)
                for stage in ('parse', 'ui', 'pro'):
                    self.assertEqual(result[stage], expected[stage], f'{fid}: stage "{stage}" changed')

    def test_capo_round_trip(self):
        """A capo chart converted to concert pitch and exported with the same
        capo must give back the site's original chord shapes."""
        for fid, meta in self.manifest.items():
            with open(os.path.join(LOCAL, 'pages', fid + '.html'), encoding='utf-8') as f:
                page = ew_fetch.parse_page(meta['url'], f.read())
            if not page.get('capo'):
                continue
            with self.subTest(fixture=fid):
                ui = ui_stage([page])[0]
                if not ui['capo']:
                    continue
                concert = build_pro(page['title'], page['artist'], ui['chart'], ui['concertKey'],
                                    capo=ui['capo'])
                # The site's own chart, built untouched in its shapes key.
                original = build_pro(page['title'], page['artist'], page['chart_text'], ui['chartKey'])
                self.assertIn(f"(Capo {ui['capo']})", concert['file_name'])
                self.assertEqual([s['chords'].split() for s in concert['slides']],
                                 [s['chords'].split() for s in original['slides']],
                                 f'{fid}: capo {ui["capo"]} shapes differ from the site chart')


if __name__ == '__main__':
    unittest.main()
