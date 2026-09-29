// ── Chart text helpers (song metadata, chart body, section headers) ─────────
// Pure functions shared by the app and the test suite (tests/ui_stage.ts).

export function parseSongMeta(mdContent: string): { title: string; artist: string } {
  const m = mdContent.match(/^title:\s*"([^"]+)"/m);
  if (!m) return { title: "", artist: "" };
  const parts = m[1].split("|").map(p => p.trim());
  const title = parts[0].replace(/\s*\|\s*chords.*/i, "").trim();
  const artist = parts[1] && !/^chords/i.test(parts[1]) ? parts[1] : "";
  return { title, artist };
}

/** Extract the chart body from an MD file for preview/editing.
 *  Tries the ``` code block first, then falls back to stripping frontmatter. */
/** Tabs → spaces (tab stop 8, like Python's expandtabs and ChordPro's
 *  a2crd) so a tab counts as the columns it looks like, not as one. */
export function expandTabs(text: string, tabStop = 8): string {
  return text.split("\n").map(line => {
    if (!line.includes("\t")) return line;
    let out = "";
    for (const ch of line) {
      out += ch === "\t" ? " ".repeat(tabStop - (out.length % tabStop)) : ch;
    }
    return out;
  }).join("\n");
}

export function extractChartBody(mdContent: string): string {
  return expandTabs(extractRawChartBody(mdContent));
}

function extractRawChartBody(mdContent: string): string {
  // Drop blank lines at the edges but keep the first line's indentation —
  // an indented chord line's leading spaces are its chord positions.
  const tidy = (t: string) => t.replace(/^(?:[ \t]*\r?\n)+/, "").trimEnd();
  const codeMatch = mdContent.match(/```[^\n]*\n([\s\S]*?)```/);
  if (codeMatch) return tidy(codeMatch[1]);
  // Fallback: strip YAML frontmatter and leading blank lines
  return tidy(mdContent.replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, ""));
}

/**
 * Normalise section headers in a chart body so the preview shows what
 * ProPresenter will actually receive, matching the Python parser's output.
 *
 * Rules (applied per line, non-indented lines only):
 *  [VERSE 1] / [chorus]     → [Verse 1] / [Chorus]   (bracket + title-case)
 *  First Verse / Second Chorus → [Verse 1] / [Chorus 2]  (ordinal words)
 *  Verse 1: / CHORUS        → [Verse 1] / [Chorus]   (named without brackets)
 */
export function normalizeChartHeaders(chart: string): string {
  const ORDINAL_MAP: Record<string, string> = {
    first:'1', second:'2', third:'3', fourth:'4', fifth:'5',
    sixth:'6', seventh:'7', eighth:'8', ninth:'9', tenth:'10',
  };
  const SECTION_WORDS =
    'intro|verse|chorus|pre[\\s\\-]?chorus|bridge|tag|outro|interlude|' +
    'instrumental|ending|coda|hook|turn|turnaround|transition|vamp|breakdown|refrain';
  const ORDINAL_RE = new RegExp(
    `^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\\s+(${SECTION_WORDS})\\s*:?\\s*$`,
    'i'
  );
  const NAMED_RE = new RegExp(
    `^(${SECTION_WORDS})\\s*(\\d*)\\s*:?\\s*$`,
    'i'
  );

  return chart.split('\n').map(line => {
    const trimmed = line.trim();
    if (!trimmed) return line;

    // Already bracketed: normalise capitalisation of first word, preserve number.
    // [VERSE 1] → [Verse 1],  [chorus] → [Chorus],  [Pre-Chorus] → [Pre-Chorus]
    const bracketM = trimmed.match(/^\[([^\]]+)\](.*)/);
    if (bracketM) {
      const parts = bracketM[1].trim().split(/\s+/);
      const label = parts[0].charAt(0).toUpperCase() + parts[0].slice(1).toLowerCase();
      const rest  = parts.slice(1).join(' ');
      return `[${rest ? `${label} ${rest}` : label}]${bracketM[2]}`;
    }

    // Section headers are never indented — skip indented lines.
    if (line[0] === ' ' || line[0] === '\t') return line;

    // Ordinal: "First Verse" → "[Verse 1]"
    const ordM = trimmed.match(ORDINAL_RE);
    if (ordM) {
      const num = ORDINAL_MAP[ordM[1].toLowerCase()];
      const sec = ordM[2].charAt(0).toUpperCase() + ordM[2].slice(1).toLowerCase();
      return `[${sec} ${num}]`;
    }

    // Named without brackets: "Verse 1:" / "CHORUS" → "[Verse 1]" / "[Chorus]"
    const namedM = trimmed.match(NAMED_RE);
    if (namedM) {
      const sec = namedM[1].charAt(0).toUpperCase() + namedM[1].slice(1).toLowerCase();
      const num = namedM[2] ? ` ${namedM[2]}` : '';
      return `[${sec}${num}]`;
    }

    return line;
  }).join('\n');
}

// ── Paste mode ──────────────────────────────────────────────────────────────

// Header/footer lines chord sites print around a chart (UG's print view:
// "Tuning: E A D G B E", "Capo: 3rd fret", "Key: Bb", "Page 1/3"). They carry
// key/capo info (read from the raw paste first) but must not become slides.
const PASTE_META_LINE =
  /^\s*(tuning|capo|key|difficulty|tempo|bpm|time( signature)?|strumming|author|chords? by|tabbed by|page \d+\s*(\/|of)\s*\d+)\b.*$/i;

// A section header the .pro builder recognises (md_to_pro.SECTION_NAME_RE and
// _ORDINAL_SECTION_RE): "[Verse 1]" anywhere, or a plain name at the start of
// the line ("Chorus:", "Verse 2", "First Verse") — indented names are lyrics.
const SECTION_NAMES =
  "intro|verse|chorus|pre[\\s-]?chorus|bridge|tag|outro|interlude|instrumental|ending|coda|hook|turn|turnaround|transition|vamp|breakdown|refrain";
const SECTION_LINE = new RegExp(
  `^(\\s*\\[[^\\]]+\\]|(?:(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\\s+)?(?:${SECTION_NAMES})\\s*\\d*\\s*:?)\\s*$`, "i");

export interface PastedChart {
  /** Chart ready for the preview (tabs expanded, junk dropped, sectioned). */
  chart: string;
  /** First real line before the chart, as a title suggestion ("" if none). */
  titleGuess: string;
  /** Artist from a "by …" line before the chart ("" if none). */
  artistGuess: string;
}

// cp1252 characters that stand in for bytes 0x80–0x9F when UTF-8 text is
// misread as Windows-1252 ("’" → "â€™").
const CP1252: Record<string, number> = {
  "€": 0x80, "‚": 0x82, "ƒ": 0x83, "„": 0x84, "…": 0x85, "†": 0x86, "‡": 0x87, "ˆ": 0x88,
  "‰": 0x89, "Š": 0x8a, "‹": 0x8b, "Œ": 0x8c, "Ž": 0x8e, "‘": 0x91, "’": 0x92, "“": 0x93,
  "”": 0x94, "•": 0x95, "–": 0x96, "—": 0x97, "˜": 0x98, "™": 0x99, "š": 0x9a, "›": 0x9b,
  "œ": 0x9c, "ž": 0x9e, "Ÿ": 0x9f,
};

/** Repair UTF-8 text that was misread as Latin-1/Windows-1252 somewhere
 *  along a copy-paste ("Iâ€™m" / "Iâm" → "I’m"). Only runs that look like
 *  mojibake are touched, and only if they decode as valid UTF-8. */
export function fixMojibake(text: string): string {
  return text.replace(/[\u00c2-\u00f4][\u0080-\u00bf\u0152-\u02dc\u2013-\u2122]{1,3}/g, run => {
    const bytes: number[] = [];
    for (const ch of run) {
      const code = ch.codePointAt(0)!;
      const b = code < 0x100 ? code : CP1252[ch];
      if (b === undefined) return run;
      bytes.push(b);
    }
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes));
    } catch {
      return run;
    }
  });
}

// Preamble lines that are page furniture, not a title: close buttons, lone
// letters/numbers, chord-diagram and strumming headings.
const NOT_A_TITLE = /^(x|×|✕|\d+|&|chords?|strumming( pattern)?|whole song.*|tabs?)$/i;

/** Tidy a chart pasted from a web page, PDF or document so it goes through the
 *  same pipeline as a fetched one. Lines before the first section header are
 *  treated as the page's preamble (title, artist, tuning…) — the .pro builder
 *  ignores them anyway — and a chart with no headers at all gets one, since
 *  otherwise it would produce no slides. */
export function preparePastedChart(raw: string): PastedChart {
  const lines = expandTabs(fixMojibake(raw).replace(/\r\n?/g, "\n").replace(/ /g, " ")).split("\n");
  const firstHeader = lines.findIndex(l => SECTION_LINE.test(l));
  const preamble = firstHeader > 0 ? lines.slice(0, firstHeader) : [];
  const body = (firstHeader >= 0 ? lines.slice(firstHeader) : lines)
    .filter(l => !PASTE_META_LINE.test(l));
  // Markdown links (from a clipper) → their text: "[Phil Wickham](url)" → "Phil Wickham".
  const plain = preamble.map(l => l.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").trim());
  const titleGuess = plain
    .find(l => l && !PASTE_META_LINE.test(l) && !NOT_A_TITLE.test(l) && !/^by\s/i.test(l) && l.length > 2)
    ?.replace(/\s+(official|chords?|tabs?|lyrics)\b.*$/i, "")
    .trim() ?? "";
  const artistGuess = plain.find(l => /^by\s+\S/i.test(l))?.replace(/^by\s+/i, "").trim() ?? "";
  const chart = body.join("\n").replace(/^(?:[ \t]*\n)+/, "").trimEnd();
  return {
    chart: firstHeader >= 0 ? chart : `[Verse]\n${chart}`,
    titleGuess,
    artistGuess,
  };
}
