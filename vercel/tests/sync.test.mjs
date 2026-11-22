// Tests for the Mac sync helpers (CSV building and env parsing); no network needed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { csvCell, toCsv, readEnv } from "../sync-feedback.mjs";

test("csv cells with commas, quotes and new lines are quoted safely", () => {
  assert.equal(csvCell("plain"), "plain");
  assert.equal(csvCell('say "hi", ok'), '"say ""hi"", ok"');
  assert.equal(csvCell("two\nlines"), '"two\nlines"');
  assert.equal(csvCell(undefined), "");
});

test("csv lists newest report first and flattens game context", () => {
  const csv = toCsv([
    { received: "2026-11-01T10:00:00Z", id: "OLD", name: "A", email: "a@x.io", category: "bug", message: "m1", context: { layout: "desktop", level: "2" } },
    { received: "2026-11-02T10:00:00Z", id: "NEW", name: "B", email: "b@x.io", category: "idea", message: "m2", context: {} },
  ]).trim().split("\n");
  assert.match(csv[0], /^received,id,name,email,category,message,layout,level/);
  assert.match(csv[1], /,NEW,/);
  assert.match(csv[2], /,OLD,.*,desktop,2,/);
});

test("env file values are read without quotes", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "env-"));
  const file = path.join(dir, ".env");
  await writeFile(file, '# comment\nBLOB_READ_WRITE_TOKEN="abc_123"\nOTHER=x\n');
  const env = await readEnv(file);
  assert.equal(env.BLOB_READ_WRITE_TOKEN, "abc_123");
  assert.equal(env.OTHER, "x");
});
