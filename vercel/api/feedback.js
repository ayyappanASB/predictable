// PREDICTABLE feedback API (Vercel serverless function)
// Author: Balasubramanian Ayyappan (3073JDDJ)
//
// POST /api/feedback  {name, email, category, message, website, context}
//   -> 201 {ok: true, id}           report saved as a PRIVATE file in Vercel Blob
//   -> 400 {ok: false, error}       invalid input (with a human-readable reason)
//   -> 429 {ok: false, error}       too many reports from one address
// GET  /api/feedback  -> 200 {ok: true}  (health check)
//
// Reports are private: only the owner's read-write token can download them
// (see sync-feedback.mjs, which copies them to the Mac).

import { randomBytes } from "node:crypto";
import { put } from "@vercel/blob";

export const LIMITS = { name: 80, email: 254, message: 2000, minMessage: 5, body: 10_000 };
export const CATEGORIES = ["bug", "idea", "praise", "other"];
const ALLOWED_ORIGINS = new Set([
  "https://predictable-pi.vercel.app",
  "https://ayyappanasb.github.io",
  "http://127.0.0.1:8765",
  "http://localhost:8765",
]);
const RATE = { max: 5, windowMs: 10 * 60 * 1000 };   // 5 reports per address per 10 minutes
const recent = new Map();                            // address -> [timestamps] (per warm instance)

/**
 * Remove control characters and surrounding spaces from a text field.
 * @param {unknown} value  raw value from the request body
 * @param {number} max     maximum length kept
 * @param {boolean} multiline  keep line breaks (for the message)
 * @returns {string} the cleaned text ("" if the value was not a string)
 */
export function clean(value, max, multiline = false) {
  if (typeof value !== "string") return "";
  const ctrl = multiline ? /[\u0000-\u0009\u000B\u000C\u000E-\u001F\u007F]/g : /[\u0000-\u001F\u007F]/g;
  return value.replace(ctrl, "").trim().slice(0, max);
}

/**
 * Check a feedback submission and build the record to store.
 * @param {object} body  parsed JSON body of the request
 * @returns {{ok: true, record: object} | {ok: false, error: string, spam?: boolean}}
 */
export function validate(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { ok: false, error: "Invalid request." };
  if (typeof body.website === "string" && body.website.trim() !== "") {
    return { ok: false, error: "Invalid request.", spam: true };       // honeypot field filled by a bot
  }
  const name = clean(body.name, LIMITS.name);
  const email = clean(body.email, LIMITS.email).toLowerCase();
  const message = clean(body.message, LIMITS.message, true);
  const category = CATEGORIES.includes(body.category) ? body.category : "other";
  if (!name) return { ok: false, error: "Please enter your name." };
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return { ok: false, error: "Please enter a valid email address." };
  if (message.length < LIMITS.minMessage) return { ok: false, error: "Please describe the issue (at least 5 characters)." };
  const ctx = body.context && typeof body.context === "object" ? body.context : {};
  const context = {};
  for (const key of ["layout", "level", "state", "score", "best", "runs", "scale", "page", "version"]) {
    if (ctx[key] !== undefined && ctx[key] !== null) context[key] = clean(String(ctx[key]), 60);
  }
  return { ok: true, record: { name, email, category, message, context } };
}

/**
 * True if `address` sent too many reports recently (and records this attempt).
 * @param {string} address  client IP address
 * @param {number} now      current time in ms (injectable for tests)
 */
export function rateLimited(address, now = Date.now()) {
  const times = (recent.get(address) || []).filter((t) => now - t < RATE.windowMs);
  if (times.length >= RATE.max) {
    recent.set(address, times);
    return true;
  }
  times.push(now);
  recent.set(address, times);
  return false;
}

/**
 * Short, human-friendly report id such as "K7Q2XD" (shown to the player).
 * @returns {string}
 */
export function reportId() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from(randomBytes(6), (b) => alphabet[b % alphabet.length]).join("");
}

/**
 * Build the request handler; `store` saves one report (injected so tests need no cloud).
 * @param {(pathname: string, json: string) => Promise<unknown>} store
 * @returns {(req: object, res: object) => Promise<void>} a Vercel Node.js handler
 */
export function createHandler(store) {
  return async function handler(req, res) {
    const origin = req.headers?.origin;
    if (origin && ALLOWED_ORIGINS.has(origin)) {
      res.setHeader("Access-Control-Allow-Origin", origin);
      res.setHeader("Vary", "Origin");
    }
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
    res.setHeader("Cache-Control", "no-store");
    if (req.method === "OPTIONS") return res.status(204).end();
    if (req.method === "GET") return res.status(200).json({ ok: true, service: "predictable-feedback" });
    if (req.method !== "POST") return res.status(405).json({ ok: false, error: "Method not allowed." });

    let body = req.body;
    try {
      if (typeof body === "string") body = JSON.parse(body);
    } catch {
      return res.status(400).json({ ok: false, error: "Invalid request." });
    }
    if (JSON.stringify(body ?? {}).length > LIMITS.body) {
      return res.status(413).json({ ok: false, error: "Report is too long." });
    }
    const result = validate(body);
    if (!result.ok) {
      // bots that fill the hidden field get a fake success so they do not retry
      if (result.spam) return res.status(201).json({ ok: true, id: "THANKS" });
      return res.status(400).json(result);
    }
    const address = String(req.headers?.["x-forwarded-for"] || "unknown").split(",")[0].trim();
    if (rateLimited(address)) {
      return res.status(429).json({ ok: false, error: "Too many reports - please try again in a few minutes." });
    }

    const id = reportId();
    const received = new Date().toISOString();
    const record = {
      id, received, ...result.record,
      userAgent: clean(String(req.headers?.["user-agent"] || ""), 300),
      country: clean(String(req.headers?.["x-vercel-ip-country"] || ""), 4),
    };
    const pathname = `feedback/${received.slice(0, 7)}/${received.replace(/[:.]/g, "-")}-${id}.json`;
    try {
      await store(pathname, JSON.stringify(record, null, 2));
    } catch (err) {
      console.error("feedback store failed", err);
      return res.status(500).json({ ok: false, error: "Could not save your report. Please try again." });
    }
    return res.status(201).json({ ok: true, id });
  };
}

/**
 * Save a report as a private JSON file in the project's Blob store.
 * @param {string} pathname  where to store it, e.g. feedback/2026-11/....json
 * @param {string} json      the report as JSON text
 */
async function blobStore(pathname, json) {
  return put(pathname, json, {
    access: "private", contentType: "application/json", addRandomSuffix: false,
  });
}

export default createHandler(blobStore);
