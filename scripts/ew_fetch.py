#!/usr/bin/env python3
"""
ew_fetch.py — Universal chord chart fetcher → ProPresenter .pro converter.

Supports:
  EssentialWorship, WorshipTogether, WorshipChords.com, WorshipChords.net,
  Ultimate Guitar, and a generic fallback for unknown sites.

Usage:
  # Preview mode — outputs JSON for the ChordPresenter UI:
  python3 ew_fetch.py --url URL --preview

  # Generate from a fresh fetch:
  python3 ew_fetch.py --url URL [--key KEY] [--out DIR]

  # Generate from a chart file (user-edited content from the UI):
  python3 ew_fetch.py --chart-file PATH --title TITLE --artist ARTIST [--key KEY] [--out DIR]
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import os
import tempfile
import subprocess
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md_to_pro  # key detection helpers, shared with the .pro builder
from html.parser import HTMLParser


# ── Shared section-name regex (mirrors md_to_pro.py SECTION_NAME_RE) ──────────

SECTION_NAME_RE = re.compile(
    r'^(intro|verse|chorus|pre[\s\-]?chorus|bridge|tag|outro|interlude|'
    r'instrumental|ending|coda|hook|turn|turnaround|transition|vamp|'
    r'breakdown|refrain)\s*\d*\s*:?\s*$',
    re.IGNORECASE
)

# ── EW-specific section name handling ─────────────────────────────────────────

EW_SECTION_RE = re.compile(
    r'^(Intro|Verse\s*\d*|Chorus|Pre[\s\-]?Chorus|Bridge|Tag\s*\d*|'
    r'Outro|Interlude|Instrumental|Ending|Coda|Hook|Turn|Transition)\s*$',
    re.IGNORECASE
)

_EW_NAME_MAP = {
    'INSTRUMENTAL': 'INTERLUDE',
}


def ew_header_to_bracket(line: str) -> str | None:
    stripped = line.strip()
    m = EW_SECTION_RE.match(stripped)
    if not m:
        return None
    name = m.group(1).strip().upper()
    name = _EW_NAME_MAP.get(name, name)
    return f'[{name}]'


def convert_chart_to_md(chart_text: str, title: str, artist: str) -> str:
    """
    Convert raw chart text (plain section headers) to the MD format
    that md_to_pro.py expects (bracket headers + code block + YAML frontmatter).
    """
    lines = chart_text.splitlines()
    converted = []
    for line in lines:
        bracket = ew_header_to_bracket(line)
        if bracket:
            converted.append(bracket)
        else:
            converted.append(line)

    converted = [l for l in converted
                 if 'Chord chart and lyrics provided by' not in l]

    # Trim blank lines at the edges only — keep the first line's indentation
    # (an indented chord line's leading spaces are its chord positions).
    chart_body = re.sub(r'^(?:[ \t]*\n)+', '', '\n'.join(converted)).rstrip()

    title_esc  = title.replace('"', '\\"')
    artist_esc = artist.replace('"', '\\"')
    full_title = f'{title_esc} | {artist_esc}' if artist_esc else title_esc

    return f'---\ntitle: "{full_title}"\nsource: "chord-fetch"\n---\n\n```\n{chart_body}\n```\n'


# ── Network ────────────────────────────────────────────────────────────────────

def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        charset = 'utf-8'
        ct = resp.headers.get('Content-Type', '')
        if 'charset=' in ct:
            charset = ct.split('charset=')[-1].strip().split(';')[0].strip()
        return raw.decode(charset, errors='replace')


# ── Site detection ─────────────────────────────────────────────────────────────

# Sites we deliberately don't parse. Checked before fetching so the user gets
# a clear reason instead of a raw HTTP error or a half-parsed page.
UNSUPPORTED_SITES = {
    'e-chords.com': 'E-Chords isn\'t supported — the site blocks automated requests. '
                    'Try the same song on Ultimate Guitar, WorshipTogether, or WorshipChords.',
}

def unsupported_reason(url: str) -> str | None:
    url_lower = url.lower()
    for domain, reason in UNSUPPORTED_SITES.items():
        if domain in url_lower:
            return reason
    return None

def detect_site(url: str) -> str:
    url_lower = url.lower()
    if 'essentialworship.com' in url_lower:       return 'essentialworship'
    if 'worshiptogether.com' in url_lower:        return 'worshiptogether'
    if 'worshipchords.net' in url_lower:          return 'worshipchords_net'
    if 'worshipchords.com' in url_lower:          return 'worshipchords_com'
    if 'ultimate-guitar.com' in url_lower:        return 'ultimate_guitar'
    if 'tabs.ultimate-guitar.com' in url_lower:  return 'ultimate_guitar'
    if 'genius.com' in url_lower:                return 'genius'
    if 'allchristiansongslyrics.com' in url_lower: return 'lyrics_generic'
    if 'azlyrics.com' in url_lower:              return 'lyrics_generic'
    if 'lyricsfreak.com' in url_lower:           return 'lyrics_generic'
    if 'songlyrics.com' in url_lower:            return 'lyrics_generic'
    return 'generic'


# ── Helper: strip HTML tags, unescape entities ─────────────────────────────────

def _strip_html(s: str) -> str:
    s = re.sub(r'<[^>]+>', '', s)
    return html_mod.unescape(s)


def _fix_broken_brackets(text: str) -> str:
    """Fix section headers where [ was stripped, e.g. 'Intro]' → '[Intro]'."""
    lines = text.splitlines()
    fixed = []
    for line in lines:
        s = line.strip()
        if s.endswith(']') and not s.startswith('[') and len(s) <= 30:
            line = line.replace(s, '[' + s, 1)
        fixed.append(line)
    return '\n'.join(fixed)


# ══════════════════════════════════════════════════════════════════════════════
# SITE PARSERS — each returns {title, artist, key, chart_text}
# ══════════════════════════════════════════════════════════════════════════════

# ── EssentialWorship ───────────────────────────────────────────────────────────

class EWHTMLParser(HTMLParser):
    """Extract title, artist, recommended key, and chord chart from an EW page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title      = ''
        self.artist     = ''
        self.rec_key    = ''
        self.chart_text = ''

        self._in_h1     = False
        self._in_h2     = False
        self._in_pre    = False
        self._in_strong = False

        self._h1_buf     = []
        self._h2_buf     = []
        self._pre_buf    = []
        self._strong_buf = []
        self._pre_blocks = []
        self._last_strong_label = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'h1':
            self._in_h1 = True; self._h1_buf = []
        elif tag == 'h2':
            self._in_h2 = True; self._h2_buf = []
        elif tag == 'pre':
            self._in_pre = True; self._pre_buf = []
        elif tag in ('strong', 'b'):
            self._in_strong = True; self._strong_buf = []

    def handle_endtag(self, tag):
        if tag == 'h1':
            self._in_h1 = False
            text = ''.join(self._h1_buf).strip()
            if text and not self.title:
                self.title = text
        elif tag == 'h2':
            self._in_h2 = False
            text = ''.join(self._h2_buf).strip()
            if 'By:' in text and not self.artist:
                self.artist = re.sub(r'.*?By:\s*', '', text).strip()
        elif tag == 'pre':
            self._in_pre = False
            content = ''.join(self._pre_buf)
            if content.strip():
                self._pre_blocks.append(content)
            self._pre_buf = []
        elif tag in ('strong', 'b'):
            self._in_strong = False
            self._last_strong_label = ''.join(self._strong_buf).strip()

    def handle_data(self, data):
        if self._in_h1:    self._h1_buf.append(data)
        if self._in_h2:    self._h2_buf.append(data)
        if self._in_pre:   self._pre_buf.append(data)
        if self._in_strong: self._strong_buf.append(data)
        elif self._last_strong_label in ('Recommended Key:', 'Recommended Key'):
            key = data.strip()
            if re.match(r'^[A-G][#b]?m?$', key) and not self.rec_key:
                self.rec_key = key
            self._last_strong_label = ''

    def get_chart(self) -> str:
        if not self._pre_blocks:
            return ''
        best = max(self._pre_blocks, key=len)
        lines = best.splitlines()
        lines = [l for l in lines if 'Chord chart and lyrics provided by' not in l]
        fixed = []
        for line in lines:
            s = line.strip()
            if s.endswith(']') and not s.startswith('[') and len(s) <= 30:
                line = line.replace(s, '[' + s, 1)
            fixed.append(line)
        return '\n'.join(fixed).strip()


def _extract_ew_fallbacks(html_content: str) -> str:
    pre_m = re.search(r'<pre[^>]*>(.*?)</pre>', html_content, re.DOTALL | re.IGNORECASE)
    if pre_m:
        text = re.sub(r'<[^>]+>', '', pre_m.group(1))
        text = re.sub(r'Chord chart and lyrics provided by.*', '', text, flags=re.IGNORECASE)
        if len(text.strip()) > 50:
            return _fix_broken_brackets(text.strip())
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', html_content, re.DOTALL | re.IGNORECASE):
        blob = m.group(1)
        for key in ('chord_chart', 'chart', 'chords', 'post_content'):
            jm = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)+)"', blob)
            if jm:
                text = jm.group(1).replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                if len(text.strip()) > 50:
                    return text.strip()
    div_m = re.search(r'<div[^>]*class="[^"]*chord[^"]*"[^>]*>(.*?)</div>',
                      html_content, re.DOTALL | re.IGNORECASE)
    if div_m:
        text = re.sub(r'<[^>]+>', '', div_m.group(1))
        if len(text.strip()) > 50:
            return text.strip()
    return ''


def parse_essentialworship(html_content: str) -> dict:
    parser = EWHTMLParser()
    parser.feed(html_content)

    chart = parser.get_chart()
    if not chart:
        chart = _extract_ew_fallbacks(html_content)

    if not parser.artist:
        h2_m = re.search(r'<h2[^>]*>(.*?)</h2>', html_content, re.DOTALL | re.IGNORECASE)
        if h2_m:
            txt = re.sub(r'<[^>]+>', '', h2_m.group(1)).strip()
            if txt and 'by:' not in txt.lower() and len(txt) < 80:
                parser.artist = txt

    if not parser.rec_key:
        km = re.search(r'Recommended Key[:\s]+([A-G][#b]?m?)\b', html_content)
        if km:
            parser.rec_key = km.group(1)

    return {
        'title':      parser.title,
        'artist':     parser.artist,
        'key':        parser.rec_key,
        'chart_text': chart,
    }


# ── WorshipTogether ────────────────────────────────────────────────────────────

def parse_worshiptogether(html: str) -> dict:
    """
    WT renders chord charts using ChordPro segments:
      <div class="chord-pro-line">
        <div class="chord-pro-segment">
          <div class="chord-pro-note">D&nbsp;</div>
          <div class="chord-pro-lyric">Lord, I'm desperate for a </div>
        </div>
        <div class="chord-pro-segment">
          <div class="chord-pro-note">C2&nbsp;</div>
          <div class="chord-pro-lyric">holy change</div>
        </div>
      </div>

    Key is in data-original-key attribute.
    Each chord-pro-line becomes one ProPresenter slide.
    """
    # Title
    title_m = re.search(r'class="t-song-details__marquee__headline">(.*?)</h1>', html)
    title = html_mod.unescape(title_m.group(1).strip()) if title_m else ''

    # Artist — page title format: "SONG - ARTIST | Worship Together"
    artist = ''
    page_title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    if page_title_m:
        pt = page_title_m.group(1).strip()
        # "Breathe On It - Tauren Wells | Worship Together"
        m = re.match(r'^.*?\s*[-–]\s*(.*?)\s*\|\s*Worship', pt, re.IGNORECASE)
        if m:
            artist = m.group(1).strip()
    if not artist:
        for pat in [
            r'"artistName"\s*:\s*"([^"]+)"',
            r'class="t-song-details__marquee__artist[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>',
        ]:
            am = re.search(pat, html, re.DOTALL)
            if am:
                candidate = html_mod.unescape(_strip_html(am.group(1)).strip())
                if candidate and len(candidate) < 60 and '  ' not in candidate:
                    artist = candidate
                    break

    # Key
    key_m = re.search(r'data-original-key="([^"]+)"', html)
    key = key_m.group(1) if key_m else ''

    # Find the chord-pro-disp section
    disp_start = html.find('chord-pro-disp')
    if disp_start == -1:
        return {'title': title, 'artist': artist, 'key': key, 'chart_text': ''}
    disp_html = html[disp_start:]

    note_re  = re.compile(r'<div\s+class="chord-pro-note">(.*?)</div>', re.DOTALL)
    lyric_re = re.compile(r'<div\s+class="chord-pro-lyric">(.*?)</div>', re.DOTALL)

    chart_lines = []

    # Split into chord-pro-lines, then each line into chord-pro-segments
    for line_chunk in re.split(r'<div\s+class="chord-pro-line">', disp_html)[1:]:
        seg_chunks = re.split(r'<div\s+class="chord-pro-segment">', line_chunk)[1:]
        if not seg_chunks:
            continue

        pairs = []
        for seg in seg_chunks:
            nm = note_re.search(seg)
            lm = lyric_re.search(seg)
            note  = html_mod.unescape(re.sub(r'<[^>]+>', '', nm.group(1))).strip() if nm else ''
            lyric = html_mod.unescape(re.sub(r'<[^>]+>', '', lm.group(1))).strip() if lm else ''
            pairs.append((note, lyric))

        all_notes  = [n for n, _ in pairs]
        all_lyrics = [l for _, l in pairs]
        has_chord  = any(n for n in all_notes)
        full_lyric = ' '.join(l for l in all_lyrics if l).strip()

        # Section header: no chord, lyric matches a known section name
        if not has_chord and full_lyric and SECTION_NAME_RE.match(full_lyric):
            chart_lines.append(f'[{full_lyric.upper()}]')
            continue

        # Chord-only line (instrumental bar notation like "| Gsus / / G |")
        if has_chord and not full_lyric:
            chart_lines.append(' '.join(n for n in all_notes if n))
            continue

        # Regular chord+lyric — reconstruct aligned chord/lyric lines
        chord_line = ''
        lyric_line = ''
        for note, lyric in pairs:
            width = max(len(note) + 1 if note else 0, len(lyric) + 1 if lyric else 1)
            chord_line += note.ljust(width) if note else ' ' * width
            lyric_line += lyric.ljust(width)

        if chord_line.strip():
            chart_lines.append(chord_line.rstrip())
        if lyric_line.strip():
            chart_lines.append(lyric_line.rstrip())

    return {
        'title':      title,
        'artist':     artist,
        'key':        key,
        'chart_text': '\n'.join(chart_lines),
    }


# ── WorshipChords.com ──────────────────────────────────────────────────────────

def parse_worshipchords_com(html: str) -> dict:
    """
    WorshipChords.com puts the chart in a <pre> block as near-plain text.
    og:description format: "SONG Chords - ARTIST - view lyrics..."
    """
    # Title from h1 or og:title
    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    if not title_m:
        title_m = re.search(r'property="og:title" content="([^"]+)"', html)
    title = _strip_html(title_m.group(1)).strip() if title_m else ''
    title = re.sub(r'\s+Chords\s*$', '', title, flags=re.IGNORECASE).strip()

    # Artist from og:description: "SONG Chords - ARTIST - view lyrics..."
    artist = ''
    og_m = re.search(r'property="og:description" content="([^"]+)"', html)
    if og_m:
        desc = og_m.group(1)
        # Format: "Song Chords - Artist - view..."
        m = re.match(r'^.*?[Cc]hords\s*[-–]\s*([^-–]+?)(?:\s*[-–]|\s*$)', desc)
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) < 60:
                artist = candidate
    if not artist:
        # Fallback: regex for capitalized name pattern
        m = re.search(r'Artist.*?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', html)
        if m:
            artist = m.group(1).strip()

    # Metadata lists two keys: "Original Key: Ab" and "Suggested Worship Key:
    # G with capo 1" (or just "A"). The chart can be written in EITHER — Holy
    # Forever's is in the original Db, Build My Life's in the suggested G
    # shapes — so the chords decide which one applies (see _wc_resolve_key).
    meta_text = html_mod.unescape(re.sub(r'<[^>]+>', ' ', html))
    orig_m = re.search(r'Original Key:\s*([A-G][#b]?)(m(?!aj))?', meta_text)
    sugg_m = re.search(r'Suggested Worship Key:\s*([A-G][#b]?)(m(?!aj))?'
                       r'(?:\s*with\s*capo\s*(\d{1,2}))?', meta_text, re.IGNORECASE)
    original  = (orig_m.group(1) + (orig_m.group(2) or '')) if orig_m else ''
    suggested = (sugg_m.group(1) + (sugg_m.group(2) or '')) if sugg_m else ''
    sugg_capo = int(sugg_m.group(3)) if sugg_m and sugg_m.group(3) else 0

    # Extract <pre> block — use the largest one
    pre_blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL | re.IGNORECASE)
    if not pre_blocks:
        return {'title': title, 'artist': artist, 'key': original, 'capo': 0, 'chart_text': ''}
    chart = max(pre_blocks, key=len)
    chart = re.sub(r'<[^>]+>', '', chart)   # strip any HTML
    chart = html_mod.unescape(chart).strip()

    key, capo = _wc_resolve_key(chart, original, suggested, sugg_capo)
    return {
        'title':      title,
        'artist':     artist,
        'key':        key,
        'capo':       capo,
        'chart_text': chart,
    }


def _wc_resolve_key(chart: str, original: str, suggested: str, sugg_capo: int) -> tuple:
    """Return (concert key, capo) for a WorshipChords.com chart.

    Chords in the suggested key's shapes → concert = suggested + capo, with
    that capo (G shapes, capo 1 → Ab, capo 1). Otherwise the chart is in the
    original key with no capo. Keys compare by relative major so a chart the
    detector reads as Em still matches a suggested G.
    """
    try:
        chord_key = md_to_pro._key_from_body(chart)
        if suggested and chord_key != 'Unknown' and \
                md_to_pro._key_idx(chord_key) == md_to_pro._key_idx(suggested):
            if sugg_capo and 0 < sugg_capo < 12:
                return md_to_pro.shift_key(suggested, sugg_capo), sugg_capo
            return suggested, 0
    except ValueError:
        pass
    return original, 0


# ── WorshipChords.net ──────────────────────────────────────────────────────────

def parse_worshipchords_net(html: str) -> dict:
    """
    WorshipChords.net uses a <pre> block with HTML spans for chords and section headers.
    Page <title> format: "SONG Chords by ARTIST - Worship Chords"
    Stripping HTML tags from the pre block gives a clean chord-above-lyric plain text chart.
    """
    # Title + artist from page <title>: "Magnified Chords by Lifeway - Worship Chords"
    title, artist = '', ''
    page_title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    if page_title_m:
        pt = page_title_m.group(1).strip()
        m = re.match(r'^(.*?)\s+[Cc]hords\s+by\s+(.*?)\s*[-–]', pt)
        if m:
            title  = m.group(1).strip()
            artist = m.group(2).strip()
        else:
            m2 = re.match(r'^(.*?)\s*[-–]\s*Worship', pt)
            if m2:
                title = m2.group(1).strip()

    key_m = re.search(r'[Oo]riginal [Kk]ey.*?([A-G][#b]?m?)', html)
    key   = key_m.group(1) if key_m else ''

    pre_m = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL | re.IGNORECASE)
    if not pre_m:
        return {'title': title, 'artist': artist, 'key': key, 'chart_text': ''}

    chart = pre_m.group(1)
    # Strip all HTML tags — the whitespace layout is preserved in the text nodes
    chart = re.sub(r'<[^>]+>', '', chart)
    chart = html_mod.unescape(chart)

    return {
        'title':      title,
        'artist':     artist,
        'key':        key,
        'chart_text': chart.strip(),
    }


# ── Ultimate Guitar ────────────────────────────────────────────────────────────

def _ug_pro_message(html: str) -> str:
    """Explain a UG Official/Pro link, with a search for the free versions."""
    from urllib.parse import quote_plus
    song = ''
    m = re.search(r'/tab/[^/"]+/([a-z0-9-]+?)-(?:official|pro|chords|tabs)-\d+', html)
    if m:
        song = m.group(1).replace('-', ' ')
    msg = ("This is an Ultimate Guitar Official (Pro) version, which is only available with a "
           "UG Pro subscription, so ChordPresenter can't fetch it. Use a free \"Chords\" version "
           "of the song instead")
    if song:
        msg += (f" (search: https://www.ultimate-guitar.com/search.php?search_type=title&value="
                f"{quote_plus(song)})")
    return msg + (". If you subscribe, you can open the song's Print view on Ultimate Guitar, "
                  "copy the chart, and use the Paste tab.")


def parse_ultimate_guitar(html: str) -> dict:
    """
    UG embeds everything in a JSON blob at data-content on the page.
    The chord chart uses [ch]CHORD[/ch] and [tab]...[/tab] markup.
    Section headers are already in [Bracket] format.
    """
    # Extract JSON from data-content attribute
    m = re.search(r'data-content="(.*?)"(?:\s|>)', html)
    if not m:
        return {'title': '', 'artist': '', 'key': '', 'chart_text': ''}

    json_str = html_mod.unescape(m.group(1))
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return {'title': '', 'artist': '', 'key': '', 'chart_text': ''}

    # UG "Official" / "Pro" versions are part of the paid UG Pro subscription.
    # Anonymously the page is just the "Ultimate Guitar Pro" upsell with no
    # chart (page data holds only official_version / has_pro_tab_version), so
    # say so plainly instead of "could not parse".
    page_data = (data.get('store', {}).get('page', {}) or {}).get('data', {}) or {}
    if not page_data.get('tab') and ('official_version' in page_data or 'has_pro_tab_version' in page_data):
        return {'title': '', 'artist': '', 'key': '', 'chart_text': '',
                'error': _ug_pro_message(html)}

    # Extract metadata from store.page.data.tab
    tab = {}
    try:
        tab = data['store']['page']['data']['tab']
    except (KeyError, TypeError):
        pass

    # Capo + key live in tab_view.meta (tab.capo doesn't exist — reading it
    # there silently dropped every UG capo). UG's key is the CONCERT key; the
    # chords are written as shapes for key − capo (e.g. key B, capo 4 → G).
    meta = {}
    try:
        meta = data['store']['page']['data']['tab_view']['meta'] or {}
    except (KeyError, TypeError):
        pass

    title  = tab.get('song_name', '')
    artist = tab.get('artist_name', '')
    key    = meta.get('tonality') or tab.get('tonality_name', '')
    try:
        capo = int(meta.get('capo') or tab.get('capo') or 0)
    except (TypeError, ValueError):
        capo = 0

    # Find 'content' field (the chord chart)
    def find_content(obj, depth=0):
        if depth > 6:
            return None
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == 'content' and isinstance(v, str) and len(v) > 100:
                    return v
                r = find_content(v, depth + 1)
                if r:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = find_content(item, depth + 1)
                if r:
                    return r
        return None

    content = find_content(data) or ''

    # UG marks every chord explicitly ([ch]Bm7b5[/ch]), so it's the one site
    # where we KNOW what's a chord. Any marked name our chord grammar rejects
    # would make its whole line read as lyrics (shown to the audience), so
    # report those for the app to warn about.
    marked = set(re.findall(r'\[ch\](.*?)\[/ch\]', content))
    unrecognized = sorted(c for c in marked if not md_to_pro._is_chord_token(c))

    # Convert UG markup to plain chord-above-lyric format
    # [ch]CHORD[/ch] → just CHORD (keep surrounding whitespace for alignment)
    content = re.sub(r'\[ch\](.*?)\[/ch\]', r'\1', content)
    # [tab]...[/tab] → strip markers, keep content
    content = re.sub(r'\[/?tab\]', '', content)
    # [Verse 1], [Chorus] etc. are already in bracket format — leave them

    return {
        'title':      title,
        'artist':     artist,
        'key':        key,
        'capo':       capo if 0 < capo < 12 else 0,
        'chart_text': content.strip(),
        'unrecognized_chords': unrecognized,
    }


# ── Genius.com ────────────────────────────────────────────────────────────────

class _GeniusLyrics(HTMLParser):
    """Text of every <div data-lyrics-container="true"> on a Genius page,
    one string per block, with <br> as line breaks and anything marked
    data-exclude-from-selection (headers, contributor counts) left out."""

    VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self._buf = [], []
        self._depth = 0          # open elements inside the current lyrics block
        self._skip = 0           # >0 while inside an excluded subtree

    @classmethod
    def extract(cls, html: str) -> list:
        p = cls()
        p.feed(html)
        p.close()
        return p.blocks

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._depth == 0:
            if tag == 'div' and a.get('data-lyrics-container') == 'true':
                self._depth, self._buf = 1, []
            return
        if tag == 'br':
            if not self._skip:
                self._buf.append('\n')
            return
        if tag in self.VOID:
            return
        self._depth += 1
        if self._skip or a.get('data-exclude-from-selection') == 'true':
            self._skip += 1

    def handle_endtag(self, tag):
        if self._depth == 0 or tag in self.VOID:
            return
        if self._skip:
            self._skip -= 1
        self._depth -= 1
        if self._depth == 0:
            self.blocks.append(''.join(self._buf))

    def handle_data(self, data):
        if self._depth and not self._skip:
            self._buf.append(data)


def parse_genius(html: str) -> dict:
    """
    Genius stores lyrics in one or more <div data-lyrics-container="true"> elements.
    Section headers appear as [Verse 1], [Chorus] etc., either inline or in <h2> tags.
    Lines are separated by <br> tags.

    Returns lyrics-only chart text (no chord lines) — always use with lyrics_only mode.
    """
    # Title: og:title or h1 — format "Artist – Song Lyrics"
    title, artist = '', ''
    og_title_m = re.search(r'property="og:title" content="([^"]+)"', html)
    if og_title_m:
        ot = og_title_m.group(1)
        # Format: "Artist Name – Song Title Lyrics" or "Song Title by Artist Name"
        m = re.match(r'^(.*?)\s*[–-]\s*(.*?)\s*(?:Lyrics)?\s*$', ot)
        if m:
            # Drop featured-artist credits so file names stay readable:
            # "Elevation Worship (Ft. Brandon Lake …)" → "Elevation Worship".
            artist = re.sub(r'\s*\((?:ft|feat|featuring)\.?\s.*\)\s*$', '',
                            m.group(1).strip(), flags=re.IGNORECASE)
            title  = re.sub(r'\s*Lyrics\s*$', '', m.group(2)).strip()

    if not title:
        h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        title = _strip_html(h1_m.group(1)).strip() if h1_m else ''

    key = ''  # Genius is lyrics-only, no key info

    # Lyrics live in <div data-lyrics-container="true"> blocks, which contain
    # nested elements — the first one opens with a header strip (title,
    # contributors) marked data-exclude-from-selection. A "first </div>" regex
    # stopped inside that header and lost everything after it (whole verses),
    # so the blocks are read with a real parser that tracks nesting.
    chart_lines = _GeniusLyrics.extract(html)
    if not chart_lines:
        # Fallback: older layout — a div with class containing "Lyrics"
        containers = re.findall(
            r'<div[^>]+class="[^"]*Lyrics[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE
        )
        for container in containers:
            text = re.sub(r'<br\s*/?>', '\n', container, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            chart_lines.append(html_mod.unescape(text))

    chart_text = '\n'.join(chart_lines).strip()

    # Normalize section headers: "[Verse 1]" stays as-is (already bracket format)
    # Plain "Verse 1" or "Chorus" headers get bracket-wrapped if detected
    normalized = []
    for line in chart_text.splitlines():
        stripped = line.strip()
        if not stripped:
            normalized.append('')
            continue
        # Already a bracket header. Genius adds singer credits —
        # "[Chorus: Brandon Lake & Chandler Moore, Both]" → "[Chorus]".
        if re.match(r'^\[.*\]$', stripped):
            normalized.append('[' + stripped[1:-1].split(':')[0].strip() + ']')
            continue
        # Plain section name → wrap in brackets
        if SECTION_NAME_RE.match(stripped):
            normalized.append(f'[{stripped.upper()}]')
            continue
        normalized.append(line)

    return {
        'title':      title,
        'artist':     artist,
        'key':        key,
        'chart_text': '\n'.join(normalized).strip(),
        'lyrics_only': True,  # hint to the UI that this is lyrics-only content
    }


# ── Generic lyrics-only sites ─────────────────────────────────────────────────

def parse_lyrics_generic(html: str) -> dict:
    """
    Generic parser for lyrics-only sites (AZLyrics, allchristiansongslyrics.com, etc.).
    Tries common patterns:
      1. div.lyrics / div#lyrics / div[class*="lyric"]
      2. Large <p> block of text
      3. Largest <div> with paragraph-like content
    Returns lyrics-only chart text.
    """
    # Title from og:title or h1
    title, artist = '', ''
    og_m = re.search(r'property="og:title" content="([^"]+)"', html)
    if og_m:
        ot = og_m.group(1).strip()
        # Try "Artist - Song" or "Song by Artist" patterns
        m = re.match(r'^(.*?)\s*[-–]\s*(.*?)(?:\s*Lyrics)?\s*$', ot)
        if m:
            # Heuristic: shorter part is usually the artist
            p1, p2 = m.group(1).strip(), m.group(2).strip()
            if len(p1) < len(p2):
                artist, title = p1, p2
            else:
                title, artist = p1, p2
    if not title:
        h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        title = _strip_html(h1_m.group(1)).strip() if h1_m else ''

    chart_text = ''

    # 1. Look for dedicated lyrics div
    for pat in [
        r'<div[^>]+(?:id|class)="[^"]*(?:lyrics?|song-text|lyric-body)[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]+(?:id|class)="[^"]*(?:song_content|song-content|verse)[^"]*"[^>]*>(.*?)</div>',
    ]:
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1)) > 100:
            text = re.sub(r'<br\s*/?>', '\n', m.group(1), flags=re.IGNORECASE)
            text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = html_mod.unescape(text).strip()
            if len(text) > 100:
                chart_text = text
                break

    # 2. Largest <p> block (some sites put all lyrics in one big paragraph)
    if not chart_text:
        paras = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
        if paras:
            best = max(paras, key=len)
            text = re.sub(r'<br\s*/?>', '\n', best, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = html_mod.unescape(text).strip()
            if len(text) > 100:
                chart_text = text

    # 3. Fallback: try pre block
    if not chart_text:
        pre_m = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL | re.IGNORECASE)
        if pre_m:
            chart_text = html_mod.unescape(re.sub(r'<[^>]+>', '', pre_m.group(1))).strip()

    # Normalize section headers
    normalized = []
    for line in chart_text.splitlines():
        stripped = line.strip()
        if re.match(r'^\[.*\]$', stripped):
            normalized.append(stripped)
        elif SECTION_NAME_RE.match(stripped):
            normalized.append(f'[{stripped.upper()}]')
        else:
            normalized.append(line)

    return {
        'title':      title,
        'artist':     artist,
        'key':        '',
        'chart_text': '\n'.join(normalized).strip(),
        'lyrics_only': True,
    }


# ── Generic fallback ───────────────────────────────────────────────────────────

def parse_generic(html: str) -> dict:
    """
    Try common chord chart patterns for unknown sites:
    1. Largest <pre> block
    2. <div> with class containing 'chord' or 'chart'
    """
    # Title from og:title or h1
    title_m = re.search(r'property="og:title" content="([^"]+)"', html)
    if not title_m:
        title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    title = _strip_html(title_m.group(1)).strip() if title_m else ''

    artist_m = re.search(r'property="og:description" content="([^"]+)"', html)
    artist = ''

    key = ''

    # Try pre blocks
    pre_blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL | re.IGNORECASE)
    if pre_blocks:
        chart = max(pre_blocks, key=len)
        chart = re.sub(r'<[^>]+>', '', chart)
        chart = html_mod.unescape(chart)
        if len(chart.strip()) > 50:
            return {'title': title, 'artist': artist, 'key': key, 'chart_text': chart.strip()}

    # Try chord/chart divs
    div_m = re.search(r'<div[^>]*class="[^"]*(?:chord|chart|lyric)[^"]*"[^>]*>(.*?)</div>',
                      html, re.DOTALL | re.IGNORECASE)
    if div_m:
        chart = re.sub(r'<[^>]+>', '', div_m.group(1))
        chart = html_mod.unescape(chart)
        if len(chart.strip()) > 50:
            return {'title': title, 'artist': artist, 'key': key, 'chart_text': chart.strip()}

    return {'title': title, 'artist': artist, 'key': key, 'chart_text': ''}


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def parse_page(url: str, html_content: str) -> dict:
    """Detect site from URL and dispatch to the appropriate parser."""
    site = detect_site(url)
    parsers = {
        'essentialworship':  parse_essentialworship,
        'worshiptogether':   parse_worshiptogether,
        'worshipchords_com': parse_worshipchords_com,
        'worshipchords_net': parse_worshipchords_net,
        'ultimate_guitar':   parse_ultimate_guitar,
        'genius':            parse_genius,
        'lyrics_generic':    parse_lyrics_generic,
        'generic':           parse_generic,
    }
    parser_fn = parsers.get(site, parse_generic)
    result = parser_fn(html_content)
    # Tabs → spaces before anything measures columns (a tab would otherwise
    # count as one column and misplace every chord after it). Tab stop 8,
    # same as ChordPro's a2crd.
    if result.get('chart_text'):
        result['chart_text'] = '\n'.join(l.expandtabs(8) for l in result['chart_text'].split('\n'))
    result['_site'] = site  # include site name for debugging
    # Ensure lyrics_only key always present (False for chord-chart sites)
    result.setdefault('lyrics_only', False)
    return result


# Keep the old name as an alias for backward compatibility
def parse_ew_page(html_content: str) -> dict:
    return parse_essentialworship(html_content)


# ── Generation ────────────────────────────────────────────────────────────────

def generate_pro(title: str, artist: str, chart_text: str,
                 target_key: str | None, output_dir: str | None,
                 lyrics_only: bool = False, source_key: str | None = None,
                 capo: int = 0):
    """Write a temp MD file and call md_to_pro.py to generate the .pro file."""
    md_content = convert_chart_to_md(chart_text, title, artist)

    fd, tmp_path = tempfile.mkstemp(suffix='.md', prefix='chord_chart_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(md_content)

        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'md_to_pro.py')
        # Same interpreter that's running us — the app's bundled Python, not
        # whatever "python3" happens to be on PATH.
        cmd = [sys.executable, script, tmp_path]
        if target_key and target_key.strip():
            cmd += ['--key', target_key.strip()]
        if source_key and source_key.strip():
            cmd += ['--source-key', source_key.strip()]
        if capo:
            cmd += ['--capo', str(capo)]
        if output_dir and output_dir.strip():
            cmd += ['--out', output_dir.strip()]
        if lyrics_only:
            cmd += ['--lyrics-only']

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end='')
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Universal chord chart → ProPresenter .pro converter')
    ap.add_argument('--url',        help='Chord chart page URL (EW, WorshipTogether, UG, etc.)')
    ap.add_argument('--chart-file', help='Path to plain-text chart file (user-edited)')
    ap.add_argument('--title',      default='', help='Song title (for --chart-file mode)')
    ap.add_argument('--artist',     default='', help='Artist name (for --chart-file mode)')
    ap.add_argument('--key',        help='Target (concert) key for transposition')
    ap.add_argument('--source-key', help='Key the chart\'s chord shapes are written in (skips detection)')
    ap.add_argument('--capo',       type=int, default=0,
                    help='Output capo: write chords as shapes for key − capo')
    ap.add_argument('--out',        help='Output directory for .pro file')
    ap.add_argument('--preview',     action='store_true',
                    help='Output JSON preview and exit (requires --url)')
    ap.add_argument('--lyrics-only', action='store_true',
                    help='Generate lyrics-only slides (no chord embedding)')
    args = ap.parse_args()

    # ── Mode 1: URL preview ───────────────────────────────────────
    if args.preview:
        if not args.url:
            print(json.dumps({'error': '--url is required for --preview mode'}))
            sys.exit(1)
        reason = unsupported_reason(args.url)
        if reason:
            print(json.dumps({'error': reason}))
            return
        try:
            html_content = fetch_html(args.url)
            data = parse_page(args.url, html_content)
            if not data['title'] and not data['chart_text'] and not data.get('error'):
                data['error'] = (
                    f'Could not parse page (site: {data.get("_site","unknown")}). '
                    'The site may be blocking or rendering client-side. '
                    f'HTML snippet: {html_content[:300]!r}'
                )
            print(json.dumps(data))
        except Exception as e:
            print(json.dumps({'error': str(e)}))
            sys.exit(1)
        return

    lyrics_only = getattr(args, 'lyrics_only', False)

    # ── Mode 2: Generate from URL ─────────────────────────────────
    if args.url and not args.chart_file:
        reason = unsupported_reason(args.url)
        if reason:
            print(reason, file=sys.stderr)
            sys.exit(1)
        try:
            html_content = fetch_html(args.url)
            data = parse_page(args.url, html_content)
        except Exception as e:
            print(f'Error fetching {args.url}: {e}', file=sys.stderr)
            sys.exit(1)
        # Lyrics-only sites always force lyrics_only mode
        effective_lyrics_only = lyrics_only or data.get('lyrics_only', False)
        # Site says capo → its chart is shapes for key − capo, so hand the
        # shapes key down; the key alone would be read as the shapes' key.
        src_key = data.get('key') or None
        site_capo = data.get('capo') or 0
        if src_key and site_capo:
            src_key = md_to_pro.shift_key(src_key, -site_capo)
        generate_pro(data['title'], data['artist'], data['chart_text'],
                     args.key or data.get('key') or None, args.out,
                     lyrics_only=effective_lyrics_only,
                     source_key=src_key, capo=args.capo)
        return

    # ── Mode 3: Generate from chart file (user-edited) ────────────
    if args.chart_file:
        try:
            with open(args.chart_file, 'r', encoding='utf-8') as f:
                chart_text = f.read()
        except Exception as e:
            print(f'Could not read chart file: {e}', file=sys.stderr)
            sys.exit(1)
        generate_pro(args.title, args.artist, chart_text, args.key, args.out,
                     lyrics_only=lyrics_only, source_key=args.source_key,
                     capo=args.capo)
        return

    ap.print_help()
    sys.exit(1)


if __name__ == '__main__':
    main()
