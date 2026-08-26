#!/usr/bin/env bash
set -euo pipefail

bucket_name='codex-session-history'
cloud_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v npm >/dev/null 2>&1; then
    printf 'npm is required. Install Node.js, then retry.\n' >&2
    exit 1
fi
if ! command -v npx >/dev/null 2>&1; then
    printf 'npx is required. Install Node.js, then retry.\n' >&2
    exit 1
fi

cd "$cloud_dir"
npx wrangler login

set +e
bucket_output="$(npx wrangler r2 bucket create codex-session-history 2>&1)"
bucket_status=$?
set -e
if ((bucket_status != 0)); then
    if [[ "$bucket_output" == *'already exists'* ]]; then
        printf 'R2 bucket %s already exists; continuing.\n' "$bucket_name"
    else
        printf 'Could not create R2 bucket %s: %s\n' "$bucket_name" "$bucket_output" >&2
        exit "$bucket_status"
    fi
fi

printf 'SYNC_TOKEN: ' >&2
IFS= read -r -s sync_token || true
printf '\n' >&2
if [[ -z "$sync_token" ]]; then
    printf 'SYNC_TOKEN cannot be empty.\n' >&2
    exit 1
fi

printf '%s\n' "$sync_token" | npx wrangler secret put SYNC_TOKEN
unset sync_token
npx wrangler deploy

printf 'Next: run codex-session sync setup with the Worker URL above.\n'
