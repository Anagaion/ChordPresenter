// Runs the app's URL-mode chart handling (what App.tsx's fetchEW does between
// the Python site parser and the Python .pro builder) so tests can check it
// without the UI. Reads JSON lines from stdin, one per page:
//   {"key": "...", "capo": 0, "chart_text": "..."}
// and writes one JSON line per input:
//   {"chartKey", "concertKey", "capo", "chart"}
// Run with: node tests/ui_stage.ts   (Node ≥ 23 strips the types itself)

import { createInterface } from "node:readline";
import { analyzeKey, toConcert } from "../src/music.ts";
import { normalizeChartHeaders } from "../src/chart.ts";

const rl = createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const d = JSON.parse(line);
  const chart: string = d.chart_text || "";
  const info = analyzeKey(chart, chart, d.key || "", d.capo ?? undefined);
  process.stdout.write(JSON.stringify({
    ...info,
    chart: normalizeChartHeaders(toConcert(chart, info)),
  }) + "\n");
}
