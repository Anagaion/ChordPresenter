// Answers chord questions with the app's code (src/music.ts) so
// tests/test_chord_parity.py can require the exact same answers from Python.
// stdin: {"tokens": [...], "lines": [...]}
// stdout: {"tokens": [quality|null, ...], "lines": [[[col, chord], ...]|null, ...],
//          "normalized": [...], "transposed": [...]}

import { readFileSync } from "node:fs";
import { chordQuality, scanChordLine, transposeChord } from "../src/music.ts";

const input = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({
  tokens: input.tokens.map((t: string) => chordQuality(t)),
  lines: input.lines.map((l: string) => scanChordLine(l)?.map(p => [p.col, p.chord]) ?? null),
  transposed: input.tokens.map((t: string) => transposeChord(t, 3, false)),
}));
