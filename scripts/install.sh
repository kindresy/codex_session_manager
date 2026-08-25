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
COMMIT_ACTIVE=0
CREATED_TARGET=0
HAD_CURRENT=0
HAD_COMMAND=0
OLD_CURRENT_TARGET=
CURRENT_TMP=
COMMAND_TMP=
cleanup() {
    status=$1
    trap - 0 HUP INT TERM
    if [ "$COMMIT_ACTIVE" -eq 1 ]; then
        ROLLBACK_LINKS_SAFE=0
        if [ "$HAD_COMMAND" -eq 1 ] \
            || { rm -f "$COMMAND" && [ ! -e "$COMMAND" ] && [ ! -L "$COMMAND" ]; }; then
            if [ "$HAD_CURRENT" -eq 1 ]; then
                rollback_tmp=$APP_ROOT/.rollback.$$
                rm -f "$rollback_tmp"
                if [ "${CODEX_SESSION_INSTALLER_TEST_FAIL_ROLLBACK:-}" != 1 ] \
                    && ln -s "$OLD_CURRENT_TARGET" "$rollback_tmp" \
                    && mv -Tf "$rollback_tmp" "$CURRENT" \
                    && [ "$(readlink "$CURRENT")" = "$OLD_CURRENT_TARGET" ]; then
                    ROLLBACK_LINKS_SAFE=1
                fi
                rm -f "$rollback_tmp"
            elif rm -f "$CURRENT" \
                && [ ! -e "$CURRENT" ] && [ ! -L "$CURRENT" ]; then
                ROLLBACK_LINKS_SAFE=1
            fi
        fi
        if [ "$ROLLBACK_LINKS_SAFE" -eq 1 ]; then
            [ "$CREATED_TARGET" -eq 0 ] || rm -rf "$TARGET"
        else
            printf 'Warning: rollback could not safely restore all links; retaining %s\n' \
                "$TARGET" >&2
        fi
    fi
    [ -z "$CURRENT_TMP" ] || rm -f "$CURRENT_TMP"
    [ -z "$COMMAND_TMP" ] || rm -f "$COMMAND_TMP"
    [ -z "$STAGE" ] || rm -rf "$STAGE"
    rm -rf "$DOWNLOAD_DIR"
    exit "$status"
}
trap 'cleanup $?' 0
trap 'exit 1' HUP INT TERM
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
    HAD_COMMAND=1
fi
if [ -e "$CURRENT" ] && [ ! -L "$CURRENT" ]; then
    fail "$CURRENT exists and is not a symbolic link"
fi

PREVIOUS=
if [ -L "$CURRENT" ]; then
    HAD_CURRENT=1
    OLD_CURRENT_TARGET=$(readlink "$CURRENT")
    PREVIOUS=$OLD_CURRENT_TARGET
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
    CREATED_TARGET=1
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
if [ "$HAD_COMMAND" -eq 0 ]; then
    ln -s "$MANAGED_COMMAND" "$COMMAND_TMP"
fi
COMMIT_ACTIVE=1
mv -Tf "$CURRENT_TMP" "$CURRENT"
if [ "${CODEX_SESSION_INSTALLER_TESTING:-}" = 1 ] \
    && [ "${CODEX_SESSION_INSTALLER_TEST_FAIL_PHASE:-}" = after-current ]; then
    fail "injected failure after current switch"
fi
if [ "$HAD_COMMAND" -eq 0 ]; then
    mv -Tf "$COMMAND_TMP" "$COMMAND"
fi

"$COMMAND" --version >/dev/null || fail "installed command smoke test failed"

for directory in "$VERSIONS"/*; do
    [ -d "$directory" ] || continue
    name=${directory##*/}
    [ "$name" = "$VERSION" ] && continue
    [ -n "$PREVIOUS" ] && [ "$name" = "$PREVIOUS" ] && continue
    rm -rf "$directory" || printf 'Warning: could not remove old version %s\n' "$name" >&2
done
COMMIT_ACTIVE=0

printf 'Installed codex-session %s at %s\n' "$VERSION" "$COMMAND"
case :$PATH: in
    *:$PREFIX/bin:*) ;;
    *) printf 'Add it for this shell with:\n  export PATH="%s/bin:$PATH"\n' "$PREFIX" ;;
esac
