#!/bin/sh
set -eu

bucket_name='codex-session-history'

case "$0" in
    */*) script_path=$0 ;;
    *) script_path=$(command -v "$0") || exit 1 ;;
esac
script_dir=${script_path%/*}
[ "$script_dir" = "$script_path" ] && script_dir=.
cloud_dir=$(CDPATH= cd -P "$script_dir" && pwd)

if ! command -v npm >/dev/null 2>&1; then
    printf 'npm is required. Install Node.js, then retry.\n' >&2
    exit 1
fi
if ! command -v npx >/dev/null 2>&1; then
    printf 'npx is required. Install Node.js, then retry.\n' >&2
    exit 1
fi

cd "$cloud_dir"
npx --no-install wrangler login

if bucket_output=$(npx --no-install wrangler r2 bucket create codex-session-history 2>&1); then
    :
else
    bucket_status=$?
    if [ "$bucket_output" != "Bucket $bucket_name already exists." ]; then
        printf 'Could not create R2 bucket %s: %s\n' "$bucket_name" "$bucket_output" >&2
        exit "$bucket_status"
    fi
    printf 'R2 bucket %s already exists; continuing.\n' "$bucket_name"
fi

npx --no-install wrangler r2 bucket dev-url disable codex-session-history --force
if domain_output=$(npx --no-install wrangler r2 bucket domain list codex-session-history 2>&1); then
    :
else
    domain_status=$?
    printf 'Could not list custom domains for R2 bucket %s: %s\n' "$bucket_name" "$domain_output" >&2
    exit "$domain_status"
fi
empty_domain_output="Listing custom domains connected to bucket '$bucket_name'...
There are no custom domains connected to this bucket."
if [ "$domain_output" != "$empty_domain_output" ]; then
    printf 'R2 bucket %s has custom domains. Remove them before deploying.\n' "$bucket_name" >&2
    exit 1
fi

terminal_hidden=0
restore_terminal() {
    if [ "$terminal_hidden" -eq 1 ]; then
        stty echo
    fi
}
trap 'restore_terminal' 0 1 2 3 15
set +x
printf 'SYNC_TOKEN: ' >&2
if [ -t 0 ]; then
    stty -echo
    terminal_hidden=1
fi
IFS= read -r sync_token || sync_token=
if [ "$terminal_hidden" -eq 1 ]; then
    stty echo
    terminal_hidden=0
fi
printf '\n' >&2
if [ -z "$sync_token" ]; then
    printf 'SYNC_TOKEN cannot be empty.\n' >&2
    exit 1
fi

printf '%s\n' "$sync_token" | npx --no-install wrangler secret put SYNC_TOKEN
unset sync_token
npx --no-install wrangler deploy

printf 'Next: run codex-session sync setup with the Worker URL above.\n'
