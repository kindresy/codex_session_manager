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
printf '\nq' | TERM=xterm timeout 10 script -qefc \
    "stty rows 40 cols 140; env LC_ALL=C.UTF-8 PATH=/usr/bin:/bin $APP --codex-home $JSON_HOME --no-color" \
    "$WORK/json.typescript" >/dev/null
grep -F "fixture real prompt" "$WORK/json.typescript" >/dev/null
grep -F "fixture answer" "$WORK/json.typescript" >/dev/null
grep -F "找不到 codex" "$WORK/json.typescript" >/dev/null

SQL_HOME=$WORK/sql-home
mkdir -p "$SQL_HOME"
sqlite3 "$SQL_HOME/state_5.sqlite" <"$ROOT/tests/fixtures/current_schema.sql"
printf '\nq' | TERM=xterm timeout 10 script -qefc \
    "stty rows 40 cols 140; env LC_ALL=C.UTF-8 PATH=/usr/bin:/bin $APP --codex-home $SQL_HOME --no-color" \
    "$WORK/sql.typescript" >/dev/null
grep -F "current question" "$WORK/sql.typescript" >/dev/null
grep -F "找不到 codex" "$WORK/sql.typescript" >/dev/null
