const TOKEN_KEY = "codex-session-sync-token";

export function matchSession(session, query) {
  const needle = String(query ?? "").trim().toLocaleLowerCase();
  if (!needle) return true;
  return [session.id, session.question, session.cwd].some((value) =>
    String(value ?? "").toLocaleLowerCase().includes(needle),
  );
}

export function shortSessionId(id) {
  return [...String(id ?? "")].slice(0, 8).join("");
}

export function validSessionIndex(payload) {
  return payload !== null && payload?.schema_version === 1 && Array.isArray(payload.sessions);
}

export function sessionListFromIndex(payload) {
  if (!validSessionIndex(payload)) throw new Error("invalid_index");
  return payload.sessions;
}

export function isMobileLayout(mediaQuery) {
  return Boolean(mediaQuery?.matches);
}

export async function requestJson(fetcher, token, path, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", "application/json");
  const response = await fetcher(path, { ...options, headers, cache: "no-store" });
  if (response.ok) return response.json();
  let code = `${response.status}`;
  try {
    code = (await response.json()).error || code;
  } catch {
    // The HTTP status remains useful when an intermediary returns non-JSON.
  }
  const error = new Error(code);
  error.status = response.status;
  throw error;
}

export function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
  );
}

export function formatTimestamp(seconds) {
  const date = timestampDate(seconds);
  return date ? date.toLocaleString() : "Unknown time";
}

function timestampDate(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return null;
  const date = new Date(seconds * 1000);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function renderItems(turns) {
  return (Array.isArray(turns) ? turns : [])
    .flatMap((turn) => (Array.isArray(turn?.items) ? turn.items : []))
    .map(renderItem)
    .join("");
}

function renderItem(item) {
  if (item.type === "user" || item.type === "assistant") {
    const label = item.type === "user" ? "You" : "Assistant";
    return `<article class="message ${item.type}"><h3>${label}</h3><div class="message-text">${escapeHtml(item.text)}</div></article>`;
  }
  if (item.type === "command") {
    const exit = item.exit_code === null ? "" : ` · exit ${escapeHtml(item.exit_code)}`;
    return `<details class="activity command"><summary>Command · ${escapeHtml(item.status)}${exit}</summary><div class="activity-body"><code>${escapeHtml(item.command)}</code><p class="path">${escapeHtml(item.cwd)}</p><pre>${escapeHtml(item.output)}</pre></div></details>`;
  }
  if (item.type === "file_change") {
    return `<details class="activity file-change"><summary>${escapeHtml(item.kind)} · ${escapeHtml(item.path)}</summary><pre>${escapeHtml(item.diff)}</pre></details>`;
  }
  return `<details class="activity unknown"><summary>${escapeHtml(item.type || "Unknown item")}</summary><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></details>`;
}

function startApp() {
  const elements = Object.fromEntries(
    [
      "token-panel",
      "token-form",
      "token-input",
      "token-error",
      "viewer",
      "session-pane",
      "search",
      "refresh",
      "change-token",
      "status",
      "session-list",
      "empty-list",
      "detail",
      "detail-empty",
      "detail-content",
      "detail-title",
      "detail-meta",
      "items",
      "back",
      "delete-session",
    ].map((id) => [id, document.getElementById(id)]),
  );
  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    sessions: [],
    selectedId: null,
    detailHistory: false,
    returnFocusId: null,
  };
  const mobileQuery = window.matchMedia("(max-width: 47.99rem)");

  function showTokenSetup(message = "") {
    elements["token-panel"].hidden = false;
    elements.viewer.hidden = true;
    elements["token-error"].textContent = message;
    elements["token-input"].value = state.token;
    elements["token-input"].focus();
  }

  function showViewer() {
    elements["token-panel"].hidden = true;
    elements.viewer.hidden = false;
  }

  function setStatus(message, error = false) {
    elements.status.textContent = message;
    elements.status.classList.toggle("error", error);
  }

  async function api(path, options = {}) {
    try {
      return await requestJson(fetch, state.token, path, options);
    } catch (error) {
      if (error.status === 401) {
        state.token = "";
        localStorage.removeItem(TOKEN_KEY);
        clearDetail({ restoreFocus: false, consumeHistory: true });
        showTokenSetup("Token invalid. Enter a valid sync token.");
      }
      throw error;
    }
  }

  function renderList() {
    const matches = state.sessions.filter((session) => matchSession(session, elements.search.value));
    elements["session-list"].replaceChildren();
    elements["empty-list"].hidden = matches.length !== 0;
    for (const session of matches) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      const question = document.createElement("strong");
      const id = document.createElement("span");
      const metadata = document.createElement("span");
      const updated = document.createElement("time");
      button.type = "button";
      button.className = "session-card";
      button.dataset.sessionId = session.id;
      button.classList.toggle("selected", session.id === state.selectedId);
      question.textContent = session.question || "Untitled session";
      id.className = "session-id";
      id.textContent = shortSessionId(session.id);
      metadata.textContent = session.cwd;
      updated.textContent = formatTimestamp(session.updated_at);
      const date = timestampDate(session.updated_at);
      if (date) updated.dateTime = date.toISOString();
      button.append(question, id, metadata, updated);
      button.addEventListener("click", () => selectSession(session));
      item.append(button);
      elements["session-list"].append(item);
    }
  }

  async function refreshSessions() {
    elements.refresh.disabled = true;
    setStatus("Refreshing…");
    try {
      const index = await api("/api/sessions");
      state.sessions = sessionListFromIndex(index);
      if (state.selectedId && !state.sessions.some((session) => session.id === state.selectedId)) {
        clearDetail({ consumeHistory: true });
      }
      renderList();
      setStatus(`${state.sessions.length} session${state.sessions.length === 1 ? "" : "s"}`);
    } catch (error) {
      setStatus(`Refresh failed: ${error.message}. Showing the previous list.`, true);
    } finally {
      elements.refresh.disabled = false;
    }
  }

  async function selectSession(metadata) {
    const opening = state.selectedId === null;
    state.returnFocusId = metadata.id;
    state.selectedId = metadata.id;
    renderList();
    elements.detail.classList.add("detail-open");
    elements["detail-empty"].hidden = true;
    elements["detail-content"].hidden = false;
    elements["detail-title"].textContent = metadata.question || "Untitled session";
    elements["detail-meta"].textContent = "Loading…";
    elements.items.replaceChildren();
    if (opening && isMobileLayout(mobileQuery)) pushDetailHistory();
    syncDetailAccessibility(true);
    try {
      const session = await api(`/api/sessions/${encodeURIComponent(metadata.id)}`);
      if (state.selectedId !== metadata.id) return;
      elements["detail-title"].textContent = session.question || "Untitled session";
      elements["detail-meta"].textContent = `${session.cwd} · ${formatTimestamp(session.updated_at)}`;
      elements.items.innerHTML = renderItems(session.turns);
    } catch (error) {
      if (state.selectedId === metadata.id) {
        elements["detail-meta"].textContent = `Could not load session: ${error.message}`;
      }
    }
  }

  function pushDetailHistory() {
    if (state.detailHistory) return;
    history.pushState({ codexSessionDetail: true }, "");
    state.detailHistory = true;
  }

  function syncDetailAccessibility(focusDetail = false) {
    const modal = state.selectedId !== null && isMobileLayout(mobileQuery);
    elements["session-pane"].inert = modal;
    if (modal) elements["session-pane"].setAttribute("aria-hidden", "true");
    else elements["session-pane"].removeAttribute("aria-hidden");
    if (modal && focusDetail) elements.back.focus();
  }

  function focusSession(id) {
    if (!id) return;
    const button = [...elements["session-list"].querySelectorAll(".session-card")].find(
      (candidate) => candidate.dataset.sessionId === id,
    );
    button?.focus();
  }

  function clearDetail({ restoreFocus = true, consumeHistory = false } = {}) {
    const focusId = state.returnFocusId;
    const hadHistory = consumeHistory && state.detailHistory;
    state.detailHistory = false;
    state.selectedId = null;
    elements.detail.classList.remove("detail-open");
    elements["detail-content"].hidden = true;
    elements["detail-empty"].hidden = false;
    elements.items.replaceChildren();
    renderList();
    syncDetailAccessibility();
    if (restoreFocus) focusSession(focusId);
    if (hadHistory) history.back();
  }

  async function deleteSelected() {
    const session = state.sessions.find((entry) => entry.id === state.selectedId);
    if (!session || !confirm(`Delete “${session.question || session.id}”? This cannot be undone.`)) return;
    elements["delete-session"].disabled = true;
    try {
      await api(`/api/sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
      state.sessions = state.sessions.filter((entry) => entry.id !== session.id);
      clearDetail({ consumeHistory: true });
      setStatus("Session deleted.");
    } catch (error) {
      setStatus(`Delete failed: ${error.message}`, true);
    } finally {
      elements["delete-session"].disabled = false;
    }
  }

  elements["token-form"].addEventListener("submit", (event) => {
    event.preventDefault();
    state.token = elements["token-input"].value;
    localStorage.setItem(TOKEN_KEY, state.token);
    elements["token-error"].textContent = "";
    showViewer();
    refreshSessions();
  });
  elements["change-token"].addEventListener("click", () => showTokenSetup());
  elements.refresh.addEventListener("click", refreshSessions);
  elements.search.addEventListener("input", renderList);
  elements.back.addEventListener("click", () => {
    if (state.detailHistory) history.back();
    else clearDetail();
  });
  elements["delete-session"].addEventListener("click", deleteSelected);
  window.addEventListener("popstate", () => {
    if (!state.detailHistory) return;
    state.detailHistory = false;
    clearDetail();
  });
  mobileQuery.addEventListener("change", () => {
    if (state.selectedId !== null && isMobileLayout(mobileQuery)) pushDetailHistory();
    syncDetailAccessibility(state.selectedId !== null);
  });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
  if (state.token) {
    showViewer();
    refreshSessions();
  } else {
    showTokenSetup();
  }
}

if (typeof document !== "undefined") startApp();
