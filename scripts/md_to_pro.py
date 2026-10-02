#!/usr/bin/env python3
"""
md_to_pro.py — Convert Obsidian Clipper chord+lyrics MD files to ProPresenter .pro files.

Usage:
    python3 md_to_pro.py "path/to/Song Name.md"
    python3 md_to_pro.py --all    (process every .md in INBOX_DIR)

For each song produces two files in SONGS_OUTPUT_DIR:
    "Song - Artist - Vocals.pro"
    "Song - Artist - Vocals + Chords.pro"  ← Phase 2 (chords support coming)

Input format (EssentialWorship / Obsidian Clipper):
    YAML frontmatter with title field, then a ``` code block containing:
      [SECTION NAME] headers
      Chord lines  (only chord symbols, spaces, | / -)
      Lyric lines  (actual words)

Sections like INTRO, OUTRO, INSTRUMENTAL, TURN are skipped (no lyrics).
Sections with no lyric lines (e.g. [CHORUS 1] [x2] repeat markers) are also skipped.

Theme: DoubleThickTheme (TungstenNarrow-Bold, white text, two thick black lines).
"""

from __future__ import annotations

import re
import os
import sys

# ── Import slide/file building machinery from create_pro_song ──────────────
# All protobuf and RTF logic lives there.
sys.path.insert(0, os.path.dirname(__file__))
from create_pro_song import (
    build_slide, build_group, build_arrangement, build_pro_file,
    SONGS_OUTPUT_DIR,
)

# ────────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────────

INBOX_DIR = ""  # Set via --inbox flag or Preferences; do not hardcode

# Only skip guitar-tab sections — everything else (intro, outro, tag, interlude, turn)
# is handled: chord-only sections become blank stage-monitor slides, lyric sections
# become normal slides.
SKIP_SECTION_RE = re.compile(r'^tab$', re.IGNORECASE)

# Sentinel marking an explicit 2-line slide (used by ChordPresenter's Edit .pro
# mode when re-exporting an existing .pro's slides). U+E000 (Private Use Area)
# never appears in real lyric/chord text and \u2014 unlike U+2028/U+2029 \u2014 is NOT
# treated as a line boundary by str.splitlines(), so it survives intact
# through chart_text.splitlines() in ew_fetch.py's convert_chart_to_md() and
# body.splitlines() below. Any lyric line containing it is split back into
# the two original lines and kept on ONE slide, instead of falling through to
# the normal one-line-per-slide behaviour. Must match SLIDE_LINE_SEP in
# src/App.tsx's exportProChart.
SLIDE_LINE_SEP = '\ue000'

# Whitelist of recognised section names — works for any capitalisation and with or
# without a trailing colon (EssentialWorship, WorshipTogether, WorshipChords.com,
# E-Chords, Ultimate Guitar, WorshipChords.net all produce variants of these).
SECTION_NAME_RE = re.compile(
    r'^(intro|verse|chorus|pre[\s\-]?chorus|bridge|tag|outro|interlude|'
    r'instrumental|ending|coda|hook|turn|turnaround|transition|vamp|'
    r'breakdown|refrain)\s*\d*\s*:?\s*$',
    re.IGNORECASE
)

# Ordinal-word section headers: "First Verse", "Second Chorus", etc.
# WorshipChords.com uses this format instead of "Verse 1", "[VERSE 1]", etc.
_ORDINAL_TO_NUM = {
    'first': '1', 'second': '2', 'third': '3', 'fourth': '4',
    'fifth': '5', 'sixth': '6', 'seventh': '7', 'eighth': '8',
    'ninth': '9', 'tenth': '10',
}
_ORDINAL_SECTION_RE = re.compile(
    r'^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)'
    r'\s+(verse|chorus|bridge|tag|pre[\s\-]?chorus|intro|outro|interlude|vamp|refrain)'
    r'\s*:?\s*$',
    re.IGNORECASE
)

def _normalize_ordinal_section(name: str) -> str:
    """'First Verse' → 'Verse 1',  'Second Chorus' → 'Chorus 2', etc."""
    m = _ORDINAL_SECTION_RE.match(name.strip())
    if not m:
        return name.title()
    num     = _ORDINAL_TO_NUM[m.group(1).lower()]
    section = m.group(2).title()
    return f"{section} {num}"

# ────────────────────────────────────────────────────────────────
# CHORD / LYRIC LINE DETECTION
# ────────────────────────────────────────────────────────────────

# ── Chord grammar (shared with src/music.ts via chord_grammar.json) ──────────
# A chord is ROOT + quality + an extension known for that quality
# (+ bracketed additions like "(sus4)", "(b9)") + optional "/BASS".
# The lists live in chord_grammar.json so Python and the app can't drift apart.
import json as _json

def _load_chord_grammar():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chord_grammar.json'),
              encoding='utf-8') as f:
        return _json.load(f)

_GRAMMAR = _load_chord_grammar()

def _alt(items, escape=True):
    items = sorted(items, key=len, reverse=True)          # longest first
    return '|'.join(re.escape(i) if escape else i for i in items)

_ROOT = f'(?:{_alt(_GRAMMAR["roots"])})'
_QUALITY_BRANCHES = '|'.join(
    f'(?P<q_{fam}>{_alt(_GRAMMAR["qualities"][fam])})(?:{_alt(_GRAMMAR["extensions"][fam])})'
    for fam in ('minor', 'augmented', 'diminished', 'half_diminished', 'major')
)
_BRACKETED = f'(?:\\((?:{_alt(_GRAMMAR["bracketed_additions"], escape=False)})\\))*'
_CHORD_RE = re.compile(f'^(?P<root>{_ROOT})(?:{_QUALITY_BRANCHES}){_BRACKETED}(?:/(?P<bass>{_ROOT}))?$')
_NO_CHORD = set(_GRAMMAR['no_chord'])
_BARE_DASH_RE = re.compile(r'^[A-G][#b]?-+(/|$)')


def chord_quality(tok: str) -> str | None:
    """'minor' / 'major' / 'augmented' / 'diminished' / 'half_diminished' for a
    chord token, 'no_chord' for N.C., or None if it isn't a chord."""
    if tok in _NO_CHORD:
        return 'no_chord'
    # A bare trailing dash is a connector ("C-Bb-Ab" walks down), not minor;
    # "-" means minor only with something after it ("C-7", "C-9").
    if _BARE_DASH_RE.match(tok):
        return None
    m = _CHORD_RE.match(tok)
    if not m:
        return None
    for fam in ('minor', 'augmented', 'diminished', 'half_diminished', 'major'):
        if m.group(f'q_{fam}') is not None:
            return fam
    return None


def _is_chord_token(tok: str) -> bool:
    return chord_quality(tok) is not None


# Non-chord tokens allowed on a chord line: bars, dashes, slashes (strum
# marks), dots, repeat marks. Same set as CHORD_LINE_FILLER in src/music.ts.
_FILLER_RE = re.compile(r'^(-+|/+|\.+|%|\*+|x\d+|\d+x|\(x?\d+x?\))$', re.IGNORECASE)


def scan_chord_line(line: str):
    """Read a line as a chord line.

    Returns [(column, chord), …] if every piece of the line is a chord or
    filler and there's at least one chord; otherwise None. Columns are in the
    line as given (callers pass the raw, tab-expanded line). "|" always
    separates; "(G)" and "G*" are unwrapped; "G-D" is split at the dashes
    unless the whole token is a chord ("C-7" is C minor 7).
    """
    found = []
    for m in re.finditer(r'[^\s|]+', line):
        tok, col = m.group(), m.start()
        if _FILLER_RE.match(tok):
            continue
        core = tok
        if core.endswith('*'):
            core = core.rstrip('*')
        if core.startswith('('):
            core, col = core[1:], col + 1
        if core.endswith(')') and core.count(')') > core.count('('):
            core = core[:-1]
        if _is_chord_token(core):
            found.append((col, core))
            continue
        parts = [(pm.start(), pm.group()) for pm in re.finditer(r'[^-]+', core)]
        if parts and all(_is_chord_token(p) for _, p in parts):
            found.extend((col + off, p) for off, p in parts)
            continue
        return None
    return found or None


def is_chord_line(line: str) -> bool:
    """True if the line is chords (plus bars, dashes, repeat marks) only."""
    return scan_chord_line(line.strip()) is not None


def is_filler_line(line: str) -> bool:
    """A line of only bars/dashes/strum slashes and no chords ("| / / / |")."""
    toks = re.findall(r'[^\s|]+', line)
    return bool(line.strip()) and all(_FILLER_RE.match(t) for t in toks)

# Guitar-tab staff line: "e|--7--9--|", "B|-10-12-|(x4)", "|---5---|". UG
# "(Tab)" pages and tab snippets inside chord charts put these outside any
# [Tab] section; they're neither chords nor lyrics, so they're dropped.
_TAB_STAFF_RE = re.compile(r'^([A-Ga-g][#b]?\s*)?\|[-0-9hpbrx/\\~()|.*^\s]*-[-0-9hpbrx/\\~()|.*^\s]*$')

def is_tab_staff_line(line: str) -> bool:
    return bool(_TAB_STAFF_RE.match(line.strip()))

# A line of only dashes/equals/dots/underscores is a visual divider, not an
# empty chord line (which would become a blank slide).
_DIVIDER_RE = re.compile(r'^[-=._~*]{3,}$')

def is_divider_line(line: str) -> bool:
    return bool(_DIVIDER_RE.match(line.strip())) or is_filler_line(line)

# ────────────────────────────────────────────────────────────────
# DIATONIC KEY DETECTION  (chord-quality aware)
# ────────────────────────────────────────────────────────────────

# Enharmonic twin for normalisation checks.
_ENH = {
    'C#':'Db','Db':'C#','D#':'Eb','Eb':'D#',
    'F#':'Gb','Gb':'F#','G#':'Ab','Ab':'G#','A#':'Bb','Bb':'A#',
}

def _normalize_chord(chord: str) -> str:
    """
    Reduce a chord to root + 'm' (minor) or just root (everything else).
    Slash bass notes and all extensions are stripped. Minor means the
    grammar's minor family: m, mi, min, - (so Em7, Emi7, E-7 → 'Em').

    Examples:
        G, Gmaj7, Gsus4, G7, G/B  → 'G'
        Em, Em7, Em7sus4, E-7      → 'Em'
        F#m, F#m7                  → 'F#m'
    """
    fam = chord_quality(chord)
    m = re.match(r'^([A-G][#b]?)', chord)
    if not m or fam in (None, 'no_chord'):
        return ''
    return m.group(1) + ('m' if fam == 'minor' else '')

def _chord_variants(norm: str) -> tuple:
    """Return (norm, enharmonic-twin) for set-membership checks."""
    is_minor = norm.endswith('m')
    root = norm[:-1] if is_minor else norm
    suffix = 'm' if is_minor else ''
    twin = _ENH.get(root, '')
    return (norm, twin + suffix) if twin else (norm,)

# Full 24-key diatonic chord sets — major keys I ii iii IV V vi,
# minor keys i III iv v V VI VII  (both natural-v and harmonic-V included
# since worship songs use either depending on the song).
# Diminished (vii°) omitted — rare in contemporary worship charts.
_DIATONIC_CHORDS: dict = {
    # ── Major keys ────────────────────────────────────────────────
    'C':  {'C','Dm','Em','F','G','Am'},
    'G':  {'G','Am','Bm','C','D','Em'},
    'D':  {'D','Em','F#m','G','A','Bm'},
    'A':  {'A','Bm','C#m','D','E','F#m'},
    'E':  {'E','F#m','G#m','A','B','C#m'},
    'B':  {'B','C#m','D#m','E','F#','G#m'},
    'F#': {'F#','G#m','A#m','B','C#','D#m'},
    'F':  {'F','Gm','Am','Bb','C','Dm'},
    'Bb': {'Bb','Cm','Dm','Eb','F','Gm'},
    'Eb': {'Eb','Fm','Gm','Ab','Bb','Cm'},
    'Ab': {'Ab','Bbm','Cm','Db','Eb','Fm'},
    'Db': {'Db','Ebm','Fm','Gb','Ab','Bbm'},
    # ── Minor keys ───────────────────────────────────────────────
    'Am': {'Am','C','Dm','Em','E','F','G'},
    'Em': {'Em','G','Am','Bm','B','C','D'},
    'Bm': {'Bm','D','Em','F#m','F#','G','A'},
    'F#m':{'F#m','A','Bm','C#m','C#','D','E'},
    'C#m':{'C#m','E','F#m','G#m','G#','A','B'},
    'G#m':{'G#m','B','C#m','D#m','D#','E','F#'},
    'Dm': {'Dm','F','Gm','Am','A','Bb','C'},
    'Gm': {'Gm','Bb','Cm','Dm','D','Eb','F'},
    'Cm': {'Cm','Eb','Fm','Gm','G','Ab','Bb'},
    'Fm': {'Fm','Ab','Bbm','Cm','C','Db','Eb'},
    'Bbm':{'Bbm','Db','Ebm','Fm','F','Gb','Ab'},
}

def _key_from_chords(norm_chords: list) -> str:
    """
    Return the key (major or minor) whose diatonic chord set has the most
    matches against the normalised chord list.

    Tiebreaks (in order):
    1. The key whose tonic chord name equals the first chord in the song.
       (Songs very often start on the I/i chord — 'G' starts on G, 'Am'
       starts on Am.)
    2. Keep the earlier key in dict order (stable).

    Using chord quality (major vs minor root) means, e.g., Gm correctly
    scores for Bb major / G minor but NOT for C major — better signal than
    root-only matching.
    """
    if not norm_chords:
        return 'Unknown'
    unique = list(dict.fromkeys(norm_chords))  # deduplicate, preserve order
    first = unique[0]

    best_key, best_score = 'C', -1
    for key, diatonic in _DIATONIC_CHORDS.items():
        score = sum(
            1 for c in unique
            if any(v in diatonic for v in _chord_variants(c))
        )
        if score < best_score:
            continue
        if score > best_score:
            best_score = score
            best_key = key
            continue
        # Tied — tiebreak on first chord being the tonic.
        new_tonic = any(v == key for v in _chord_variants(first))
        cur_tonic = any(v == best_key for v in _chord_variants(first))
        if new_tonic and not cur_tonic:
            best_key = key
    return best_key


def _chord_root(chord: str) -> str:
    """Extract the root note (kept for use in other parts of the module)."""
    m = re.match(r'^([A-G][#b]?)', chord)
    return m.group(1) if m else ''


# ────────────────────────────────────────────────────────────────
# RAW-MD BODY EXTRACTOR  (for sites with no ``` code block)
# ────────────────────────────────────────────────────────────────

def _extract_raw_md_body(raw: str) -> str:
    """
    Extract the chord chart body from a clipped MD file that has no ``` code block.
    Used for sites like WorshipTogether where Obsidian Clipper produces plain MD.

    Strategy:
      1. Strip YAML frontmatter, markdown images, markdown links, and ATX headers.
      2. Find the first line that matches a known section name (e.g. "Intro", "Verse 1").
      3. Return everything from that point onward, filtering out "REPEAT …" directives.
    """
    # Remove YAML frontmatter block
    raw = re.sub(r'^---\s*\n.*?\n---\s*\n', '', raw, flags=re.DOTALL | re.MULTILINE)
    # Remove markdown images: ![alt](url)
    raw = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', raw)
    # Remove markdown links entirely — navigation elements like "[Free chord pro download](#)"
    raw = re.sub(r'\[[^\]]*\]\([^)]*\)', '', raw)
    # Remove ATX headers: ## Title
    raw = re.sub(r'^#{1,6}\s+.*$', '', raw, flags=re.MULTILINE)

    lines = raw.splitlines()

    # Find the first recognised section header; everything before it is navigation junk.
    chart_start = None
    for i, line in enumerate(lines):
        if SECTION_NAME_RE.match(line.strip()):
            chart_start = i
            break

    if chart_start is None:
        # Could not find a section header — return cleaned content as-is and hope for the best.
        return raw

    chart_lines = lines[chart_start:]
    # Filter "REPEAT …" directives (WorshipTogether uses "REPEAT CHORUS" etc.)
    result = [l for l in chart_lines
              if not re.match(r'^REPEAT\s+', l.strip(), re.IGNORECASE)]
    return '\n'.join(result)


# ────────────────────────────────────────────────────────────────
# MD PARSER
# ────────────────────────────────────────────────────────────────

def parse_md_song(filepath: str):
    """
    Parse an EssentialWorship Obsidian Clipper .md file.

    Returns:
        title    : str  — song title (without artist)
        artist   : str  — artist name (may be empty)
        sections : list of (section_name, [lyric_line, ...])
                   Each lyric_line is one slide (strings only — no tuples).
                   Chord lines, instrumental sections, and empty repeat-markers
                   are all stripped out.
        chord_map: list of (section_name, [(lyric_line, {char_pos: chord_name})])
                   Parallel to sections, with chord position data for Phase 2.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()

    # ── Extract title and artist from YAML frontmatter ──────────
    title, artist = '', ''
    title_match = re.search(r'^title:\s*"([^"]+)"', raw, re.MULTILINE)
    if title_match:
        parts = [p.strip() for p in title_match.group(1).split('|')]
        # Format: "Song Name | Artist | Chords + Lyrics"
        if len(parts) >= 1:
            title = parts[0].strip()
        if len(parts) >= 2:
            candidate = parts[1].strip()
            # If the second part looks like the suffix rather than a real artist, skip it
            if not re.match(r'^chords', candidate, re.IGNORECASE):
                artist = candidate
        # Strip " | Chords + Lyrics" suffix from title if it leaked in
        title = re.sub(r'\s*\|\s*chords.*$', '', title, flags=re.IGNORECASE).strip()

    if not title:
        title = os.path.splitext(os.path.basename(filepath))[0]

    # ── Extract code block content ───────────────────────────────
    code_match = re.search(r'```\s*\n(.*?)```', raw, re.DOTALL)
    if code_match:
        body = code_match.group(1)
    else:
        # No code block — site like WorshipTogether outputs plain MD.
        # Extract the chord chart by stripping navigation and finding the first section.
        body = _extract_raw_md_body(raw)

    # ── Walk lines, building sections ────────────────────────────
    sections = []        # [(name, [lyric_lines])]
    chord_map = []       # [(name, [(lyric, {pos: chord})])]

    cur_name        = None
    cur_lines       = []   # lyric lines for current section
    cur_chords      = []   # (lyric, {pos: chord}) pairs for current section
    cur_chord_lines = []   # chord-only lines (for instrumental sections)
    pending_chord_line = None

    def flush():
        nonlocal cur_name, cur_lines, cur_chords, cur_chord_lines, pending_chord_line
        if cur_name is not None:
            if cur_lines:
                # Normal lyric section
                if not SKIP_SECTION_RE.match(cur_name):
                    sections.append((cur_name, list(cur_lines)))
                    chord_map.append((cur_name, list(cur_chords)))
            elif cur_chord_lines:
                # Chord-only section (Intro, Outro, Interlude, Tag, etc.)
                # Lyric text = spaces matching chord line length → blank on audience
                # screen, but chord indicators sit at correct positions on stage monitor.
                chord_slides      = []
                chord_slide_data  = []
                for cl in cur_chord_lines:
                    positions  = _map_chord_positions(cl, cl)
                    # Spaces keep the lyric field non-empty (so RTF renders)
                    # but invisible — audience sees a blank slide.
                    lyric_text = ' ' * max((len(cl.rstrip())), 1)
                    chord_slides.append(lyric_text)
                    chord_slide_data.append((lyric_text, positions))
                if chord_slides:
                    sections.append((cur_name, chord_slides))
                    chord_map.append((cur_name, chord_slide_data))
        cur_name        = None
        cur_lines       = []
        cur_chords      = []
        cur_chord_lines = []
        pending_chord_line = None

    for raw_line in body.splitlines():
        raw_line = raw_line.expandtabs(8)   # tabs → spaces before any column work
        stripped = raw_line.strip()

        # ── Section header: bracket format [VERSE 1], [Chorus], etc. ────
        header_match = re.match(r'^\[([^\]]+)\]', stripped)
        if header_match:
            flush()
            raw_name = header_match.group(1).strip()
            # Strip repeat qualifiers like "(x2)" or "x2" at the end
            raw_name = re.sub(r'\s*x\d+\s*$', '', raw_name, flags=re.IGNORECASE).strip()
            cur_name = raw_name.title()   # "VERSE 1" → "Verse 1"
            pending_chord_line = None
            continue

        # ── Section header: ordinal word format ──────────────────────
        # "First Verse", "Second Chorus", etc. (WorshipChords.com style).
        # Must come before SECTION_NAME_RE so these lines don't fall through
        # to lyric parsing.
        if stripped and not raw_line[0].isspace() and _ORDINAL_SECTION_RE.match(stripped):
            flush()
            cur_name = _normalize_ordinal_section(stripped)
            pending_chord_line = None
            continue

        # ── Section header: known name without brackets ───────────────
        # Handles WorshipChords.com ("Verse 1"), E-Chords ("Intro:"),
        # WorshipTogether ("VERSE 1"), EW plain style, and more.
        # Only match non-indented lines so chord-alignment spaces don't interfere.
        if stripped and not raw_line[0].isspace() and SECTION_NAME_RE.match(stripped):
            flush()
            clean_name = re.sub(r':?\s*$', '', stripped)   # strip trailing colon
            cur_name = clean_name.strip().title()
            pending_chord_line = None
            continue

        if cur_name is None:
            continue

        if not stripped:
            pending_chord_line = None
            continue

        # ── Skip "REPEAT CHORUS" / "REPEAT VERSE" directives ─────────
        if re.match(r'^REPEAT\s+', stripped, re.IGNORECASE):
            continue

        # ── Skip guitar-tab staff lines (e|--7--|) and dividers (-----) ──
        # A line starting with a bar that isn't a chord line ("| p  pull-off",
        # a tab legend) is never sung — keep it off the slides.
        if is_tab_staff_line(stripped) or is_divider_line(stripped) or \
                (stripped.startswith('|') and not is_chord_line(stripped)):
            pending_chord_line = None
            continue

        if is_chord_line(stripped):
            # Keep the chord line's leading spaces: they're what put a chord
            # over the right syllable. (Stripping them used to slide every
            # indented chord line to the start of the lyric.)
            pending_chord_line = raw_line.rstrip()
            cur_chord_lines.append(stripped)
            continue

        # It's a lyric line
        # Pair with the pending chord line for chord position mapping. Columns
        # are measured from where the lyric text starts, since the slide gets
        # the stripped lyric.
        chord_positions = {}
        if pending_chord_line is not None:
            lyric_indent = len(raw_line) - len(raw_line.lstrip())
            chord_positions = _map_chord_positions(pending_chord_line, stripped, lyric_indent)
            pending_chord_line = None

        # ── Explicit 2-line slide sentinel (ChordPresenter Edit .pro mode) ──
        # Bypasses the dash/comma heuristics below entirely — the two lines
        # are already known-good and must land on the same slide untouched.
        if SLIDE_LINE_SEP in stripped:
            parts = [p.strip() for p in stripped.split(SLIDE_LINE_SEP) if p.strip()]
            if len(parts) >= 2:
                slide_entry = (parts[0], parts[1])
            elif parts:
                slide_entry = parts[0]
            else:
                continue
            cur_lines.append(slide_entry)
            cur_chords.append((slide_entry if isinstance(slide_entry, str)
                               else f"{slide_entry[0]} {slide_entry[1]}",
                               chord_positions))
            continue

        # Normalize chord-alignment spaces (e.g. "gave   me   one  more   day" → clean)
        # Squeeze runs of spaces to one — and move each chord with its text,
        # or every chord after a gap would land too far right (chord positions
        # were measured on the unsqueezed line).
        lyric_clean, chord_positions = _squeeze_spaces(stripped, chord_positions)

        # ── Dash rule: "An - other" → "Another" ─────────────────────────────
        # Worship charts use " - " to mark sustained syllable breaks within words.
        # Simply remove the dash and join the syllables.
        # Edge cases like "no - one" → "noone" are rare and can be fixed in preview.
        # Syllable dashes ("A - maz - ing") are removed to rejoin the word;
        # chords over a removed dash move to the start of the next syllable.
        lyric_clean, chord_positions = _remove_spans(
            lyric_clean, [m.span() for m in re.finditer(r'\s+-\s+', lyric_clean)], chord_positions)

        # Comma rule: "phrase one, phrase two" → 2-line slide with hard RTF break.
        # Delete the comma; each phrase becomes its own line within one slide.
        # Only split when the part BEFORE the comma has at least 4 words.
        # e.g. "My God, You're..." (2 words) → no split
        #      "Fire in His eyes, healing..." (4 words) → split
        comma_m = re.search(r',\s+', lyric_clean)
        part1_words = len(lyric_clean[:comma_m.start()].split()) if comma_m else 0
        if comma_m and part1_words >= 4:
            part1 = lyric_clean[:comma_m.start()].strip()
            part2 = lyric_clean[comma_m.end():].strip()
            slide_entry = (part1, part2)

            # Adjust chord positions: those before the comma stay; those in part2
            # shift left by (comma position + separator length - 1 newline char).
            part2_orig_start = comma_m.end()   # where part2 begins in original
            part2_rtf_start  = len(part1) + 1  # where part2 begins in combined RTF text
            adjusted = {}
            for pos, chord in chord_positions.items():
                if pos < comma_m.start():
                    adjusted[pos] = chord                          # in part1, no change
                else:
                    new_pos = pos - part2_orig_start + part2_rtf_start
                    adjusted[max(0, new_pos)] = chord              # in part2, shifted
            chord_positions = adjusted
        else:
            slide_entry = lyric_clean

        cur_lines.append(slide_entry)
        cur_chords.append((slide_entry if isinstance(slide_entry, str)
                           else f"{slide_entry[0]} {slide_entry[1]}",
                           chord_positions))

    flush()

    return title, artist, sections, chord_map


def _squeeze_spaces(text: str, positions: dict) -> tuple:
    """Collapse runs of spaces to one, remapping {char_pos: chord} to the
    squeezed text. A chord over a removed space moves to the next kept
    character; none end up past the last character or share a position."""
    out, new_index, prev_space = [], [], False
    for ch in text:
        new_index.append(len(out))
        if ch == ' ' and prev_space:
            continue
        out.append(ch)
        prev_space = ch == ' '
    squeezed = ''.join(out)
    if not positions:
        return squeezed, positions
    last = len(squeezed) - 1
    items = sorted(positions.items())
    cols = [new_index[pos] if pos < len(new_index) else last for pos, _ in items]
    return squeezed, _spread_positions(cols, [c for _, c in items], last)


def _remove_spans(text: str, spans: list, positions: dict) -> tuple:
    """Delete the given (start, end) spans from text, remapping chord
    positions: a chord inside a removed span moves to the next kept
    character; no two chords end up sharing one."""
    if not spans:
        return text, positions
    out, new_index, cut = [], [], iter(sorted(spans))
    span = next(cut, None)
    for i, ch in enumerate(text):
        while span and i >= span[1]:
            span = next(cut, None)
        new_index.append(len(out))
        if span and span[0] <= i < span[1]:
            continue
        out.append(ch)
    result = ''.join(out)
    if not positions:
        return result, positions
    items = sorted(positions.items())
    last = len(result) - 1
    cols = [new_index[pos] if pos < len(new_index) else last for pos, _ in items]
    return result, _spread_positions(cols, [c for _, c in items], last)


def _spread_positions(cols: list, chords: list, last: int) -> dict:
    """Place chords (in order) on character positions 0..last as close to
    their columns as possible, never sharing one: clamp, push collisions
    right, then pull anything past the end back left. If there are more
    chords than characters, the last ones are kept."""
    if last < 0 or not chords:
        return {}
    cols, chords = cols[-(last + 1):], chords[-(last + 1):]
    pos = [min(max(c, 0), last) for c in cols]
    for i in range(1, len(pos)):
        pos[i] = max(pos[i], pos[i - 1] + 1)
    pos[-1] = min(pos[-1], last)
    for i in range(len(pos) - 2, -1, -1):
        pos[i] = min(pos[i], pos[i + 1] - 1)
    return dict(zip(pos, chords))


def _map_chord_positions(chord_line: str, lyric_line: str, lyric_indent: int = 0) -> dict:
    """
    Given a chord line and the lyric line beneath it, return a dict of
    {char_position_in_lyric: chord_name} for Phase 2 chord embedding.

    chord_line keeps its original leading spaces; lyric_indent is how many
    leading spaces the (already stripped) lyric_line had, so columns line up.

    Example:
        chord_line = "       C/E    Dm   C    Bb    F/A"
        lyric_line = "'Cause You gave   me   one  more   day"
        → {7: 'C/E', 14: 'Dm', 19: 'C', 24: 'Bb', 30: 'F/A'}
    """
    # Find each chord token and its position in the chord line. "|" and an
    # opening "(" are separators, so "|(G)" and "(D)" are found too.
    # N.C. marks a chord line but isn't a chord ProPresenter can show, so it's
    # not written to the slide (same as before v1.2).
    found = [(max(0, col - lyric_indent), chord)
             for col, chord in (scan_chord_line(chord_line) or [])
             if chord not in _NO_CHORD]

    # A chord can only sit on a character of the lyric. Chords before it
    # starts (lead-in chords) or past its end (a chord after the last word)
    # get pulled onto it, and two chords must never share a character or one
    # overwrites the other. So: clamp, push collisions right, then pull
    # anything past the end back left — every chord stays, in order, as close
    # to its real column as the lyric allows.
    return _spread_positions([c for c, _ in found], [ch for _, ch in found], len(lyric_line) - 1)


# ────────────────────────────────────────────────────────────────
# TRANSPOSITION ENGINE
# ────────────────────────────────────────────────────────────────

# Chromatic scale in sharps; flat spellings mapped to their sharp equivalents.
_CHROMATIC   = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_FLAT_TO_SHARP = {'Db':'C#','Eb':'D#','Fb':'E','Gb':'F#','Ab':'G#','Bb':'A#','Cb':'B'}
_SHARP_TO_FLAT = {'C#':'Db','D#':'Eb','F#':'Gb','G#':'Ab','A#':'Bb'}

# Keys that conventionally use flat spellings.
_FLAT_KEYS = {'F','Bb','Eb','Ab','Db','Gb','Dm','Gm','Cm','Fm','Bbm','Ebm'}

def _note_idx(note: str) -> int:
    # Accept key labels like "G#m", "Bbm" — use only the root note portion.
    root_only = re.match(r'^[A-G][#b]?', note.strip())
    note = root_only.group() if root_only else note
    note = _FLAT_TO_SHARP.get(note, note)
    return _CHROMATIC.index(note)

def _idx_note(idx: int, prefer_flat: bool) -> str:
    note = _CHROMATIC[idx % 12]
    if prefer_flat:
        note = _SHARP_TO_FLAT.get(note, note)
    return note

_KEY_RE = re.compile(r'^([A-G][#b]?)(m(?!aj))?')

# Conventional spelling for each pitch class (used when a key is computed,
# e.g. B with capo 4 → G shapes, rather than chosen by the user).
_MAJOR_SPELLING = ['C','Db','D','Eb','E','F','F#','G','Ab','A','Bb','B']
_MINOR_SPELLING = ['Cm','C#m','Dm','Ebm','Em','Fm','F#m','Gm','G#m','Am','Bbm','Bm']

def _is_minor_key(key: str) -> bool:
    m = _KEY_RE.match(key.strip())
    return bool(m and m.group(2))

def _key_idx(key: str) -> int:
    """Pitch index of a key's RELATIVE MAJOR, so a major/minor pair that share
    a key signature compare equal: C == Am, G == Em. Picking Am as the target
    for a song detected in C is then a 0-semitone move, not +9 (C → A major)."""
    idx = _note_idx(key)
    return (idx + 3) % 12 if _is_minor_key(key) else idx

def shift_key(key: str, semitones: int) -> str:
    """Move a key label by N semitones, keeping its mode (G +4 → B, Em +4 → G#m)."""
    idx = (_note_idx(key) + semitones) % 12
    return (_MINOR_SPELLING if _is_minor_key(key) else _MAJOR_SPELLING)[idx]

def transpose_chord(chord: str, semitones: int, prefer_flat: bool = False) -> str:
    """
    Transpose a chord name by the given number of semitones.
    Handles slash chords (C/E), qualities (m, maj7, sus2, dim, aug, …), and N.C.
    """
    if chord in ('N.C.', 'NC') or semitones == 0:
        return chord
    m = re.match(r'^([A-G][#b]?)(.*?)(?:/([A-G][#b]?))?$', chord)
    if not m:
        return chord
    root, quality, bass = m.group(1), m.group(2), m.group(3)
    try:
        new_root = _idx_note((_note_idx(root) + semitones) % 12, prefer_flat)
    except ValueError:
        return chord
    if bass:
        try:
            new_bass = _idx_note((_note_idx(bass) + semitones) % 12, prefer_flat)
            return f"{new_root}{quality}/{new_bass}"
        except ValueError:
            pass
    return f"{new_root}{quality}"

def transpose_chord_map(chord_map, semitones: int, prefer_flat: bool):
    """Apply transposition to every chord name in the full chord_map."""
    if semitones == 0:
        return chord_map
    result = []
    for sec_name, pairs in chord_map:
        new_pairs = []
        for lyric, positions in pairs:
            new_pos = {p: transpose_chord(c, semitones, prefer_flat)
                       for p, c in positions.items()}
            new_pairs.append((lyric, new_pos))
        result.append((sec_name, new_pairs))
    return result

# "Key: Am", "Key: BCapo: 4th fret" (UG clip, no space) — keep the minor 'm'
# but not the 'm' of 'maj'.
_KEY_LINE_RE = re.compile(r'Key:\s*([A-G][#b]?)(m(?!aj))?')

# "Capo: 4th fret", "Capo 4", "# Capo 4", "Capo on fret 2", "capo 3rd".
_CAPO_RE = re.compile(r'capo\b\s*:?\s*(?:on\s+)?(?:fret\s*)?(\d{1,2})', re.IGNORECASE)

def _detect_capo(text: str) -> int:
    m = _CAPO_RE.search(text)
    n = int(m.group(1)) if m else 0
    return n if 0 < n < 12 else 0

def _detect_chart_key(filepath: str) -> tuple:
    """Return (chart_key, concert_key, capo) for a standalone .md file.

    chart_key is the key the written chord SHAPES are in; concert_key is what
    the song actually sounds in. They differ only when the chart says capo.
    Sites (UG, Obsidian clips of UG) label the CONCERT key — "Key: B, Capo 4"
    with G shapes — so the shapes are Key − capo. If the chords themselves
    already look like the labelled key, the site labelled the shapes instead.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()
    capo = _detect_capo(raw)
    labelled = _KEY_LINE_RE.search(raw)
    detected = _detect_key(filepath)
    if not capo or not labelled or detected == 'Unknown':
        return detected, (shift_key(detected, capo) if capo and detected != 'Unknown' else detected), capo
    # _detect_key returned the label; compare with what the chords say.
    code = re.search(r'```\s*\n(.*?)```', raw, re.DOTALL)
    chord_key = _key_from_body(code.group(1) if code else _extract_raw_md_body(raw))
    if chord_key != 'Unknown' and _key_idx(chord_key) == _key_idx(detected):
        return detected, shift_key(detected, capo), capo
    return shift_key(detected, -capo), detected, capo

def _detect_key(filepath: str) -> str:
    """Return the original key of the chart.

    Priority order:
    1. Explicit ``Key: X`` line anywhere in the file — highest confidence.
       Handles UG/Obsidian clippings like ``Key: BCapo: 4th fret`` (missing
       space) by matching only the note root + optional accidental.
    2. Diatonic matching — collect every chord root from every chord line in
       the chart and find the major key whose scale contains the most of them.
       More robust than "first chord" because most songs have many chord lines
       and the tonic chord appears far more often than any other.
    3. Fallback: 'Unknown' (only if no chord lines exist at all, e.g. a pure
       lyrics file — key doesn't matter in that case anyway).
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()

    # Priority 1: explicit Key: field.
    key_match = _KEY_LINE_RE.search(raw)
    if key_match:
        return key_match.group(1) + (key_match.group(2) or '')

    # Get chart body.
    code = re.search(r'```\s*\n(.*?)```', raw, re.DOTALL)
    body = code.group(1) if code else _extract_raw_md_body(raw)
    return _key_from_body(body)


def _key_from_body(body: str) -> str:
    """Chord-quality diatonic matching over the whole chart body."""
    # Slash bass notes don't count ("B/D#" contributes only B — the bass would
    # otherwise skew detection, e.g. make G#m look better than B major).
    norm_chords = []
    for line in body.splitlines():
        for _, chord in scan_chord_line(line.strip()) or []:
            norm_chords.append(_normalize_chord(chord.split('/')[0]))
    norm_chords = [c for c in norm_chords if c]  # drop empty strings (N.C.)

    return _key_from_chords(norm_chords)  # returns 'Unknown' if list is empty


# ────────────────────────────────────────────────────────────────
# .PRO FILE BUILDER  (single output file with chords embedded)
# ────────────────────────────────────────────────────────────────

def capo_note(capo: int, concert_key: str, shapes_key: str) -> str:
    """Stage-display note for the first slide when chords are capo shapes."""
    return (f"CAPO {capo} - chords are {shapes_key} shapes (sounds in {concert_key}).\n"
            f"No capo / electric / keys: play in {concert_key}.")


def build_song_pro(title: str, artist: str, sections, chord_map,
                   lyrics_only: bool = False, first_slide_notes: str | None = None):
    """
    Build a single .pro file with lyrics + optionally embedded chords.
    Automatically prepends 2 blank slides in an "Opening" group so the operator
    has space to add media backgrounds, audience look, etc.

    lyrics_only=True  → plain lyric slides only, no chord data on stage monitor.
    lyrics_only=False → current behaviour: chords embedded for stage monitor display.

    Returns binary .pro content.
    """
    # Prepend 2 blank slides as an "Opening" section
    blank_section  = [("Opening", ["", ""])]
    blank_chords   = [("Opening", [("", {}), ("", {})])]
    all_sections   = blank_section + list(sections)
    all_chord_map  = blank_chords  + list(chord_map)

    if lyrics_only:
        # No chord data — all dicts empty, produces clean lyric-only slides
        chord_data = [(sec_name, [{} for _ in pairs]) for sec_name, pairs in all_chord_map]
    else:
        chord_data = []
        for sec_name, lyric_chord_pairs in all_chord_map:
            chord_dicts = [chords for _, chords in lyric_chord_pairs]
            chord_data.append((sec_name, chord_dicts))

    # Notes go on the first Opening slide: stage display only, never audience.
    slide_notes = {0: first_slide_notes} if first_slide_notes else None
    return build_pro_file(title, all_sections, arrangement_name="DoubleThickTheme",
                          chord_data=chord_data, slide_notes=slide_notes)


# ────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """Replace characters that are illegal or dangerous in macOS/Windows filenames."""
    # / is the main culprit (path separator); others are cautionary
    return re.sub(r'[/\\:*?"<>|]', '-', name).strip(' -')


def process_file(filepath: str, target_key: str = None, output_dir: str = None,
                 lyrics_only: bool = False, source_key: str = None, capo: int = 0):
    """
    target_key : CONCERT key to output in (default: the song's concert key).
    source_key : key the chart's chord shapes are written in. ChordPresenter
                 always passes this (it has already converted capo charts to
                 concert pitch), so detection here can't disagree with the UI.
                 Omitted on the CLI → detected from the file, including any
                 "Capo N" note.
    capo       : output capo. Chords are written as shapes for (target − capo)
                 and the first slide gets a stage-display note saying so.
    """
    print(f"\nProcessing: {os.path.basename(filepath)}")

    title, artist, sections, chord_map = parse_md_song(filepath)
    display_name = _safe_filename(f"{title} - {artist}" if artist else title)

    if source_key:
        chart_key, concert_key, src_capo = source_key, source_key, 0
    else:
        chart_key, concert_key, src_capo = _detect_chart_key(filepath)
        if src_capo:
            print(f"  Source chart: capo {src_capo} ({chart_key} shapes, concert {concert_key})")

    capo = capo if (capo and not lyrics_only and 0 < capo < 12) else 0
    key = target_key or concert_key
    shapes_key = key

    try:
        if capo:
            shapes_key = shift_key(key, -capo)
        semitones = (_key_idx(shapes_key) - _key_idx(chart_key)) % 12
        if semitones:
            prefer_flat = shapes_key in _FLAT_KEYS
            chord_map = transpose_chord_map(chord_map, semitones, prefer_flat)
            print(f"  Transposing: {chart_key} → {shapes_key} ({semitones:+d} semitones)")
        print(f"  Key: {key}" + (f" (capo {capo}, {shapes_key} shapes)" if capo else ""))
    except ValueError as e:
        print(f"  WARNING: Could not transpose ({e}); using original key {chart_key}")
        key, shapes_key, capo = chart_key, chart_key, 0

    notes = capo_note(capo, key, shapes_key) if capo else None

    mode_tag = " [lyrics only]" if lyrics_only else ""
    print(f"  Title:  {title}{mode_tag}")
    print(f"  Artist: {artist or '(none)'}")
    for sname, lines in sections:
        print(f"  [{sname}] {len(lines)} slides")

    out_dir = output_dir or SONGS_OUTPUT_DIR
    if not out_dir or not out_dir.strip():
        raise ValueError(
            "No output folder configured. Open Preferences in ChordPresenter and set an Output folder."
        )
    os.makedirs(out_dir, exist_ok=True)

    # Single output file: "Title - Artist - Key.pro"  (or "Title - Key.pro" if no artist).
    # Lyrics-only slides carry no chords, so no key ("… - Unknown.pro" before).
    capo_tag    = f" (Capo {capo})" if capo else ""
    key_tag     = "" if lyrics_only or not key or key == 'Unknown' else f" - {key}"
    file_name   = f"{display_name}{key_tag}{capo_tag}.pro"
    file_path   = os.path.join(out_dir, file_name)
    song_data   = build_song_pro(display_name, artist, sections, chord_map,
                                  lyrics_only=lyrics_only, first_slide_notes=notes)

    with open(file_path, 'wb') as f:
        f.write(song_data)

    total = sum(len(ls) for _, ls in sections)
    print(f"  → {file_name}")
    print(f"     {total} slides, {len(song_data):,} bytes")


def main():
    args = sys.argv[1:]

    # Parse optional --key TARGET, --out DIR, --lyrics-only flags
    target_key  = None
    source_key  = None
    capo        = 0
    output_dir  = None
    lyrics_only = False
    filtered = []
    i = 0
    while i < len(args):
        if args[i] == '--key' and i + 1 < len(args):
            target_key = args[i + 1]; i += 2
        elif args[i] == '--source-key' and i + 1 < len(args):
            source_key = args[i + 1]; i += 2
        elif args[i] == '--capo' and i + 1 < len(args):
            capo = int(args[i + 1]); i += 2
        elif args[i] == '--out' and i + 1 < len(args):
            output_dir = args[i + 1]; i += 2
        elif args[i] == '--lyrics-only':
            lyrics_only = True; i += 1
        else:
            filtered.append(args[i]); i += 1
    args = filtered

    if '--all' in args:
        all_files = sorted(
            f for f in os.listdir(INBOX_DIR)
            if f.endswith('.md') and 'Chords + Lyrics' in f
        )
        # Deduplicate: prefer base filename over "(1)" / "(2)" variants
        seen = {}
        for fname in all_files:
            key_fname = re.sub(r'\s*\(\d+\)(?=\.md$)', '', fname)
            if key_fname not in seen:
                seen[key_fname] = fname
        md_files = [os.path.join(INBOX_DIR, f) for f in seen.values()]
        if not md_files:
            print(f"No chord+lyrics MD files found in {INBOX_DIR}")
            return
        for fp in sorted(md_files):
            try:
                process_file(fp, target_key=target_key, output_dir=output_dir,
                             lyrics_only=lyrics_only, capo=capo)
            except Exception as e:
                print(f"  ERROR: {e}")
    elif args:
        for fp in args:
            process_file(fp, target_key=target_key, output_dir=output_dir,
                         lyrics_only=lyrics_only, source_key=source_key, capo=capo)
    else:
        print("Usage:")
        print("  python3 md_to_pro.py 'path/to/song.md'")
        print("  python3 md_to_pro.py 'path/to/song.md' --key G")
        print("  python3 md_to_pro.py 'path/to/song.md' --key B --capo 4   (G shapes)")
        print("  python3 md_to_pro.py --all")
        print("  python3 md_to_pro.py --all --key Bb --out /path/to/output")
        sys.exit(1)


if __name__ == '__main__':
    main()
