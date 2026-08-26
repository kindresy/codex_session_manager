# Cloud Session Sync Design

Date: 2026-08-26

## Goal

Add an optional personal cloud library to Codex Session Manager. A Linux machine uploads normalized Codex CLI history to infrastructure owned by the user, while Android browsers and other terminals can list, search, and read that history.

The first release favors a small implementation and simple deployment over advanced security, multi-user administration, background synchronization, or offline support.

## Scope

The first release provides:

- Manual incremental upload from Linux with `codex-session sync`.
- Initial full upload with `codex-session sync --all`.
- A Cloudflare Worker backed by a private R2 bucket.
- A responsive PWA for Android and desktop browsers.
- A read-only cloud mode in the existing terminal UI.
- Cloud-side retention when a local session is archived or deleted.
- Manual deletion from the web viewer.

It does not provide:

- Background services, scheduled synchronization, or automatic upload when the TUI starts.
- End-to-end encryption, QR pairing, per-device credentials, or key rotation.
- Multi-user accounts or sharing between different users.
- Remote resume or continuation of a Codex session.
- Automatic cloud deletion when local data disappears.
- Offline caching of session content.
- Restore of a cloud session deleted in the first release.

## Architecture

The repository gains three independently testable components.

### Sync client

The Python CLI uses the existing Codex App Server integration. It calls `thread/list` for non-archived CLI sessions and calls `thread/read` only for sessions that require upload. It converts Codex responses into a project-owned, versioned JSON format before sending them over HTTPS.

The existing SQLite/JSONL compatibility layer remains a listing fallback, but complete cloud synchronization requires App Server data. If App Server cannot return a complete thread, that session is reported as failed and is not marked as synchronized.

### Cloud Worker

A small Cloudflare Worker authenticates API requests using one configured Bearer token and reads or writes a private R2 bucket. It contains no Codex-specific parsing logic and never connects to the user's Linux machine.

The Worker also serves the PWA static assets from the same origin.

### Web viewer and cloud TUI

The PWA lists and reads cloud sessions through the Worker API. The existing Python TUI gains a cloud-backed repository that provides the same list, search, and preview interfaces as the local repository. Cloud mode is read-only and does not bind Enter to `codex resume`.

## Data Flow

1. `codex-session sync` requests the current remote index.
2. The client lists current non-archived CLI threads from Codex App Server.
3. It compares local session IDs and `updated_at` values with the remote index.
4. For each new or changed session, it reads the full thread and normalizes supported content.
5. It uploads each successful session object independently.
6. After session uploads finish, it writes an index containing all retained remote entries plus successful new or updated entries.
7. PWA and terminal clients fetch the index first and fetch a full session only after selection.

`sync --all` ignores remote timestamps and re-reads every eligible local session except IDs recorded as deleted. It does not clear existing cloud data.

## R2 Object Layout

```text
index.json
sessions/<full-session-id>.json
```

### Index schema

```json
{
  "schema_version": 1,
  "sessions": [
    {
      "id": "full-session-id",
      "question": "first user question",
      "created_at": 1787700000,
      "updated_at": 1787703600,
      "cwd": "/project/path"
    }
  ],
  "deleted_ids": []
}
```

The index contains only fields required by list and search views. Session entries are ordered by `updated_at` descending. A deleted ID is excluded from the visible list and from future uploads.

### Session schema

Each session object contains:

- `schema_version`
- full session ID
- first user question
- creation and update timestamps
- working directory
- chronologically ordered turns
- normalized display items within each turn

Supported display items are:

- user text
- assistant text
- command, output, and exit status
- file-change summary

System prompts, injected environment context, internal reasoning, authentication configuration, and unknown internal event types are omitted. Command output and file-change data are preserved for review but rendered collapsed by default in the web viewer.

## Synchronization Semantics

- Synchronization is manual and idempotent.
- A session is unchanged when its full ID exists remotely and its local `updated_at` is not newer.
- New and changed sessions are uploaded independently.
- Failed reads or uploads are summarized at the end and remain eligible for the next sync.
- The index is updated only after all per-session attempts complete and includes only successful changes.
- Previously stored cloud sessions remain in the index when they no longer appear locally.
- Manual web deletion removes the session object and atomically adds its ID to `deleted_ids` before returning success.
- A deleted ID is never uploaded again, including with `sync --all`.
- The first release assumes one person runs sync commands serially. It does not resolve simultaneous index updates from multiple writers.

## HTTP API

```text
GET    /health
GET    /api/sessions
GET    /api/sessions/:id
PUT    /api/sessions/:id
DELETE /api/sessions/:id
PUT    /api/index
```

All `/api/*` requests require `Authorization: Bearer <token>`. The Worker validates session IDs before constructing R2 object keys. Responses use JSON error objects with stable error codes for authentication failure, missing sessions, invalid payloads, unsupported schema versions, and storage failure.

The PWA and API share one Worker origin, so the first release does not expose cross-origin API access. CLI clients may call the API directly over HTTPS.

## Commands and Configuration

```text
codex-session sync setup
codex-session sync
codex-session sync --all
codex-session sync status
codex-session cloud
```

`sync setup` asks for the Worker URL and access token. The CLI stores them in `~/.config/codex-session/sync.json`. The file is user-readable configuration, not an encryption key store.

`sync status` checks configuration and `/health`, then reports the remote session count and last index update time without uploading.

`codex-session cloud` starts a read-only cloud-backed TUI. It preserves `j/k`, scrolling, `/`, `n/N`, refresh, and quit behavior. Enter has no action in cloud mode, and the help line states that remote resume is unavailable.

## PWA Experience

On first use, the page asks for the shared token and stores it in browser-local storage. It then presents:

- A session list showing first question, update time, working directory, and ID prefix.
- Case-insensitive substring search over first question, full ID, and working directory.
- A detail view that displays turns chronologically.
- Expanded user and assistant messages.
- Collapsed command output and file-change sections.
- Refresh, back, and delete actions.

Phones use list and detail pages. Wider screens use a two-pane list/detail layout. The UI uses lightweight CSS and browser APIs rather than a large component framework. The PWA manifest allows installation to the Android home screen, but the service worker caches only the application shell, not session API responses.

## Deployment

Cloud code lives under `cloud/`. A user clones the repository and runs:

```bash
cd cloud
npm install
./deploy.sh
```

The deployment script guides the user through Cloudflare login, creates or selects a private R2 bucket, stores the shared token as a Worker secret, deploys the Worker and PWA, and prints the resulting Worker URL plus the next `codex-session sync setup` command.

No source edits are required. Deployment requires a user-owned Cloudflare account and Node.js/npm for the one-time cloud deployment. Using the already-installed CLI and PWA does not require Node.js.

## Error Handling

- Missing sync configuration directs the user to `codex-session sync setup`.
- Network errors leave local and existing cloud data unchanged.
- HTTP 401 directs the user to update the configured token.
- One failed session does not stop remaining uploads.
- An index write failure leaves uploaded objects available for reconciliation during the next sync.
- Unsupported local or remote schema versions instruct the user to upgrade Codex Session Manager.
- The PWA shows recoverable errors in the current view and retains the existing list when refresh fails.
- There is no persistent retry queue; rerunning `codex-session sync` retries incomplete work.

## Testing

Python tests cover:

- Codex thread normalization and omission rules.
- Incremental and `--all` selection.
- tombstone handling and retained remote sessions.
- configuration and command routing.
- partial upload and index-write failures.
- the cloud repository and read-only TUI behavior.

Worker tests cover:

- Bearer-token validation.
- session ID and payload validation.
- list, read, upload, and delete operations.
- deletion tombstones.
- R2 error responses.

PWA tests cover:

- token setup.
- list rendering and search.
- detail rendering and collapsed technical items.
- refresh and delete behavior.

An integration test runs against a local Worker/R2 simulation and completes upload, list, read, and delete flows with synthetic data. CI never reads real Codex history and does not require Cloudflare credentials.

## Compatibility Boundary

The cloud schema belongs to Codex Session Manager and is independent of Codex's SQLite and JSONL formats. Only the sync client's App Server adapter depends on Codex's thread response schema. The cloud Worker, stored objects, PWA, and cloud TUI remain stable when Codex changes its local persistence strategy.

Official Codex App Server documentation describes `thread/list` as suitable for rendering history and `thread/read` as a way to retrieve stored turns without resuming the thread. Cloudflare documents direct Worker bindings for R2 and joint deployment of Worker logic with static assets.

## Success Criteria

The feature is complete when a new user can clone the repository, deploy the cloud component without editing source, configure the Linux CLI, manually upload synthetic or real non-archived CLI sessions, and read the resulting history from both an Android PWA and a terminal. Repeated synchronization uploads only changed sessions, cloud-only history remains visible, and manually deleted sessions do not reappear.
