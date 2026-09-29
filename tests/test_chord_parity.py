"""
Python ↔ app parity: the .pro builder (scripts/md_to_pro.py) and the app
(src/music.ts) must agree on what's a chord, what's a chord line, and where
each chord sits. Every bug fixed in v1.2 came from the two disagreeing.

Checks every chord name the grammar can produce, a set of tricky lines, and —
when local fixtures exist — every line of every saved song.

Run: python3 -m unittest discover tests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import md_to_pro    # noqa: E402

LOCAL = os.path.join(ROOT, 'tests', 'fixtures', 'local')

LINES = [
    'G        Am     C', '         G#m              F#        B', '|(G) D/F# Em D | C  D  |',
    '| G | D/F# Em |', '| / / / / |', 'G  Am  C  x2', '(Ab(sus4))  (D)', 'C-7   F7', 'G-D-Em  C',
    'N.C.', 'Bm7b5   E7#9   Am', 'DbMaj7    C7(b9)  C7(B9)', 'A mighty fortress', 'Go tell it',
    'Ah   ah   ah', 'Intro: G Am C', 'e|--7--9--|', '----------', 'G*  C*', 'Cm(maj7)  C+  C°7',
]


def app_answers(tokens: list[str], lines: list[str]) -> dict:
    out = subprocess.run(['node', '--no-warnings', os.path.join(ROOT, 'tests', 'chord_parity.ts')],
                         input=json.dumps({'tokens': tokens, 'lines': lines}),
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def grammar_tokens() -> list[str]:
    g = md_to_pro._GRAMMAR
    toks = []
    for fam, quals in g['qualities'].items():
        for q in quals:
            for ext in g['extensions'][fam]:
                toks.append('G' + q + ext)
    toks += ['Ab' + x for x in ('(sus4)', '(add4)', '7(b9)', 'm(maj7)')]
    toks += ['C/E', 'Am/G', 'F#m7/C#'] + g['no_chord']
    toks += ['Go', 'Do', 'Ah', 'Amen', 'Bad', 'Co7', 'Gzz', 'H7', 'x2']   # must be rejected
    return toks


def fixture_lines() -> list[str]:
    lines = []
    snaps = os.path.join(LOCAL, 'snapshots')
    for dirpath, _, files in os.walk(snaps):
        for f in files:
            with open(os.path.join(dirpath, f), encoding='utf-8') as fh:
                snap = json.load(fh)
            lines += snap['parse']['chart_text'].splitlines() + snap['ui']['chart'].splitlines()
    return lines


class Parity(unittest.TestCase):
    maxDiff = None

    def test_tokens(self):
        toks = grammar_tokens()
        app = app_answers(toks, [])
        py = [md_to_pro.chord_quality(t) for t in toks]
        diffs = [(t, p, a) for t, p, a in zip(toks, py, app['tokens']) if p != a]
        self.assertEqual(diffs, [], 'Python and the app classify these chords differently')

    def test_transposition(self):
        toks = [t for t in grammar_tokens() if md_to_pro._is_chord_token(t)]
        app = app_answers(toks, [])
        py = [md_to_pro.transpose_chord(t, 3, False) for t in toks]
        diffs = [(t, p, a) for t, p, a in zip(toks, py, app['transposed']) if p != a]
        self.assertEqual(diffs, [], 'Python and the app transpose these chords differently')

    def test_lines(self):
        lines = LINES + fixture_lines()
        app = app_answers([], lines)
        diffs = []
        for line, got in zip(lines, app['lines']):
            py = md_to_pro.scan_chord_line(line)
            py = [list(p) for p in py] if py else None
            if py != got:
                diffs.append((line, py, got))
        self.assertEqual(diffs[:10], [], f'{len(diffs)} lines read differently by Python and the app')


if __name__ == '__main__':
    unittest.main()
