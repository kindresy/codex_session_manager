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
          json: async () => {
            if (this.fail.has("json")) throw new Error("R2 body read failed");
            return JSON.parse(value);
          },
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

function sessionKey(id) {
  return `sessions/${Buffer.from(id).toString("base64url")}.json`;
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
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get(sessionKey(id))), payload);

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
  for (const path of [
    "/api/sessions/",
    "/api/sessions/unencoded/slash",
    "/api/sessions/%",
    "/api/sessions/%00",
    "/api/sessions/%1F",
    "/api/sessions/%7F",
    "/api/sessions/%C2%85",
    `/api/sessions/${"a".repeat(751)}`,
  ]) {
    const response = await request(environment(), path);
    assert.equal(response.status, 400, path);
    assert.deepEqual(await body(response), { error: "invalid_id" });
  }

  const maximum = await request(environment(), `/api/sessions/${"a".repeat(750)}`);
  assert.equal(maximum.status, 404);
});

test("byte-distinct Unicode IDs use distinct ASCII R2 keys", async () => {
  const env = environment();
  const ids = ["\u00e9", "e\u0301"];
  for (const id of ids) {
    const response = await request(env, `/api/sessions/${encodeURIComponent(id)}`, {
      method: "PUT",
      json: session(id),
    });
    assert.equal(response.status, 200);
  }

  const keys = [...env.SESSIONS.values.keys()];
  assert.deepEqual(keys, ids.map(sessionKey));
  assert.notEqual(keys[0], keys[1]);
  assert.ok(keys.every((key) => /^[\x20-\x7E]+$/.test(key)));

  const astral = "astral-\u{1F680}";
  const response = await request(env, `/api/sessions/${encodeURIComponent(astral)}`, {
    method: "PUT",
    json: session(astral),
  });
  assert.equal(response.status, 200);
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get(sessionKey(astral))), session(astral));
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
    ["invalid turn", { ...valid, turns: [null] }, "invalid_payload"],
    ["invalid items", { ...valid, turns: [{ items: {} }] }, "invalid_payload"],
    ["invalid item", { ...valid, turns: [{ items: [null] }] }, "invalid_payload"],
    ["missing item type", { ...valid, turns: [{ items: [{}] }] }, "invalid_payload"],
    ["invalid item type", { ...valid, turns: [{ items: [{ type: 3 }] }] }, "invalid_payload"],
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

  const unknownType = { ...valid, turns: [{ items: [{ type: "future_type", value: 1 }] }] };
  const accepted = await request(environment(), "/api/sessions/session", {
    method: "PUT",
    json: unknownType,
  });
  assert.equal(accepted.status, 200);
});

test("known item types require their normalized fields", async () => {
  const invalidItems = [
    { type: "user" },
    { type: "assistant", text: 3 },
    { type: "command", cwd: "/p", status: "done", output: "", exit_code: null },
    { type: "command", command: "ls", cwd: 3, status: "done", output: "", exit_code: null },
    { type: "command", command: "ls", cwd: "/p", output: "", exit_code: null },
    { type: "command", command: "ls", cwd: "/p", status: "done", output: null, exit_code: null },
    { type: "command", command: "ls", cwd: "/p", status: "done", output: "", exit_code: 1.5 },
    { type: "file_change", kind: "update", diff: "patch" },
    { type: "file_change", path: "a", kind: 3, diff: "patch" },
    { type: "file_change", path: "a", kind: "update" },
  ];
  for (const item of invalidItems) {
    const payload = { ...session(), turns: [{ items: [item] }] };
    const response = await request(environment(), "/api/sessions/session", { method: "PUT", json: payload });
    assert.equal(response.status, 400, JSON.stringify(item));
    assert.deepEqual(await body(response), { error: "invalid_payload" });
  }

  const validItems = [
    { type: "user", text: "question" },
    { type: "assistant", text: "answer" },
    { type: "command", command: "ls", cwd: "/p", status: "done", output: "", exit_code: null },
    { type: "command", command: "false", cwd: "/p", status: "failed", output: "", exit_code: 1 },
    { type: "file_change", path: "a", kind: "update", diff: "patch" },
  ];
  const response = await request(environment(), "/api/sessions/session", {
    method: "PUT",
    json: { ...session(), turns: [{ items: validItems }] },
  });
  assert.equal(response.status, 200);
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
    [{ ...valid, generated_at: "now" }, "invalid_payload"],
    [
      { schema_version: 1, sessions: valid.sessions, deleted_ids: valid.deleted_ids },
      "invalid_payload",
    ],
    [{ ...valid, sessions: [{ ...valid.sessions[0], cwd: undefined }] }, "invalid_payload"],
    [{ ...valid, sessions: [{ ...valid.sessions[0], id: "bad\u0000id" }] }, "invalid_payload"],
    [{ ...valid, deleted_ids: ["bad\uD800id"] }, "invalid_payload"],
    [{ ...valid, sessions: [valid.sessions[0], valid.sessions[0]] }, "invalid_payload"],
    [{ ...valid, deleted_ids: ["gone", "gone"] }, "invalid_payload"],
    [{ ...valid, deleted_ids: ["session"] }, "invalid_payload"],
  ]) {
    const response = await request(environment(), "/api/index", { method: "PUT", json: payload });
    assert.equal(response.status, 400);
    assert.deepEqual(await body(response), { error });
  }

  const nullGeneratedAt = await request(environment(), "/api/index", {
    method: "PUT",
    json: { ...valid, generated_at: null },
  });
  assert.equal(nullGeneratedAt.status, 200);
});

test("stored sessions are revalidated without reporting data errors as R2 failures", async () => {
  const cases = [
    [{ ...session(), schema_version: 2 }, "unsupported_schema"],
    [{ ...session(), id: "other" }, "invalid_data"],
    [{ ...session(), turns: [{ items: [null] }] }, "invalid_data"],
  ];
  for (const [stored, error] of cases) {
    const response = await request(environment({ [sessionKey("session")]: stored }), "/api/sessions/session");
    assert.equal(response.status, 400);
    assert.deepEqual(await body(response), { error });
  }

  const malformed = environment();
  malformed.SESSIONS.values.set(sessionKey("session"), "not json");
  const response = await request(malformed, "/api/sessions/session");
  assert.equal(response.status, 400);
  assert.deepEqual(await body(response), { error: "invalid_data" });

  const readFailure = environment({ [sessionKey("session")]: session() });
  readFailure.SESSIONS.fail.add("json");
  const failed = await request(readFailure, "/api/sessions/session");
  assert.equal(failed.status, 500);
  assert.deepEqual(await body(failed), { error: "storage_failure" });
});

test("stored indexes are revalidated without reporting data errors as R2 failures", async () => {
  const valid = { ...DEFAULT_INDEX, generated_at: 1 };
  for (const [stored, error] of [
    [{ ...valid, schema_version: 2 }, "unsupported_schema"],
    [{ ...valid, sessions: [{}] }, "invalid_data"],
    [{ ...valid, deleted_ids: ["same", "same"] }, "invalid_data"],
  ]) {
    const response = await request(environment({ "index.json": stored }), "/api/sessions");
    assert.equal(response.status, 400);
    assert.deepEqual(await body(response), { error });
  }

  const malformed = environment();
  malformed.SESSIONS.values.set("index.json", "not json");
  const response = await request(malformed, "/api/sessions");
  assert.equal(response.status, 400);
  assert.deepEqual(await body(response), { error: "invalid_data" });
});

test("delete writes a timestamped tombstone index before deleting the session", async (t) => {
  t.mock.method(Date, "now", () => 12_000);
  const id = "id/中文";
  const index = {
    schema_version: 1,
    sessions: [
      { id, question: "q", created_at: 1, updated_at: 2, cwd: "/p" },
      { id: "kept", question: "q", created_at: 1, updated_at: 2, cwd: "/p" },
    ],
    deleted_ids: ["old"],
    generated_at: 8,
  };
  const env = environment({ "index.json": index, [sessionKey(id)]: session(id) });

  const response = await request(env, `/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
  assert.equal(response.status, 200);
  assert.deepEqual(await body(response), { schema_version: 1, deleted: true });
  assert.deepEqual(env.SESSIONS.operations, [
    ["get", "index.json"],
    ["put", "index.json"],
    ["delete", sessionKey(id)],
  ]);
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get("index.json")), {
    ...index,
    sessions: index.sessions.slice(1),
    deleted_ids: ["old", id],
    generated_at: 12,
  });
  assert.equal(env.SESSIONS.values.has(sessionKey(id)), false);
});

test("R2 failures return storage errors and delete succeeds only after both writes", async () => {
  for (const [method, path, failure, json] of [
    ["GET", "/api/sessions", "get"],
    ["PUT", "/api/sessions/session", "put", session()],
    ["DELETE", "/api/sessions/session", "delete"],
  ]) {
    const env = environment({ [sessionKey("session")]: session() });
    env.SESSIONS.fail.add(failure);
    const response = await request(env, path, { method, ...(json && { json }) });
    assert.equal(response.status, 500);
    assert.deepEqual(await body(response), { error: "storage_failure" });
  }

  const env = environment({ [sessionKey("session")]: session() });
  env.SESSIONS.fail.add("delete");
  await request(env, "/api/sessions/session", { method: "DELETE" });
  assert.deepEqual(JSON.parse(env.SESSIONS.values.get("index.json")).deleted_ids, ["session"]);

  const indexFailure = environment();
  indexFailure.SESSIONS.fail.add("put");
  const failed = await request(indexFailure, "/api/sessions/session", { method: "DELETE" });
  assert.equal(failed.status, 500);
  assert.deepEqual(indexFailure.SESSIONS.operations, [
    ["get", "index.json"],
    ["put", "index.json"],
  ]);
});
