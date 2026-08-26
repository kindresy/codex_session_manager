import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import * as app from "../public/app.js";
import { escapeHtml, formatTimestamp, matchSession, renderItems } from "../public/app.js";

const metadata = {
  id: "session-42",
  question: "Fix cloud sync",
  cwd: "/Work/Cloud",
  created_at: 1,
  updated_at: 2,
};

test("matchSession searches session metadata case-insensitively", () => {
  assert.equal(matchSession(metadata, "CLOUD SYNC"), true);
  assert.equal(matchSession(metadata, "work/cloud"), true);
  assert.equal(matchSession(metadata, "SESSION-42"), true);
  assert.equal(matchSession(metadata, "   "), true);
  assert.equal(matchSession(metadata, "missing"), false);
});

test("shortSessionId returns the first eight characters for session cards", () => {
  assert.equal(typeof app.shortSessionId, "function");
  assert.equal(app.shortSessionId("1234567890abcdef"), "12345678");
  assert.equal(app.shortSessionId("1234567🚀tail"), "1234567🚀");
  assert.equal(app.shortSessionId("short"), "short");
});

test("escapeHtml escapes every HTML-significant character", () => {
  assert.equal(
    escapeHtml(`<script data-x="'">&</script>`),
    "&lt;script data-x=&quot;&#39;&quot;&gt;&amp;&lt;/script&gt;",
  );
});

test("renderItems preserves turn and item chronology while escaping content", () => {
  const html = renderItems([
    { items: [{ type: "user", text: "<first>" }, { type: "assistant", text: "second & safe" }] },
    {
      items: [
        { type: "command", command: "echo <third>", cwd: "/tmp", status: "done", output: "ok", exit_code: 0 },
        { type: "file_change", path: "<fourth>.js", kind: "update", diff: "+ code" },
      ],
    },
  ]);

  const markers = ["&lt;first&gt;", "second &amp; safe", "echo &lt;third&gt;", "&lt;fourth&gt;.js"];
  assert.ok(markers.every((marker, index) => html.indexOf(marker) > (index ? html.indexOf(markers[index - 1]) : -1)));
  assert.doesNotMatch(html, /<first>|<third>|<fourth>/);
});

test("renderItems expands messages and collapses commands and file changes", () => {
  const html = renderItems([
    {
      items: [
        { type: "user", text: "question" },
        { type: "assistant", text: "answer" },
        { type: "command", command: "pwd", cwd: "/tmp", status: "done", output: "/tmp", exit_code: 0 },
        { type: "file_change", path: "a.js", kind: "create", diff: "+a" },
      ],
    },
  ]);

  assert.match(html, /<article class="message user">/);
  assert.match(html, /<article class="message assistant">/);
  assert.match(html, /<details class="activity command">/);
  assert.match(html, /<details class="activity file-change">/);
  assert.doesNotMatch(html, /<details[^>]*\sopen(?:\s|>)/);
});

test("formatTimestamp accepts Unix seconds and handles absent values", () => {
  assert.equal(formatTimestamp(null), "Unknown time");
  assert.equal(formatTimestamp(Number.MAX_VALUE), "Unknown time");
  assert.notEqual(formatTimestamp(0), "Unknown time");
});

test("validSessionIndex accepts only schema 1 indexes with a sessions array", () => {
  assert.equal(typeof app.validSessionIndex, "function");
  assert.equal(app.validSessionIndex({ schema_version: 1, sessions: [] }), true);
  assert.equal(app.validSessionIndex({ schema_version: 2, sessions: [] }), false);
  assert.equal(app.validSessionIndex({ schema_version: 1, sessions: {} }), false);
  assert.equal(app.validSessionIndex(null), false);
});

test("sessionListFromIndex rejects invalid successful responses before state replacement", () => {
  assert.equal(typeof app.sessionListFromIndex, "function");
  const sessions = [{ id: "kept" }];
  assert.equal(app.sessionListFromIndex({ schema_version: 1, sessions }), sessions);
  assert.throws(() => app.sessionListFromIndex({ schema_version: 2, sessions }), /invalid_index/);
  assert.throws(() => app.sessionListFromIndex({ schema_version: 1, sessions: {} }), /invalid_index/);
});

test("requestJson identifies unauthorized responses and sends the bearer token", async () => {
  assert.equal(typeof app.requestJson, "function");
  let request;
  const fetcher = async (path, options) => {
    request = { path, options };
    return new Response('{"error":"unauthorized"}', {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  };

  await assert.rejects(
    app.requestJson(fetcher, "bad-token", "/api/sessions"),
    (error) => error.status === 401 && error.message === "unauthorized",
  );
  assert.equal(request.options.headers.get("Authorization"), "Bearer bad-token");
});

test("isMobileLayout follows a supplied media query without browser globals", () => {
  assert.equal(typeof app.isMobileLayout, "function");
  assert.equal(app.isMobileLayout({ matches: true }), true);
  assert.equal(app.isMobileLayout({ matches: false }), false);
  assert.equal(app.isMobileLayout(undefined), false);
});

test("browser startup wires mobile history, accessibility, and unauthorized token reset", async () => {
  const publicDirectory = new URL("../public/", import.meta.url);
  const source = await readFile(new URL("app.js", publicDirectory), "utf8");
  const html = await readFile(new URL("index.html", publicDirectory), "utf8");
  const css = await readFile(new URL("app.css", publicDirectory), "utf8");

  assert.match(source, /history\.pushState\s*\(/);
  assert.match(source, /addEventListener\(["']popstate["']/);
  assert.match(source, /history\.back\s*\(/);
  assert.match(source, /\.inert\s*=/);
  assert.match(source, /setAttribute\(["']aria-hidden["']/);
  assert.match(source, /removeAttribute\(["']aria-hidden["']/);
  assert.match(source, /\.focus\s*\(/);
  assert.match(source, /localStorage\.removeItem\(TOKEN_KEY\)/);
  assert.match(source, /error\.status\s*===\s*401/);
  assert.match(html, /id="session-pane"/);
  assert.match(html, /id="token-error"[^>]*aria-live="assertive"/);
  assert.doesNotMatch(css, /\.detail-pane\.detail-open\s*~\s*\*/);
});

test("manifest has install metadata and the service worker bypasses APIs", async () => {
  const publicDirectory = new URL("../public/", import.meta.url);
  const manifest = JSON.parse(await readFile(new URL("manifest.webmanifest", publicDirectory), "utf8"));
  assert.ok(manifest.name && manifest.short_name);
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.display, "standalone");
  assert.ok(manifest.icons.some((icon) => icon.sizes.includes("192")));
  assert.ok(manifest.icons.some((icon) => icon.sizes.includes("512")));

  const serviceWorker = await readFile(new URL("sw.js", publicDirectory), "utf8");
  assert.match(serviceWorker, /pathname\.startsWith\(["']\/api\/["']\)/);
  assert.match(serviceWorker, /return\s*;/);
  assert.doesNotMatch(serviceWorker, /cache\.put\s*\(/);
});
