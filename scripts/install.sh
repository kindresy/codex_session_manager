#!/bin/sh
set -eu

PROGRAM=codex-session-manager
ASSET=codex-session-manager-linux-x86_64.tar.gz
REPOSITORY=https://github.com/kindresy/codex_session_manager
PREFIX=${HOME:?HOME is not set}/.local
REQUESTED_TAG=

fail() {
    printf 'codex-session installer: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf 'Usage: install.sh [--prefix PATH] [--version vX.Y.Z]\n'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ "$#" -ge 2 ] || fail "--prefix requires a path"
            PREFIX=$2
            shift 2
            ;;
        --version)
            [ "$#" -ge 2 ] || fail "--version requires a tag such as v0.1.0"
            REQUESTED_TAG=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[ "$(uname -s)" = Linux ] || fail "only Linux is supported"
case "$(uname -m)" in
    x86_64|amd64) ;;
    *) fail "only Linux x86_64 is supported" ;;
esac
for command in curl tar sha256sum mktemp awk grep mkdir mv rm rmdir ln readlink; do
    command -v "$command" >/dev/null 2>&1 || fail "required command not found: $command"
done

RELEASE_BASE_URL=${CODEX_SESSION_RELEASE_BASE_URL:-$REPOSITORY/releases/download}
LATEST_URL=${CODEX_SESSION_LATEST_URL:-$REPOSITORY/releases/latest}
case "$RELEASE_BASE_URL" in
    https://*) ;;
    file://*) [ "${CODEX_SESSION_INSTALLER_TESTING:-}" = 1 ] || fail "release URL must use HTTPS" ;;
    *) fail "release URL must use HTTPS" ;;
esac
case "$LATEST_URL" in
    https://*) ;;
    file://*) [ "${CODEX_SESSION_INSTALLER_TESTING:-}" = 1 ] \
        || fail "latest release URL must use HTTPS" ;;
    *) fail "latest release URL must use HTTPS" ;;
esac

TAG=$REQUESTED_TAG
if [ -z "$TAG" ]; then
    effective_url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$LATEST_URL") \
        || fail "could not resolve the latest release"
    TAG=${effective_url##*/}
fi
printf '%s\n' "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$' \
    || fail "invalid release tag: $TAG"
VERSION=${TAG#v}

DOWNLOAD_DIR=$(mktemp -d) || fail "could not create a temporary directory"
STAGE=
cleanup() {
    [ -z "$STAGE" ] || rm -rf "$STAGE"
    rm -rf "$DOWNLOAD_DIR"
}
trap cleanup EXIT HUP INT TERM
ARCHIVE=$DOWNLOAD_DIR/$ASSET
CHECKSUM=$ARCHIVE.sha256
URL=$RELEASE_BASE_URL/$TAG
curl -fsSL "$URL/$ASSET" -o "$ARCHIVE" || fail "archive download failed"
curl -fsSL "$URL/$ASSET.sha256" -o "$CHECKSUM" || fail "checksum download failed"
(cd "$DOWNLOAD_DIR" && sha256sum -c "$ASSET.sha256") >/dev/null 2>&1 \
    || fail "archive checksum verification failed"

tar -tzf "$ARCHIVE" >"$DOWNLOAD_DIR/members" || fail "release archive is invalid"
if awk -F/ '
    BEGIN { bad = 0 }
    /^\// { bad = 1 }
    { for (i = 1; i <= NF; i++) if ($i == "..") bad = 1 }
    END { exit bad ? 0 : 1 }
' "$DOWNLOAD_DIR/members"; then
    fail "release archive contains an unsafe path"
fi
awk -F/ '$1 != "codex-session-manager" { exit 1 }' "$DOWNLOAD_DIR/members" \
    || fail "release archive has an unexpected root directory"

APP_ROOT=$PREFIX/lib/$PROGRAM
VERSIONS=$APP_ROOT/versions
TARGET=$VERSIONS/$VERSION
CURRENT=$APP_ROOT/current
COMMAND=$PREFIX/bin/codex-session
MANAGED_COMMAND=../lib/$PROGRAM/current/codex-session
mkdir -p "$VERSIONS" "$PREFIX/bin"

if [ -e "$COMMAND" ] || [ -L "$COMMAND" ]; then
    [ -L "$COMMAND" ] && [ "$(readlink "$COMMAND")" = "$MANAGED_COMMAND" ] \
        || fail "$COMMAND already exists and is not managed by this installer"
fi
if [ -e "$CURRENT" ] && [ ! -L "$CURRENT" ]; then
    fail "$CURRENT exists and is not a symbolic link"
fi

PREVIOUS=
if [ -L "$CURRENT" ]; then
    PREVIOUS=$(readlink "$CURRENT")
    PREVIOUS=${PREVIOUS##*/}
fi

if [ ! -d "$TARGET" ]; then
    STAGE=$(mktemp -d "$APP_ROOT/.stage.XXXXXX") \
        || fail "could not create installation staging directory"
    tar -xzf "$ARCHIVE" -C "$STAGE" || fail "release archive extraction failed"
    STAGED=$STAGE/codex-session-manager
    [ -x "$STAGED/codex-session" ] || fail "release executable is missing"
    reported=$("$STAGED/codex-session" --version 2>/dev/null) \
        || fail "staged executable did not start"
    [ "$reported" = "codex-session $VERSION" ] \
        || fail "staged executable version does not match $TAG"
    mv "$STAGED" "$TARGET"
    rmdir "$STAGE"
    STAGE=
else
    reported=$("$TARGET/codex-session" --version 2>/dev/null) \
        || fail "installed version $VERSION is damaged"
    [ "$reported" = "codex-session $VERSION" ] \
        || fail "installed version $VERSION does not match its directory"
fi

CURRENT_TMP=$APP_ROOT/.current.$$
COMMAND_TMP=$PREFIX/bin/.codex-session.$$
rm -f "$CURRENT_TMP" "$COMMAND_TMP"
ln -s "versions/$VERSION" "$CURRENT_TMP"
ln -s "$MANAGED_COMMAND" "$COMMAND_TMP"
mv -Tf "$CURRENT_TMP" "$CURRENT"
mv -Tf "$COMMAND_TMP" "$COMMAND"

for directory in "$VERSIONS"/*; do
    [ -d "$directory" ] || continue
    name=${directory##*/}
    [ "$name" = "$VERSION" ] && continue
    [ -n "$PREVIOUS" ] && [ "$name" = "$PREVIOUS" ] && continue
    rm -rf "$directory"
done

"$COMMAND" --version >/dev/null || fail "installed command smoke test failed"
printf 'Installed codex-session %s at %s\n' "$VERSION" "$COMMAND"
case :$PATH: in
    *:$PREFIX/bin:*) ;;
    *) printf 'Add %s/bin to PATH to run codex-session directly.\n' "$PREFIX" ;;
esac
