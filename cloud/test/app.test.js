import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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
