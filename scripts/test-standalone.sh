#!/bin/sh
set -eu

[ "$#" -eq 1 ] || { echo "usage: test-standalone.sh ARCHIVE" >&2; exit 2; }
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
tar -xzf "$1" -C "$WORK"
APP=$WORK/codex-session-manager/codex-session
"$APP" --help >/dev/null
"$APP" --version

JSON_HOME=$WORK/json-home
mkdir -p "$JSON_HOME/sessions/2026/08/22"
cp "$ROOT/tests/fixtures/fallback/rollout-2026-08-22T20-05-43-fixture.jsonl" \
    "$JSON_HOME/sessions/2026/08/22/"
printf 'q' | TERM=xterm timeout 10 script -qefc \
    "$APP --codex-home $JSON_HOME --no-color" /dev/null >/dev/null

SQL_HOME=$WORK/sql-home
mkdir -p "$SQL_HOME"
sqlite3 "$SQL_HOME/state_5.sqlite" <"$ROOT/tests/fixtures/current_schema.sql"
printf 'q' | TERM=xterm timeout 10 script -qefc \
    "$APP --codex-home $SQL_HOME --no-color" /dev/null >/dev/null
