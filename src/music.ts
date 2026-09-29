// ── Keys, capo, and transposition ────────────────────────────────────────────
import grammar from "../scripts/chord_grammar.json" with { type: "json" };

// Mirrors the Python engine in scripts/md_to_pro.py (_detect_key,
// _detect_chart_key, shift_key, _key_idx, transpose_chord) so the key the UI
// shows, the chart it previews/prints, and the .pro it exports always agree.

// ── Chord grammar (shared with scripts/md_to_pro.py via chord_grammar.json) ──
// A chord is ROOT + quality + an extension known for that quality
// (+ bracketed additions like "(sus4)", "(b9)") + optional "/BASS".
// Same regex construction as md_to_pro.py — edit the JSON, not this code.

const FAMILIES = ["minor", "augmented", "diminished", "half_diminished", "major"] as const;
type ChordFamily = typeof FAMILIES[number];

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const alt = (items: string[], escape = true) =>
  [...items].sort((a, b) => b.length - a.length).map(i => (escape ? escapeRe(i) : i)).join("|");

const ROOT = `(?:${alt(grammar.roots)})`;
const QUALITY_BRANCHES = FAMILIES.map(fam =>
  `(?<q_${fam}>${alt(grammar.qualities[fam])})(?:${alt(grammar.extensions[fam])})`).join("|");
const BRACKETED = `(?:\\((?:${alt(grammar.bracketed_additions, false)})\\))*`;
const CHORD_RE = new RegExp(`^(?<root>${ROOT})(?:${QUALITY_BRANCHES})${BRACKETED}(?:/(?<bass>${ROOT}))?$`);
const NO_CHORD = new Set(grammar.no_chord);

// Non-chord tokens allowed on a chord line: bars, dashes, slashes (strum
// marks), dots, repeat marks. Same set as _FILLER_RE in md_to_pro.py.
const FILLER = /^(-+|\/+|\.+|%|\*+|x\d+|\d+x|\(x?\d+x?\))$/i;

/** Chord family of a token, "no_chord" for N.C., or null if not a chord. */
export function chordQuality(tok: string): ChordFamily | "no_chord" | null {
  if (NO_CHORD.has(tok)) return "no_chord";
  // A bare trailing dash is a connector ("C-Bb-Ab" walks down), not minor;
  // "-" means minor only with something after it ("C-7", "C-9").
  if (/^[A-G][#b]?-+(\/|$)/.test(tok)) return null;
  const g = tok.match(CHORD_RE)?.groups;
  if (!g) return null;
  return FAMILIES.find(fam => g[`q_${fam}`] !== undefined) ?? null;
}

export const isChordToken = (tok: string) => chordQuality(tok) !== null;

/** Read a line as a chord line: [{col, chord}] if every piece is a chord or
 *  filler (and there's at least one chord), else null. Mirrors
 *  md_to_pro.scan_chord_line: "|" separates, "(G)"/"G*" unwrap, "G-D" splits
 *  at dashes unless the whole token is a chord ("C-7" = C minor 7). */
export function scanChordLine(line: string): { col: number; chord: string }[] | null {
  const found: { col: number; chord: string }[] = [];
  for (const m of line.matchAll(/[^\s|]+/g)) {
    const tok = m[0];
    let col = m.index!;
    if (FILLER.test(tok)) continue;
    let core = tok.replace(/\*+$/, "");
    if (core.startsWith("(")) { core = core.slice(1); col += 1; }
    const opens = (core.match(/\(/g) || []).length;
    const closes = (core.match(/\)/g) || []).length;
    if (core.endsWith(")") && closes > opens) core = core.slice(0, -1);
    if (isChordToken(core)) { found.push({ col, chord: core }); continue; }
    const parts = [...core.matchAll(/[^-]+/g)];
    if (parts.length && parts.every(p => isChordToken(p[0]))) {
      parts.forEach(p => found.push({ col: col + p.index!, chord: p[0] }));
      continue;
    }
    return null;
  }
  return found.length ? found : null;
}

const ENH: Record<string, string> = {
  'C#':'Db','Db':'C#','D#':'Eb','Eb':'D#',
  'F#':'Gb','Gb':'F#','G#':'Ab','Ab':'G#','A#':'Bb','Bb':'A#',
};

const SHARPS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const FLATS  = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B'];
const NOTE_IDX: Record<string, number> = {
  C:0,'B#':0,'C#':1,Db:1,D:2,'D#':3,Eb:3,E:4,Fb:4,'E#':5,F:5,'F#':6,Gb:6,
  G:7,'G#':8,Ab:8,A:9,'A#':10,Bb:10,B:11,Cb:11,
};

// Conventional spelling per pitch class — used whenever a key is computed
// (B with capo 4 → G shapes) rather than picked by the user.
const MAJOR_SPELLING = ['C','Db','D','Eb','E','F','F#','G','Ab','A','Bb','B'];
const MINOR_SPELLING = ['Cm','C#m','Dm','Ebm','Em','Fm','F#m','Gm','G#m','Am','Bbm','Bm'];

// Keys that conventionally use flat spellings (matches _FLAT_KEYS in Python).
const FLAT_KEYS = new Set(['F','Bb','Eb','Ab','Db','Gb','Dm','Gm','Cm','Fm','Bbm','Ebm']);

export const MAJOR_KEYS = ['C','C#','Db','D','Eb','E','F','F#','Gb','G','Ab','A','Bb','B'];
export const MINOR_KEYS = ['Cm','C#m','Dm','D#m','Ebm','Em','Fm','F#m','Gm','G#m','Am','A#m','Bbm','Bm'];
const KEY_OPTIONS = new Set([...MAJOR_KEYS, ...MINOR_KEYS]);

const KEY_RE = /^([A-G][#b]?)(m(?!aj))?/;

export function isMinorKey(key: string): boolean {
  const m = key.trim().match(KEY_RE);
  return Boolean(m && m[2]);
}

function noteIdx(note: string): number {
  const m = note.trim().match(/^[A-G][#b]?/);
  const idx = m ? NOTE_IDX[m[0]] : undefined;
  if (idx === undefined) throw new Error(`Unknown note: ${note}`);
  return idx;
}

/** Map any key label onto one of the dropdown's options ("A#" → "Bb",
 *  "Gbm" → "F#m"), so a site's spelling never leaves the picker blank. */
export function canonicalKey(key: string): string {
  const k = key.trim();
  if (!k) return "";
  if (KEY_OPTIONS.has(k)) return k;
  try {
    const idx = noteIdx(k);
    return isMinorKey(k) ? MINOR_SPELLING[idx] : MAJOR_SPELLING[idx];
  } catch {
    return "";
  }
}

/** Pitch index of the key's RELATIVE MAJOR, so C and Am compare equal and
 *  picking Am for a song detected in C is a 0-semitone move. */
export function keyIdx(key: string): number {
  const idx = noteIdx(key);
  return isMinorKey(key) ? (idx + 3) % 12 : idx;
}

/** Move a key by N semitones, keeping its mode (G +4 → B, Em +4 → G#m). */
export function shiftKey(key: string, semitones: number): string {
  const idx = (((noteIdx(key) + semitones) % 12) + 12) % 12;
  return isMinorKey(key) ? MINOR_SPELLING[idx] : MAJOR_SPELLING[idx];
}

export function semitonesBetween(fromKey: string, toKey: string): number {
  return (((keyIdx(toKey) - keyIdx(fromKey)) % 12) + 12) % 12;
}

export function prefersFlats(key: string): boolean {
  return FLAT_KEYS.has(key);
}

export function transposeChord(chord: string, semitones: number, preferFlat: boolean): string {
  if (!semitones || !isChordToken(chord) || NO_CHORD.has(chord)) return chord;
  const m = chord.match(/^([A-G][#b]?)(.*?)(?:\/([A-G][#b]?))?$/);
  if (!m) return chord;
  const names = preferFlat ? FLATS : SHARPS;
  const move = (n: string) => { try { return names[(noteIdx(n) + semitones) % 12]; } catch { return n; } };
  const [, root, quality, bass] = m;
  return move(root) + quality + (bass ? "/" + move(bass) : "");
}

export function isChordLine(line: string): boolean {
  return scanChordLine(line.trim()) !== null;
}

/** Shrink runs of 2+ spaces in `gap` by up to `drift` characters (last run
 *  first), so text after it moves back toward its original column. */
function absorbDrift(gap: string, drift: number): string {
  while (drift > 0) {
    const i = gap.search(/ {2,}(?=[^ ]*$)/);
    if (i < 0) break;
    gap = gap.slice(0, i) + gap.slice(i + 1);
    drift--;
  }
  return gap;
}

/** Transpose every chord line in a chart, keeping each chord at its original
 *  column (so it stays over the same syllable) unless a longer name to its
 *  left pushes it right. Lyric and header lines are untouched. */
export function transposeChart(chart: string, semitones: number, preferFlat: boolean): string {
  if (!semitones) return chart;
  return chart.split("\n").map(line => {
    const pieces = scanChordLine(line);
    if (!pieces) return line;
    // Copy the line, swapping each chord in place. When a chord gets longer
    // (G → Ab) the spaces after it absorb the difference, so later chords keep
    // their column; bars, brackets and at least one space are kept.
    let out = "", last = 0;
    for (const { col, chord } of pieces) {
      out += absorbDrift(line.slice(last, col), out.length - last) + transposeChord(chord, semitones, preferFlat);
      last = col + chord.length;
    }
    return out + line.slice(last);
  }).join("\n");
}

// ── Capo ─────────────────────────────────────────────────────────────────────

// "Capo: 4th fret", "Capo 4", "# Capo 4", "Capo on fret 2", "Key: BCapo: 4th fret".
const CAPO_RE = /capo\b\s*:?\s*(?:on\s+)?(?:fret\s*)?(\d{1,2})/i;

export function detectCapo(text: string): number {
  const m = text.match(CAPO_RE);
  const n = m ? parseInt(m[1], 10) : 0;
  return n > 0 && n < 12 ? n : 0;
}

/** Drop standalone "Capo 4" / "# Capo: 4th fret" note lines from a chart —
 *  once the chart is converted to concert pitch they're wrong, and md_to_pro
 *  would otherwise turn one inside a section into a lyric slide. */
export function stripCapoLines(chart: string): string {
  return chart
    .split("\n")
    .filter(l => !/^\s*#?\s*capo\b.{0,30}$/i.test(l))
    .join("\n");
}

// ── Key detection ────────────────────────────────────────────────────────────

// Full 24-key diatonic chord sets using normalised chord names.
// Minor keys include both natural v and harmonic V (worship songs use either).
// Diminished (vii°) omitted — rare in contemporary worship charts.
const DIATONIC_CHORDS: Record<string, Set<string>> = {
  // Major keys
  C:   new Set(['C','Dm','Em','F','G','Am']),
  G:   new Set(['G','Am','Bm','C','D','Em']),
  D:   new Set(['D','Em','F#m','G','A','Bm']),
  A:   new Set(['A','Bm','C#m','D','E','F#m']),
  E:   new Set(['E','F#m','G#m','A','B','C#m']),
  B:   new Set(['B','C#m','D#m','E','F#','G#m']),
  'F#':new Set(['F#','G#m','A#m','B','C#','D#m']),
  F:   new Set(['F','Gm','Am','Bb','C','Dm']),
  Bb:  new Set(['Bb','Cm','Dm','Eb','F','Gm']),
  Eb:  new Set(['Eb','Fm','Gm','Ab','Bb','Cm']),
  Ab:  new Set(['Ab','Bbm','Cm','Db','Eb','Fm']),
  Db:  new Set(['Db','Ebm','Fm','Gb','Ab','Bbm']),
  // Minor keys
  Am:  new Set(['Am','C','Dm','Em','E','F','G']),
  Em:  new Set(['Em','G','Am','Bm','B','C','D']),
  Bm:  new Set(['Bm','D','Em','F#m','F#','G','A']),
  'F#m':new Set(['F#m','A','Bm','C#m','C#','D','E']),
  'C#m':new Set(['C#m','E','F#m','G#m','G#','A','B']),
  'G#m':new Set(['G#m','B','C#m','D#m','D#','E','F#']),
  Dm:  new Set(['Dm','F','Gm','Am','A','Bb','C']),
  Gm:  new Set(['Gm','Bb','Cm','Dm','D','Eb','F']),
  Cm:  new Set(['Cm','Eb','Fm','Gm','G','Ab','Bb']),
  Fm:  new Set(['Fm','Ab','Bbm','Cm','C','Db','Eb']),
  Bbm: new Set(['Bbm','Db','Ebm','Fm','F','Gb','Ab']),
};

/** Reduce chord to root + 'm' if minor (m, mi, min, -), else just root. */
function normChord(chord: string): string {
  const fam = chordQuality(chord);
  const root = chord.match(/^[A-G][#b]?/)?.[0];
  if (!root || fam === null || fam === "no_chord") return "";
  return root + (fam === "minor" ? "m" : "");
}

function chordVariants(norm: string): string[] {
  const isMinor = norm.endsWith('m');
  const root = isMinor ? norm.slice(0, -1) : norm;
  const suffix = isMinor ? 'm' : '';
  const twin = ENH[root];
  return twin ? [norm, twin + suffix] : [norm];
}

function keyFromChords(normChords: string[]): string {
  if (!normChords.length) return "";
  // Deduplicate preserving first-seen order
  const unique = [...new Map(normChords.map(c => [c, c])).values()];
  const first = unique[0];
  let bestKey = "C", bestScore = -1;
  for (const [key, diatonic] of Object.entries(DIATONIC_CHORDS)) {
    const score = unique.filter(c => chordVariants(c).some(v => diatonic.has(v))).length;
    if (score < bestScore) continue;
    if (score > bestScore) { bestScore = score; bestKey = key; continue; }
    // Tied — prefer key where first chord = tonic
    const newTonic = chordVariants(first).some(v => v === key);
    const curTonic = chordVariants(first).some(v => v === bestKey);
    if (newTonic && !curTonic) bestKey = key;
  }
  return bestKey;
}

/** Key the chord shapes in a chart body are written in ("" if no chords). */
function keyFromBody(body: string): string {
  const normChords: string[] = [];
  for (const line of body.split("\n")) {
    // Slash bass notes don't count, so "B/D#" scores only as B.
    for (const { chord } of scanChordLine(line.trim()) ?? []) {
      const n = normChord(chord.split("/")[0]);
      if (n) normChords.push(n);
    }
  }
  return keyFromChords(normChords);
}

// "Key: Am", "Key: BCapo: 4th fret" — keep a minor 'm' but not 'maj'.
const KEY_LINE_RE = /Key:\s*([A-G][#b]?)(m(?!aj))?/;

export interface KeyInfo {
  /** Key the chart's chord shapes are written in. */
  chartKey: string;
  /** Key the song actually sounds in (chartKey + capo). */
  concertKey: string;
  /** Capo the source chart was written for (0 = none). */
  capo: number;
}

/**
 * Work out the chart's written key, concert key, and capo.
 *
 * Sites (UG, and Obsidian clips of UG) label the CONCERT key: "Key: B, capo 4"
 * with G chord shapes. So when there's a capo, the shapes are key − capo —
 * unless the chords themselves already look like the labelled key, in which
 * case the site labelled the shapes and the concert key is key + capo.
 *
 * @param content  whole .md file or chart text (Key:/Capo: lines are read from it)
 * @param body     just the chord chart (for chord-based detection)
 * @param siteCapo capo the site reported (undefined = site doesn't report one)
 */
export function analyzeKey(content: string, body: string, siteKey = "", siteCapo?: number): KeyInfo {
  const keyLine = content.match(KEY_LINE_RE);
  const labelled = canonicalKey(siteKey || (keyLine ? keyLine[1] + (keyLine[2] || "") : ""));
  // A site that reports its capo (UG, WorshipChords.com) is trusted even when
  // it says 0; only when it doesn't say do we look for "Capo N" in the text.
  const capo = siteCapo !== undefined
    ? (siteCapo > 0 && siteCapo < 12 ? siteCapo : 0)
    : detectCapo(content);
  const chordKey = keyFromBody(body);

  if (labelled && capo) {
    if (chordKey && keyIdx(chordKey) === keyIdx(labelled)) {
      return { chartKey: labelled, concertKey: shiftKey(labelled, capo), capo };
    }
    return { chartKey: shiftKey(labelled, -capo), concertKey: labelled, capo };
  }
  if (labelled) return { chartKey: labelled, concertKey: labelled, capo: 0 };
  if (!chordKey) return { chartKey: "", concertKey: "", capo: 0 };
  return { chartKey: chordKey, concertKey: capo ? shiftKey(chordKey, capo) : chordKey, capo };
}

/** Rewrite a capo chart in concert pitch (G shapes + capo 4 → B chords). */
export function toConcert(chart: string, info: KeyInfo): string {
  if (!info.capo || !info.chartKey) return chart;
  return transposeChart(
    stripCapoLines(chart),
    semitonesBetween(info.chartKey, info.concertKey),
    prefersFlats(info.concertKey),
  );
}
