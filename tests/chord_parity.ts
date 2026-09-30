// Answers chord questions with the app's code (src/music.ts) so
// tests/test_chord_parity.py can require the exact same answers from Python.
// stdin: {"tokens": [...], "lines": [...]}
// stdout: {"tokens": [quality|null, ...], "lines": [[[col, chord], ...]|null, ...],
//          "normalized": [...], "transposed": [...]}

import { chordQuality, scanChordLine, transposeChord } from "../src/music.ts";

const input = JSON.parse(await readStdin());
process.stdout.write(JSON.stringify({
  tokens: input.tokens.map((t: string) => chordQuality(t)),
  lines: input.lines.map((l: string) => scanChordLine(l)?.map(p => [p.col, p.chord]) ?? null),
  transposed: input.tokens.map((t: string) => transposeChord(t, 3, false)),
}));

// Read all of stdin as a stream — reading fd 0 synchronously can hang on
// Windows pipes.
async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}
