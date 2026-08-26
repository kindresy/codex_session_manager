import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/worker.js";

const DEFAULT_INDEX = {
  schema_version: 1,
  sessions: [],
  deleted_ids: [],
  generated_at: null,
};

class FakeR2 {
  constructor(values = {}) {
    this.values = new Map(Object.entries(values).map(([key, value]) => [key, JSON.stringify(value)]));
    this.operations = [];
    this.fail = new Set();
  }

  async get(key) {
    this.operations.push(["get", key]);
    if (this.fail.has("get")) throw new Error("R2 get failed");
    const value = this.values.get(key);
    return value === undefined
      ? null
      : {
          json: async () => JSON.parse(value),
          text: async () => value,
        };
  }

  async put(key, value) {
    this.operations.push(["put", key]);
    if (this.fail.has("put")) throw new Error("R2 put failed");
    this.values.set(key, typeof value === "string" ? value : new TextDecoder().decode(value));
  }

  async delete(key) {
    this.operations.push(["delete", key]);
    if (this.fail.has("delete")) throw new Error("R2 delete failed");
    this.values.delete(key);
  }
}

function environment(values) {
  const assets = {
    requests: [],
    async fetch(request) {
      this.requests.push(request);
      return new Response("asset");
    },
  };
  return { SESSIONS: new FakeR2(values), SYNC_TOKEN: "secret", ASSETS: assets };
}

async function request(env, path, options = {}) {
  const headers = new Headers(options.headers);
  if (options.auth !== false) headers.set("Authorization", "Bearer secret");
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.json);
  }
  return worker.fetch(new Request(`https://worker.test${path}`, { ...options, headers }), env);
}

async function body(response) {
  assert.match(response.headers.get("content-type"), /^application\/json\b/);
  return response.json();
}

function session(id = "session") {
  return {
    schema_version: 1,
    id,
    question: "First question",
    created_at: 10,
    updated_at: 20.5,
    cwd: "/project",
    turns: [],
  };
}

test("health is public and non-API requests use static assets", async () => {
  const env = environment();
  const health = await request(env, "/health", { auth: false });
  assert.equal(health.status, 200);
  assert.deepEqual(await body(health), { ok: true });

  const asset = await request(env, "/app.js", { auth: false });
  assert.equal(await asset.text(), "asset");
  assert.equal(env.ASSETS.requests.length, 1);
});

test("all API routes require the configured bearer token", async () => {
  for (const [path, authorization] of [
    ["/api/sessions", null],
    ["/api/sessions", "Bearer wrong"],
    ["/api/missing", null],
  ]) {
    const response = await request(environment(), path, {
      auth: false,
      headers: authorization ? { Authorization: authorization } : {},
    });
    assert.equal(response.status, 401);
    assert.deepEqual(await body(response), { error: "unauthorized" });
  }

  const missingToken = environment();
  delete missingToken.SYNC_TOKEN;
  const response = await request(missingToken, "/api/sessions", {
    auth: false,
    headers: { Authorization: "Bearer undefined" },
  });
  assert.equal(response.status, 401);
  assert.deepEqual(await body(response), { error: "unauthorized" });
});

test("missing index returns the versioned empty index", async () => {
  const response = await request(environment(), "/api/sessions");
  assert.equal(response.status, 200);
  assert.deepEqual(await body(response), DEFAULT_INDEX);
});

test("session upload and read preserve UTF-8 JSON under the decoded full ID", async () => {
  const env = environment();
  const id = "id/with space/中文";
  const payload = { ...session(id), question: "你好" };
  const path = `/api/sessions/${encodeURIComponent(id)}`;

  const uploaded = await request(env, path, { method: "PUT", json: payload });
  assert.equal(uploaded.status, 200);
  assert.deepEqual(await body(uploaded), payload);
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get(`sessions/${id}.json`)), payload);

  const downloaded = await request(env, path);
  assert.equal(downloaded.status, 200);
  assert.deepEqual(await body(downloaded), payload);
});

test("missing sessions and unknown API paths return JSON 404 errors", async () => {
  const missing = await request(environment(), "/api/sessions/missing");
  assert.equal(missing.status, 404);
  assert.deepEqual(await body(missing), { error: "not_found" });

  const unknown = await request(environment(), "/api/missing");
  assert.equal(unknown.status, 404);
  assert.deepEqual(await body(unknown), { error: "not_found" });
});

test("session IDs must be a non-empty, well-encoded single path segment", async () => {
  for (const path of ["/api/sessions/", "/api/sessions/unencoded/slash", "/api/sessions/%"]) {
    const response = await request(environment(), path);
    assert.equal(response.status, 400, path);
    assert.deepEqual(await body(response), { error: "invalid_id" });
  }
});

test("session uploads validate schema, path identity, and metadata types", async (t) => {
  const valid = session();
  const cases = [
    ["unsupported schema", { ...valid, schema_version: 2 }, "unsupported_schema"],
    ["mismatched id", { ...valid, id: "other" }, "invalid_payload"],
    ["missing question", { ...valid, question: null }, "invalid_payload"],
    ["invalid created_at", { ...valid, created_at: "10" }, "invalid_payload"],
    ["invalid updated_at", { ...valid, updated_at: Infinity }, "invalid_payload"],
    ["invalid cwd", { ...valid, cwd: 4 }, "invalid_payload"],
    ["invalid turns", { ...valid, turns: {} }, "invalid_payload"],
  ];
  for (const [name, payload, error] of cases) {
    await t.test(name, async () => {
      const response = await request(environment(), "/api/sessions/session", { method: "PUT", json: payload });
      assert.equal(response.status, 400);
      assert.deepEqual(await body(response), { error });
    });
  }

  const malformed = await request(environment(), "/api/sessions/session", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: "not json",
  });
  assert.equal(malformed.status, 400);
  assert.deepEqual(await body(malformed), { error: "invalid_payload" });
});

test("index uploads require schema 1 and list fields", async () => {
  const env = environment();
  const valid = {
    schema_version: 1,
    sessions: [{ id: "session", question: "q", created_at: 1, updated_at: 2, cwd: "/p" }],
    deleted_ids: ["gone"],
    generated_at: 123.5,
  };
  const uploaded = await request(env, "/api/index", { method: "PUT", json: valid });
  assert.equal(uploaded.status, 200);
  assert.deepEqual(await body(uploaded), valid);
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get("index.json")), valid);

  for (const [payload, error] of [
    [{ ...valid, schema_version: 2 }, "unsupported_schema"],
    [{ ...valid, sessions: {} }, "invalid_payload"],
    [{ ...valid, deleted_ids: "gone" }, "invalid_payload"],
  ]) {
    const response = await request(environment(), "/api/index", { method: "PUT", json: payload });
    assert.equal(response.status, 400);
    assert.deepEqual(await body(response), { error });
  }
});

test("delete writes a tombstoned index before deleting the session", async () => {
  const id = "id/中文";
  const index = {
    schema_version: 1,
    sessions: [
      { id, question: "q", created_at: 1, updated_at: 2, cwd: "/p" },
      { id: "kept", question: "q", created_at: 1, updated_at: 2, cwd: "/p" },
    ],
    deleted_ids: ["old", id],
    generated_at: 8,
  };
  const env = environment({ "index.json": index, [`sessions/${id}.json`]: session(id) });

  const response = await request(env, `/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
  assert.equal(response.status, 200);
  assert.deepEqual(await body(response), { schema_version: 1, deleted: true });
  assert.deepEqual(env.SESSIONS.operations, [
    ["get", "index.json"],
    ["put", "index.json"],
    ["delete", `sessions/${id}.json`],
  ]);
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get("index.json")), {
    ...index,
    sessions: index.sessions.slice(1),
    deleted_ids: ["old", id],
  });
  assert.equal(env.SESSIONS.values.has(`sessions/${id}.json`), false);
});

test("R2 failures return storage errors and delete succeeds only after both writes", async () => {
  for (const [method, path, failure, json] of [
    ["GET", "/api/sessions", "get"],
    ["PUT", "/api/sessions/session", "put", session()],
    ["DELETE", "/api/sessions/session", "delete"],
  ]) {
    const env = environment({ "sessions/session.json": session() });
    env.SESSIONS.fail.add(failure);
    const response = await request(env, path, { method, ...(json && { json }) });
    assert.equal(response.status, 500);
    assert.deepEqual(await body(response), { error: "storage_failure" });
  }

  const env = environment({ "sessions/session.json": session() });
  env.SESSIONS.fail.add("delete");
  await request(env, "/api/sessions/session", { method: "DELETE" });
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get("index.json")).deleted_ids, ["session"]);
});
