const encoder = new TextEncoder();

const EMPTY_INDEX = {
  schema_version: 1,
  sessions: [],
  deleted_ids: [],
  generated_at: null,
};

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === "/health") return json({ ok: true });
    if (pathname !== "/api" && !pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (
      typeof env.SYNC_TOKEN !== "string" ||
      env.SYNC_TOKEN.length === 0 ||
      request.headers.get("Authorization") !== `Bearer ${env.SYNC_TOKEN}`
    ) {
      return error("unauthorized", 401);
    }

    try {
      if (request.method === "GET" && pathname === "/api/sessions") {
        return json(await readIndex(env));
      }
      if (request.method === "PUT" && pathname === "/api/index") {
        return await putIndex(request, env);
      }
      if (pathname.startsWith("/api/sessions/")) {
        const id = sessionId(pathname);
        if (id === null) return error("invalid_id", 400);
        if (request.method === "GET") return await getSession(id, env);
        if (request.method === "PUT") return await putSession(request, id, env);
        if (request.method === "DELETE") return await deleteSession(id, env);
      }
      return error("not_found", 404);
    } catch {
      return error("storage_failure", 500);
    }
  },
};

async function getSession(id, env) {
  const object = await env.SESSIONS.get(sessionKey(id));
  if (object === null) return error("not_found", 404);
  return json(await object.json());
}

async function putSession(request, id, env) {
  const payload = await requestPayload(request);
  if (payload === null) return error("invalid_payload", 400);
  if (payload.schema_version !== 1) return error("unsupported_schema", 400);
  if (!validSession(payload, id)) return error("invalid_payload", 400);
  await write(env, sessionKey(id), payload);
  return json(payload);
}

async function putIndex(request, env) {
  const payload = await requestPayload(request);
  if (payload === null) return error("invalid_payload", 400);
  if (payload.schema_version !== 1) return error("unsupported_schema", 400);
  if (!validIndex(payload)) return error("invalid_payload", 400);
  await write(env, "index.json", payload);
  return json(payload);
}

async function deleteSession(id, env) {
  const current = await readIndex(env);
  const updated = {
    ...current,
    sessions: current.sessions.filter((entry) => entry.id !== id),
    deleted_ids: current.deleted_ids.includes(id) ? current.deleted_ids : [...current.deleted_ids, id],
  };
  await write(env, "index.json", updated);
  await env.SESSIONS.delete(sessionKey(id));
  return json({ schema_version: 1, deleted: true });
}

async function readIndex(env) {
  const object = await env.SESSIONS.get("index.json");
  return object === null ? EMPTY_INDEX : object.json();
}

async function requestPayload(request) {
  try {
    const payload = await request.json();
    return payload && typeof payload === "object" && !Array.isArray(payload) ? payload : null;
  } catch {
    return null;
  }
}

function sessionId(pathname) {
  const encoded = pathname.slice("/api/sessions/".length);
  if (!encoded || encoded.includes("/")) return null;
  try {
    return decodeURIComponent(encoded) || null;
  } catch {
    return null;
  }
}

function validSession(payload, id) {
  return (
    payload.id === id &&
    typeof payload.id === "string" &&
    payload.id.length > 0 &&
    typeof payload.question === "string" &&
    finiteNumber(payload.created_at) &&
    finiteNumber(payload.updated_at) &&
    typeof payload.cwd === "string" &&
    Array.isArray(payload.turns)
  );
}

function validIndex(payload) {
  return (
    Array.isArray(payload.sessions) &&
    payload.sessions.every(validIndexEntry) &&
    Array.isArray(payload.deleted_ids) &&
    payload.deleted_ids.every((id) => typeof id === "string" && id.length > 0) &&
    (payload.generated_at === undefined || payload.generated_at === null || finiteNumber(payload.generated_at))
  );
}

function validIndexEntry(entry) {
  return (
    entry !== null &&
    typeof entry === "object" &&
    !Array.isArray(entry) &&
    typeof entry.id === "string" &&
    entry.id.length > 0 &&
    typeof entry.question === "string" &&
    finiteNumber(entry.created_at) &&
    finiteNumber(entry.updated_at) &&
    typeof entry.cwd === "string"
  );
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function sessionKey(id) {
  return `sessions/${id}.json`;
}

async function write(env, key, value) {
  await env.SESSIONS.put(key, encoder.encode(JSON.stringify(value)));
}

function error(code, status) {
  return json({ error: code }, status);
}

function json(value, status = 200) {
  return new Response(encoder.encode(JSON.stringify(value)), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
