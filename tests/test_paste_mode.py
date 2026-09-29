"""
Paste tab: a chart pasted from a print view / PDF (made-up text) must come out
with its key and capo read, header junk dropped, and chords on the slides.

Run: python3 -m unittest discover tests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
from test_url_fixtures import build_pro   # noqa: E402

# Shaped like a copy of Ultimate Guitar's print view: title/artist, tuning,
# capo and key lines, page markers, G shapes for a song that sounds in Bb.
PASTED = """Morning Song Official
Test Artist
Tuning: E A D G B E
Capo: 3rd fret
Key: Bb

[Verse 1]
G            C          G
Praise Him in the morning light
         Em      D
Sing His name above
Page 1/2
[Chorus]
C          G/B        Am7
Glory, glory to the King
"""


def paste_stage(text: str) -> dict:
    out = subprocess.run(['node', '--no-warnings', os.path.join(ROOT, 'tests', 'paste_stage.ts')],
                         input=text, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class PasteMode(unittest.TestCase):
    def test_key_capo_and_cleanup(self):
        r = paste_stage(PASTED)
        self.assertEqual((r['chartKey'], r['concertKey'], r['capo']), ('G', 'Bb', 3))
        self.assertEqual(r['titleGuess'], 'Morning Song')
        for junk in ('Tuning:', 'Capo:', 'Key:', 'Page 1/2', 'Test Artist'):
            self.assertNotIn(junk, r['chart'])
        # Chart converted to concert pitch (G shapes + capo 3 → Bb).
        self.assertIn('Bb', r['chart'].splitlines()[1])

    def test_builds_a_pro_with_chords(self):
        r = paste_stage(PASTED)
        pro = build_pro('Morning Song', 'Test Artist', r['chart'], r['concertKey'])
        lyric_slides = [s for s in pro['slides'] if any(l.strip() for l in s['lines'])]
        self.assertEqual(len(lyric_slides), 3)
        self.assertTrue(all(s['chords'].strip() for s in lyric_slides))
        self.assertIn('Bb', pro['file_name'])

    def test_capo_back_to_shapes(self):
        # Exporting with the original capo 3 gives back the pasted G shapes.
        r = paste_stage(PASTED)
        pro = build_pro('Morning Song', '', r['chart'], r['concertKey'], capo=3)
        first = next(s for s in pro['slides'] if any(l.strip() for l in s['lines']))
        self.assertEqual(first['chords'].split(), ['G', 'C', 'G'])

    def test_page_furniture_and_artist(self):
        # Shaped like a browser copy of UG's print view: a close-button "X",
        # artist links, chord-diagram and strumming headings before the chart.
        raw = ('X\nMorning Song Official\nby [Test Artist](https://example.com/a) & [Second](https://example.com/b)\n'
               'Tuning: E A D G B E\nChords\nG\nStrumming pattern\n1\n&\n\n[Verse 1]\nG     C\nSing out loud\n')
        r = paste_stage(raw)
        self.assertEqual(r['titleGuess'], 'Morning Song')
        self.assertEqual(r['artistGuess'], 'Test Artist & Second')
        self.assertTrue(r['chart'].startswith('[Verse 1]'))

    def test_mojibake_apostrophes_repaired(self):
        # "’" copied through a Latin-1 misread arrives as "â\x80\x99" / "â€™".
        r = paste_stage('[Verse 1]\nG       C\nI\u00e2\u0080\u0099m free, you\u00e2\u20ac\u2122re here\n')
        self.assertIn('I’m free, you’re here', r['chart'])
        pro = build_pro('Moji', '', r['chart'], r['concertKey'])
        lyric = next(s['lines'][0] for s in pro['slides'] if s['lines'] and s['lines'][0].strip())
        self.assertEqual(lyric, "I'M FREE, YOU'RE HERE")   # slides store caps; ’ → '

    def test_no_headers_still_makes_slides(self):
        r = paste_stage('G          C\nPraise Him in the morning\nD         G\nSing His name above\n')
        pro = build_pro('No Headers', '', r['chart'], r['concertKey'])
        self.assertEqual(len([s for s in pro['slides'] if any(l.strip() for l in s['lines'])]), 2)


if __name__ == '__main__':
    unittest.main()
