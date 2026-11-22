// Copy PREDICTABLE feedback reports from the private Vercel Blob store to this Mac.
// Author: Balasubramanian Ayyappan (3073JDDJ)
//
//   node sync-feedback.mjs            download new reports (also run every 5 min by launchd)
//
// Output:  ~/PREDICTABLE Feedback/   (kept out of iCloud-synced Documents: iCloud can move files
//                                     to the cloud, and background jobs cannot read them back)
//            reports/<date>-<id>.json   one file per report (never overwritten)
//            feedback.csv               all reports, newest first (opens in Numbers / Excel)
// The secret read-write token is read from ~/.predictable/feedback.env (mode 600).

import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { execFile } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { get, list } from "@vercel/blob";

const HOME = os.homedir();
const TOKEN_FILE = path.join(HOME, ".predictable", "feedback.env");
export const OUT_DIR = process.env.PREDICTABLE_FEEDBACK_DIR || path.join(HOME, "PREDICTABLE Feedback");
const REPORTS = path.join(OUT_DIR, "reports");
const COLUMNS = ["received", "id", "name", "email", "category", "message", "layout", "level", "state", "page", "country", "userAgent"];

/**
 * Read KEY=value lines from an env file (quotes removed).
 * @param {string} file  path of the env file
 * @returns {Promise<Record<string, string>>}
 */
export async function readEnv(file) {
  const env = {};
  for (const line of (await readFile(file, "utf8")).split("\n")) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*"?(.*?)"?\s*$/);
    if (m) env[m[1]] = m[2];
  }
  return env;
}

/**
 * Quote one value for CSV (Excel/Numbers friendly).
 * @param {unknown} value  cell value
 * @returns {string}
 */
export function csvCell(value) {
  const s = value === undefined || value === null ? "" : String(value);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/**
 * Build the CSV text for all reports, newest first.
 * @param {object[]} reports  parsed report records
 * @returns {string}
 */
export function toCsv(reports) {
  const rows = [...reports].sort((a, b) => String(b.received).localeCompare(String(a.received)));
  const lines = [COLUMNS.join(",")];
  for (const r of rows) {
    const flat = { ...r, ...(r.context || {}) };
    lines.push(COLUMNS.map((c) => csvCell(flat[c])).join(","));
  }
  return lines.join("\n") + "\n";
}

/**
 * Show a macOS notification (ignored if notifications are unavailable).
 * @param {string} title  notification title
 * @param {string} text   notification body
 */
function notify(title, text) {
  const esc = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  execFile("osascript", ["-e", `display notification "${esc(text)}" with title "${esc(title)}"`], () => {});
}

/**
 * Download every report that is not on this Mac yet, then rebuild feedback.csv.
 * @returns {Promise<number>} how many new reports were downloaded
 */
export async function sync() {
  const env = await readEnv(TOKEN_FILE);
  const token = env.BLOB_READ_WRITE_TOKEN;
  if (!token) throw new Error(`BLOB_READ_WRITE_TOKEN missing in ${TOKEN_FILE}`);
  await mkdir(REPORTS, { recursive: true });

  const fresh = [];
  let cursor;
  do {
    const page = await list({ prefix: "feedback/", cursor, token });
    for (const blob of page.blobs) {
      const file = path.join(REPORTS, path.basename(blob.pathname));
      if (existsSync(file)) continue;                     // already on this Mac
      const got = await get(blob.pathname, { access: "private", token, useCache: false });
      if (!got) continue;
      const text = await new Response(got.stream).text();
      JSON.parse(text);                                   // only keep valid JSON
      await writeFile(file, text, { mode: 0o600 });
      fresh.push(JSON.parse(text));
    }
    cursor = page.hasMore ? page.cursor : undefined;
  } while (cursor);

  const all = [];
  for (const name of (await readdir(REPORTS)).filter((n) => n.endsWith(".json"))) {
    try { all.push(JSON.parse(await readFile(path.join(REPORTS, name), "utf8"))); } catch { /* skip broken file */ }
  }
  await writeFile(path.join(OUT_DIR, "feedback.csv"), toCsv(all), { mode: 0o600 });

  const stamp = new Date().toISOString();
  console.log(`${stamp}  ${fresh.length} new, ${all.length} total -> ${OUT_DIR}`);
  if (fresh.length) {
    const first = fresh[0];
    notify("PREDICTABLE feedback", fresh.length === 1
      ? `${first.name} (${first.category}): ${first.message.slice(0, 80)}`
      : `${fresh.length} new reports - see the PREDICTABLE Feedback folder`);
  }
  return fresh.length;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  sync().catch((err) => { console.error(new Date().toISOString(), "sync failed:", err.message); process.exit(1); });
}
