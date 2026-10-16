#!/bin/sh
# Mimi installer for Linux (x64, arm64) and macOS (Apple silicon).
#
#   curl -fsSL https://raw.githubusercontent.com/AndrewKenady/mimi/main/scripts/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/AndrewKenady/mimi/main/scripts/install.sh | sh -s -- --tier standard --region us-canada
#   sh scripts/install.sh --tier none          # from a checkout: code + engines only
#
# What it does: gets Mimi into $MIMI_DIR (default ~/mimi; git clone, or a tarball
# if git is missing), fetches uv (pinned, sha256-checked) into $MIMI_DIR/.tools,
# lets uv provide Python 3.12, then runs scripts/install.py with your arguments.
# Nothing is installed system-wide and no sudo is needed. Re-running updates the
# code (git pull --ff-only) and resumes any unfinished downloads.
#
# Environment: MIMI_DIR (install folder), MIMI_REPO, MIMI_BRANCH, MIMI_CONTENT
# (put models/books/maps on another drive).
set -eu

UV_VERSION=0.11.32
MIMI_REPO=${MIMI_REPO:-https://github.com/AndrewKenady/mimi}
MIMI_BRANCH=${MIMI_BRANCH:-main}

say() { printf '%s\n' "$*"; }
die() { printf 'mimi install: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

fetch_to() { # url file
    if have curl; then curl -fL --retry 3 --proto '=https' -o "$2" "$1"
    elif have wget; then wget -q -O "$2" "$1"
    else die "needs curl or wget"; fi
}

sha256_of() {
    if have sha256sum; then sha256sum "$1" | cut -d' ' -f1
    elif have shasum; then shasum -a 256 "$1" | cut -d' ' -f1
    else die "needs sha256sum or shasum to verify downloads"; fi
}

main() {
    os=$(uname -s)
    arch=$(uname -m)
    case "$os/$arch" in
        Linux/x86_64 | Linux/amd64)
            uv_target=x86_64-unknown-linux-gnu
            uv_sha=aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967 ;;
        Linux/aarch64 | Linux/arm64)
            uv_target=aarch64-unknown-linux-gnu
            uv_sha=4d4fa08d95b06642e5800df6a22bd71455f23f988269e18da2847971d8c0bf31 ;;
        Darwin/arm64)
            uv_target=aarch64-apple-darwin
            uv_sha=ed336d0ba49db8ef89b2b41fffa372ce63bd032f22a56f001c265891aec32829 ;;
        Darwin/x86_64)
            die "Intel Macs aren't supported (no llama.cpp/kiwix builds are pinned for them yet). Apple silicon Macs are." ;;
        *)
            die "unsupported system: $os $arch. Mimi runs on Linux x64/arm64, macOS on Apple silicon, and Windows 10/11 x64 (scripts/setup.ps1)." ;;
    esac
    have tar || die "needs tar"

    # 1. The Mimi folder: the checkout this script lives in, or $MIMI_DIR.
    dir=""
    if [ -f "$0" ]; then
        here=$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || true)
        if [ -n "$here" ] && [ -f "$here/core/mimi/__init__.py" ]; then dir=$here; fi
    fi
    if [ -z "$dir" ]; then
        dir=${MIMI_DIR:-$HOME/mimi}
        if [ -d "$dir/.git" ] && have git; then
            say "== Updating $dir"
            git -C "$dir" pull --ff-only || say "   (couldn't fast-forward; keeping your local version)"
        elif [ -f "$dir/core/mimi/__init__.py" ]; then
            say "== Using $dir"
        elif have git; then
            say "== Downloading Mimi into $dir"
            git clone --depth 1 --branch "$MIMI_BRANCH" "$MIMI_REPO" "$dir"
        else
            say "== Downloading Mimi into $dir (no git: tarball)"
            mkdir -p "$dir"
            fetch_to "$MIMI_REPO/archive/refs/heads/$MIMI_BRANCH.tar.gz" "$dir/.mimi-src.tar.gz"
            tar -xzf "$dir/.mimi-src.tar.gz" -C "$dir" --strip-components=1
            rm -f "$dir/.mimi-src.tar.gz"
        fi
    fi
    say "== Mimi folder: $dir"
    tools="$dir/.tools"
    mkdir -p "$tools/dl"

    # 2. uv (Python manager): the one on PATH, or a pinned, checksummed copy in .tools/uv.
    if have uv; then
        uv=$(command -v uv)
    elif [ -x "$tools/uv/uv" ]; then
        uv="$tools/uv/uv"
    else
        say "== uv $UV_VERSION"
        archive="$tools/dl/uv-$uv_target.tar.gz"
        fetch_to "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$uv_target.tar.gz" "$archive"
        got=$(sha256_of "$archive")
        [ "$got" = "$uv_sha" ] || { rm -f "$archive"; die "uv download failed its checksum (got $got)"; }
        mkdir -p "$tools/uv"
        tar -xzf "$archive" -C "$tools/uv" --strip-components=1
        rm -f "$archive"
        uv="$tools/uv/uv"
    fi

    # 3. Python 3.12, managed by uv inside the Mimi folder.
    export UV_PYTHON_INSTALL_DIR="$tools/pythons" UV_CACHE_DIR="$tools/uv-cache"
    say "== Python 3.12"
    "$uv" python install --no-bin 3.12  # stays inside the Mimi folder: nothing added to ~/.local/bin
    py=$("$uv" python find 3.12) || die "uv couldn't provide Python 3.12"

    # 4. Everything else: scripts/install.py (engines, UI, content).
    say "== Running scripts/install.py $*"
    exec "$py" "$dir/scripts/install.py" --uv "$uv" "$@"
}

main "$@"
