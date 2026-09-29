"""
Rule tests for chord/lyric parsing — made-up lines only, so they're safe to
commit and run anywhere (no saved site pages needed).

Run: python3 -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import ew_fetch     # noqa: E402
import md_to_pro    # noqa: E402
import parse_pro    # noqa: E402


class ChordTokens(unittest.TestCase):
    # Common names from ChordPro's extension lists; all but Co7 failed before v1.2.
    CHORDPRO_COMMON = ['Bm7b5', 'Am7b5', 'F#m7b5', 'E7#9', 'C7b9', 'G7#5', 'C69', 'C6add9', 'Cadd11',
                       'C7alt', 'C+', 'Caug7', 'Cdim7', 'C°7', 'Cø', 'Cm(maj7)', 'CmMaj7', 'C-7', 'Cmi7',
                       'C^7', 'C7-9', 'C9#11', 'Bb13#11', 'Cmaj13', 'C13sus', 'Dsus2/F#']

    def test_chordpro_common(self):
        for tok in self.CHORDPRO_COMMON:
            self.assertTrue(md_to_pro._is_chord_token(tok), tok)

    def test_lyric_words_are_not_chords(self):
        # Why ChordPro's 'o' / 'h' qualities are left out of the grammar.
        for word in ['Go', 'Do', 'Ah', 'Be', 'Bad', 'Add', 'Ed', 'Fade', 'Amen', 'Dead', 'Babe', 'Ace']:
            self.assertFalse(md_to_pro._is_chord_token(word), word)

    def test_minor_spellings(self):
        for tok in ['Em7', 'E-7', 'Emi7', 'Emin', 'Em(maj7)']:
            self.assertEqual(md_to_pro._normalize_chord(tok), 'Em', tok)

    def test_recognised(self):
        for tok in ['G', 'Em7', 'G/B', 'Cadd9', 'Dsus4', 'G5', 'C2', 'Gmaj7', 'F#m7',
                    'Ab(sus4)', 'Ab(add4)', 'DbMaj7', 'C7(b9)', 'C7(B9)', 'G(#11)', 'Am(add9)']:
            self.assertTrue(md_to_pro._is_chord_token(tok), tok)

    def test_not_chords(self):
        for tok in ['Hello', 'Amazing', 'Go', 'Be', 'x2', 'Chorus']:
            self.assertFalse(md_to_pro._is_chord_token(tok), tok)

    def test_transpose_keeps_quality(self):
        self.assertEqual(md_to_pro.transpose_chord('Ab(sus4)', 2, False), 'A#(sus4)')
        self.assertEqual(md_to_pro.transpose_chord('DbMaj7', 1, False), 'DMaj7')
        self.assertEqual(md_to_pro.transpose_chord('C7(b9)', 2, False), 'D7(b9)')


class Lines(unittest.TestCase):
    def test_tab_staff_lines(self):
        for line in ['e|--7--9--|', 'B|--10--12--14------|', 'E|-----------|(x4)',
                     '|---5---|', 'D|-7h9-7p5--|']:
            self.assertTrue(md_to_pro.is_tab_staff_line(line), line)
        for line in ['| G | D/F# Em |', '|(G) D/F# Em D | C  D  |', '| G - - - | D |',
                     'Glory to the King']:
            self.assertFalse(md_to_pro.is_tab_staff_line(line), line)

    def test_dash_is_minor_or_separator(self):
        self.assertEqual(md_to_pro.scan_chord_line('C-7   F7'), [(0, 'C-7'), (6, 'F7')])
        self.assertEqual(md_to_pro.scan_chord_line('G-D-Em  C'), [(0, 'G'), (2, 'D'), (4, 'Em'), (8, 'C')])

    def test_trailing_dash_is_a_connector(self):
        # "C-Bb-  Ab-" is a walk-down, not C minor / Bb minor.
        self.assertEqual([c for _, c in md_to_pro.scan_chord_line('C-Bb-  Ab-  G')], ['C', 'Bb', 'Ab', 'G'])
        self.assertEqual(md_to_pro.chord_quality('C-7'), 'minor')
        self.assertIsNone(md_to_pro.chord_quality('C-'))

    def test_strum_pattern_is_filler(self):
        self.assertTrue(md_to_pro.is_divider_line('| / / / / |'))
        self.assertFalse(md_to_pro.is_chord_line('| / / / / |'))

    def test_bar_line_chord_lines(self):
        for line in ['| G | D/F# Em |', '|(G) D/F# Em D | C  D  |', 'G  Am  C  x2']:
            self.assertTrue(md_to_pro.is_chord_line(line), line)


class TabsAndDividers(unittest.TestCase):
    def test_tabs_expand_before_positions(self):
        # "\tG" is 8 columns in, not 1: the chord must land on column 8.
        chart = '[Verse 1]\n\tG\nPraise Him in the morning\n'
        with tempfile.TemporaryDirectory() as d:
            md = os.path.join(d, 'c.md')
            with open(md, 'w', encoding='utf-8') as f:
                f.write(ew_fetch.convert_chart_to_md(chart, 'Tab Song', ''))
            with contextlib.redirect_stdout(io.StringIO()):
                md_to_pro.process_file(md, output_dir=d, source_key='G')
            pro = [n for n in os.listdir(d) if n.endswith('.pro')][0]
            slides = parse_pro.parse_pro_file(os.path.join(d, pro))['slides']
        self.assertEqual(slides[0]['chords'], ' ' * 8 + 'G')

    def test_divider_lines(self):
        for line in ['----------', '=====', '.....']:
            self.assertTrue(md_to_pro.is_divider_line(line), line)
        for line in ['G - - - D', '| G | D |', 'Amen']:
            self.assertFalse(md_to_pro.is_divider_line(line), line)

    def test_first_line_indent_kept(self):
        md = ew_fetch.convert_chart_to_md('\n\n   G    C\nPraise Him\n', 'T', '')
        self.assertIn('```\n   G    C\n', md)


class UltimateGuitarMarkers(unittest.TestCase):
    def _page(self, content):
        # The UG parser only takes "content" longer than 100 chars — pad it.
        data = {'store': {'page': {'data': {'tab': {'song_name': 'X'}, 'tab_view': {'meta': {}}}}},
                'x': {'content': content + '\n' + 'la ' * 40}}
        return '<div data-content="' + json.dumps(data).replace('"', '&quot;') + '" >'

    def test_unrecognized_marked_chords_reported(self):
        # Bm7b5 is known since the v1.2 grammar; Gzz7 is not a chord at all.
        page = self._page('[Verse]\n[ch]Bm7b5[/ch]   [ch]Gzz7[/ch]\nwords long enough to be the chart content here')
        self.assertEqual(ew_fetch.parse_ultimate_guitar(page)['unrecognized_chords'], ['Gzz7'])

    def test_official_pro_page_explained(self):
        data = {'store': {'page': {'data': {'has_pro_tab_version': True, 'has_official_version': True,
                                            'official_version': {'1': 'x'}}}}}
        page = ('<a href="https://tabs.ultimate-guitar.com/tab/test-artist/morning-song-official-123">'
                '<div data-content="' + json.dumps(data).replace('"', '&quot;') + '" >')
        err = ew_fetch.parse_ultimate_guitar(page).get('error', '')
        self.assertIn('Official (Pro)', err)
        self.assertIn('value=morning+song', err)
        self.assertIn('Paste tab', err)

    def test_all_recognized(self):
        page = self._page('[Verse]\n[ch]G[/ch]   [ch]D/F#[/ch]\nwords long enough to be the chart content here')
        self.assertEqual(ew_fetch.parse_ultimate_guitar(page)['unrecognized_chords'], [])


class ChordPositions(unittest.TestCase):
    def test_indented_chord_keeps_its_column(self):
        # Chord line starts 9 columns in: the chord must stay over column 9.
        pos = md_to_pro._map_chord_positions('         Em        C', 'Sing a new song to the King above')
        self.assertEqual(pos, {9: 'Em', 19: 'C'})

    def test_lyric_indent_is_subtracted(self):
        # Both lines indented by one space (UG " Our God…" style).
        pos = md_to_pro._map_chord_positions(' G          D', 'Holy is the Lord our God', lyric_indent=1)
        self.assertEqual(pos, {0: 'G', 11: 'D'})

    def test_bracketed_and_bar_chords_found(self):
        pos = md_to_pro._map_chord_positions('|(G) D/F# Em', 'Sing a new song to the King')
        self.assertEqual(pos, {2: 'G', 5: 'D/F#', 10: 'Em'})

    def test_trailing_chords_all_kept(self):
        # Chords past the end of a short lyric must not overwrite each other.
        pos = md_to_pro._map_chord_positions('Db          Dbsus4    Db', 'Holy is He')
        self.assertEqual(list(pos.values()), ['Db', 'Dbsus4', 'Db'])

    def test_lead_in_chords_all_kept(self):
        # Chords written before an indented lyric starts all land on it, in order.
        pos = md_to_pro._map_chord_positions('G   C   G/B   C', 'Amen', lyric_indent=16)
        self.assertEqual(pos, {0: 'G', 1: 'C', 2: 'G/B', 3: 'C'})

    def test_squeezed_spaces_keep_chords_on_their_words(self):
        # Extra spaces in a lyric are squeezed on the slide; chords must move with the words.
        chart = '[Verse 1]\nG               D\nPraise Him      now\n'
        with tempfile.TemporaryDirectory() as d:
            md = os.path.join(d, 'c.md')
            with open(md, 'w', encoding='utf-8') as f:
                f.write(ew_fetch.convert_chart_to_md(chart, 'Gap Song', ''))
            with contextlib.redirect_stdout(io.StringIO()):
                md_to_pro.process_file(md, output_dir=d, source_key='G')
            pro = [n for n in os.listdir(d) if n.endswith('.pro')][0]
            slide = parse_pro.parse_pro_file(os.path.join(d, pro))['slides'][0]
        self.assertEqual(slide['lines'][0], 'PRAISE HIM NOW')
        self.assertEqual(slide['chords'].index('D'), slide['lines'][0].index('NOW'))

    def test_built_pro_keeps_positions(self):
        """End to end: an indented chord line survives into the .pro file."""
        chart = '[Verse 1]\n          G            D\nPraise Him in the morning light\n'
        with tempfile.TemporaryDirectory() as d:
            md = os.path.join(d, 'c.md')
            with open(md, 'w', encoding='utf-8') as f:
                f.write(ew_fetch.convert_chart_to_md(chart, 'Test Song', ''))
            with contextlib.redirect_stdout(io.StringIO()):
                md_to_pro.process_file(md, output_dir=d, source_key='G')
            pro = [n for n in os.listdir(d) if n.endswith('.pro')][0]
            slides = parse_pro.parse_pro_file(os.path.join(d, pro))['slides']
        self.assertEqual(slides[0]['chords'], '          G            D')


class WorshipChordsComKey(unittest.TestCase):
    G_SHAPES = 'G    C    D    Em\nPraise Him\nG    C    D\nPraise Him again'
    DB_CHART = 'Db   Gb   Ab   Bbm\nPraise Him\nDb   Gb   Ab\nPraise Him again'

    def test_chart_in_suggested_capo_shapes(self):
        # Original Ab, suggested "G with capo 1", chart in G shapes → Ab, capo 1
        self.assertEqual(ew_fetch._wc_resolve_key(self.G_SHAPES, 'Ab', 'G', 1), ('Ab', 1))

    def test_chart_in_original_key(self):
        # Original Db, suggested "C with capo 1", chart in Db → Db, no capo
        self.assertEqual(ew_fetch._wc_resolve_key(self.DB_CHART, 'Db', 'C', 1), ('Db', 0))

    def test_chart_in_suggested_key_no_capo(self):
        self.assertEqual(ew_fetch._wc_resolve_key(self.G_SHAPES, 'A', 'G', 0), ('G', 0))


class UnsupportedSites(unittest.TestCase):
    def test_echords(self):
        self.assertIsNotNone(ew_fetch.unsupported_reason('https://www.e-chords.com/chords/x/y'))
        self.assertIsNone(ew_fetch.unsupported_reason('https://tabs.ultimate-guitar.com/tab/x'))


class RtfText(unittest.TestCase):
    def test_non_latin_characters_do_not_crash(self):
        from create_pro_song import build_rtf
        rtf = build_rtf('Iʼm free 愛')
        self.assertIn(b"I'M FREE \\u24859?", rtf)


if __name__ == '__main__':
    unittest.main()
