// Runs the app's Paste-tab preparation (App.tsx usePastedChart) on stdin text
// and prints {chartKey, concertKey, capo, chart, titleGuess} as JSON.
import { readFileSync } from "node:fs";
import { analyzeKey, toConcert } from "../src/music.ts";
import { normalizeChartHeaders, preparePastedChart } from "../src/chart.ts";

const raw = readFileSync(0, "utf8");
const { chart, titleGuess, artistGuess } = preparePastedChart(raw);
const info = analyzeKey(raw, chart);
process.stdout.write(JSON.stringify({ ...info, titleGuess, artistGuess, chart: normalizeChartHeaders(toConcert(chart, info)) }));
