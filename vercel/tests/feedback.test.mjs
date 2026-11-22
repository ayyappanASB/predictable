// Tests for the feedback API (no cloud needed: the store is replaced by a fake).
// Run: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHandler, validate, clean, rateLimited, reportId } from "../api/feedback.js";

/** Minimal fake of Vercel's response object; records status and JSON body. */
function fakeRes() {
  const res = { statusCode: 0, body: null, headers: {} };
  res.setHeader = (k, v) => { res.headers[k] = v; };
  res.status = (c) => { res.statusCode = c; return res; };
  res.json = (b) => { res.body = b; return res; };
  res.end = () => res;
  return res;
}
const good = { name: "Asha", email: "Asha@Example.com", category: "bug",
  message: "The D-pad stopped responding on level 3.", context: { layout: "portrait", level: 3 } };
let ip = 0;
/** A request from a fresh address, so rate limiting does not interfere between tests. */
const req = (body, extra = {}) => ({ method: "POST", body, headers: { "x-forwarded-for": `10.0.0.${++ip}`, ...extra } });

test("valid report is stored privately and gets a short id", async () => {
  const saved = [];
  const res = fakeRes();
  await createHandler(async (p, json) => saved.push([p, JSON.parse(json)]))(req(good, { origin: "https://ayyappanasb.github.io" }), res);
  assert.equal(res.statusCode, 201);
  assert.match(res.body.id, /^[A-Z2-9]{6}$/);
  assert.equal(saved.length, 1);
  const [path, rec] = saved[0];
  assert.match(path, /^feedback\/\d{4}-\d{2}\/.+\.json$/);
  assert.equal(rec.email, "asha@example.com");
  assert.equal(rec.context.layout, "portrait");
  assert.equal(res.headers["Access-Control-Allow-Origin"], "https://ayyappanasb.github.io");
});

test("each invalid field gives a clear message and stores nothing", async () => {
  for (const [patch, text] of [[{ name: "  " }, "name"], [{ email: "nope" }, "email"], [{ message: "hi" }, "describe"]]) {
    const saved = [];
    const res = fakeRes();
    await createHandler(async (...a) => saved.push(a))(req({ ...good, ...patch }), res);
    assert.equal(res.statusCode, 400);
    assert.match(res.body.error, new RegExp(text, "i"));
    assert.equal(saved.length, 0);
  }
});

test("honeypot bots get a fake success and nothing is stored", async () => {
  const saved = [];
  const res = fakeRes();
  await createHandler(async (...a) => saved.push(a))(req({ ...good, website: "http://spam" }), res);
  assert.equal(res.statusCode, 201);
  assert.equal(saved.length, 0);
});

test("oversized, non-JSON and wrong-method requests are rejected", async () => {
  const h = createHandler(async () => {});
  let res = fakeRes();
  await h(req({ ...good, message: "x".repeat(20000) }), res);
  assert.equal(res.statusCode, 413);
  res = fakeRes();
  await h(req("{not json"), res);
  assert.equal(res.statusCode, 400);
  res = fakeRes();
  await h({ method: "DELETE", headers: {} }, res);
  assert.equal(res.statusCode, 405);
  res = fakeRes();
  await h({ method: "GET", headers: {} }, res);
  assert.equal(res.statusCode, 200);
});

test("more than 5 reports in 10 minutes from one address is rate limited", () => {
  const t0 = 1_000_000;
  for (let i = 0; i < 5; i++) assert.equal(rateLimited("1.2.3.4", t0 + i), false);
  assert.equal(rateLimited("1.2.3.4", t0 + 10), true);
  assert.equal(rateLimited("1.2.3.4", t0 + 11 * 60 * 1000), false);   // window passed
});

test("store failure returns 500 with a friendly message", async () => {
  const res = fakeRes();
  await createHandler(async () => { throw new Error("down"); })(req(good), res);
  assert.equal(res.statusCode, 500);
  assert.match(res.body.error, /try again/);
});

test("cleaning removes control characters and limits length; unknown category -> other", () => {
  assert.equal(clean(" a\u0000b\nc ", 10), "abc");
  assert.equal(clean("line1\nline2", 20, true), "line1\nline2");
  assert.equal(clean(42, 5), "");
  const v = validate({ ...good, category: "hack", context: { level: 4, evil: "x" } });
  assert.equal(v.record.category, "other");
  assert.deepEqual(Object.keys(v.record.context), ["level"]);
  assert.notEqual(reportId(), reportId());
});
