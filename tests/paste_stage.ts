// Runs the app's Paste-tab preparation (App.tsx usePastedChart) on stdin text
// and prints {chartKey, concertKey, capo, chart, titleGuess} as JSON.
import { analyzeKey, toConcert } from "../src/music.ts";
import { normalizeChartHeaders, preparePastedChart } from "../src/chart.ts";

const raw = await readStdin();
const { chart, titleGuess, artistGuess } = preparePastedChart(raw);
const info = analyzeKey(raw, chart);
process.stdout.write(JSON.stringify({ ...info, titleGuess, artistGuess, chart: normalizeChartHeaders(toConcert(chart, info)) }));

// Read all of stdin as a stream — reading fd 0 synchronously can hang on
// Windows pipes.
async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}
