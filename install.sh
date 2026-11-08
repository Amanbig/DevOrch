#!/bin/sh
# DevOrch installer for Linux and macOS.   https://github.com/Amanbig/DevOrch
#
#   curl -fsSL https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.sh | sh -s -- --version 0.5.3
#
# Installs the `devorch` command in its own isolated environment, so it never touches your system Python.
# It picks the first available of: uv, pipx, or a private virtualenv (needs Python 3.10+). If none of
# those work it offers to install uv (which can download Python itself).
#
# It never uses sudo, prints every command it runs, and leaves ~/.devorch (your config and sessions)
# alone, even on --uninstall. Read it before you run it; it is short.
#
# Options (or the matching environment variable):
#   --version X        install a specific version            DEVORCH_VERSION
#   --method M         uv | pipx | venv (default: auto)      DEVORCH_METHOD
#   --from SPEC        install from a wheel/sdist/URL/spec   DEVORCH_FROM       (for testing a build)
#   --bin-dir DIR      where the command is linked (venv)    DEVORCH_BIN_DIR    (default ~/.local/bin)
#   --yes              don't ask before installing uv        DEVORCH_YES=1
#   --dry-run          show what would run, change nothing
#   --uninstall        remove DevOrch (keeps ~/.devorch)
#   -h, --help         show this help

set -eu

PACKAGE="devorch"
VERSION="${DEVORCH_VERSION:-}"
METHOD="${DEVORCH_METHOD:-auto}"
FROM="${DEVORCH_FROM:-}"
ASSUME_YES="${DEVORCH_YES:-0}"
BIN_DIR="${DEVORCH_BIN_DIR:-${HOME:-}/.local/bin}"
DATA_DIR="${XDG_DATA_HOME:-${HOME:-}/.local/share}/devorch"
DRY_RUN=0
UNINSTALL=0

say() { printf '%s\n' "$*"; }
info() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Print a command, then run it unless this is a dry run.
run() {
    printf '+ %s\n' "$*"
    if [ "$DRY_RUN" = 1 ]; then
        return 0
    fi
    "$@"
}

usage() {
    # embedded, not read from "$0": when piped from curl, $0 is "sh", not this file
    cat <<'EOF_USAGE'
DevOrch installer for Linux and macOS

Usage:
  curl -fsSL https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.sh | sh
  curl -fsSL https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.sh | sh -s -- [options]
  sh install.sh [options]

Options (or the matching environment variable):
  --version X      install a specific version              DEVORCH_VERSION
  --method M       uv | pipx | venv (default: auto)        DEVORCH_METHOD
  --from SPEC      install from a wheel/sdist/URL/spec     DEVORCH_FROM
  --bin-dir DIR    where the command is linked (venv)      DEVORCH_BIN_DIR  (default ~/.local/bin)
  --yes, -y        don't ask before installing uv          DEVORCH_YES=1
  --dry-run        show what would run, change nothing
  --uninstall      remove DevOrch (keeps ~/.devorch)
  -h, --help       show this help

Order of preference when --method is auto: uv, then pipx, then a private virtualenv (needs
Python 3.10+). If none works it offers to install uv, which can download Python itself.
EOF_USAGE
}

# ---- arguments -----------------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --version) [ $# -ge 2 ] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
        --version=*) VERSION="${1#*=}"; shift ;;
        --method) [ $# -ge 2 ] || die "--method needs a value"; METHOD="$2"; shift 2 ;;
        --method=*) METHOD="${1#*=}"; shift ;;
        --from) [ $# -ge 2 ] || die "--from needs a value"; FROM="$2"; shift 2 ;;
        --from=*) FROM="${1#*=}"; shift ;;
        --bin-dir) [ $# -ge 2 ] || die "--bin-dir needs a value"; BIN_DIR="$2"; shift 2 ;;
        --bin-dir=*) BIN_DIR="${1#*=}"; shift ;;
        --yes | -y) ASSUME_YES=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) printf 'error: unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$METHOD" in
    auto | uv | pipx | venv) ;;
    *) die "--method must be one of: auto, uv, pipx, venv (got '$METHOD')" ;;
esac

[ -n "${HOME:-}" ] || die "HOME is not set"

# ---- platform ------------------------------------------------------------------------------------

case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux | Darwin) ;;
    MINGW* | MSYS* | CYGWIN*) die "this script is for Linux and macOS. On Windows use install.ps1 (see the README)." ;;
    *) die "unsupported operating system: $(uname -s 2>/dev/null || echo unknown)" ;;
esac

# ---- helpers -------------------------------------------------------------------------------------

package_spec() {
    if [ -n "$FROM" ]; then
        printf '%s' "$FROM"
    elif [ -n "$VERSION" ]; then
        printf '%s==%s' "$PACKAGE" "$VERSION"
    else
        printf '%s' "$PACKAGE"
    fi
}

# A Python >= 3.10 that can create virtual environments (Debian/Ubuntu need the python3-venv package).
find_python() {
    for candidate in python3 python3.13 python3.12 python3.11 python3.10 python; do
        if have "$candidate" \
            && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null \
            && "$candidate" -c 'import ensurepip, venv' 2>/dev/null; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

# Ask a yes/no question on the terminal (stdin is the script itself when piped from curl).
confirm() {
    if [ "$ASSUME_YES" = 1 ]; then
        return 0
    fi
    # /dev/tty can exist as a file with no terminal behind it (containers, CI), so test by opening it,
    # in a subshell with errors hidden: a failed redirection must not abort this script or print noise
    if ( : </dev/tty >/dev/tty ) 2>/dev/null; then
        printf '%s [y/N] ' "$1" >/dev/tty
        answer=""
        read -r answer </dev/tty || answer=""
        case "$answer" in y | Y | yes | YES) return 0 ;; esac
    fi
    return 1
}

on_path() {
    case ":$PATH:" in *":$1:"*) return 0 ;; esac
    return 1
}

fetch_to_stdout() {
    if have curl; then
        curl -LsSf "$1"
    elif have wget; then
        wget -qO- "$1"
    else
        die "need curl or wget to download $1"
    fi
}

bootstrap_uv() {
    info "uv (a fast Python tool installer, which can also download Python) is not installed"
    if ! confirm "Install uv now from https://astral.sh/uv?"; then
        die "no installer available. Install uv (https://docs.astral.sh/uv/), pipx, or Python 3.10+ (with venv) and run this again, or re-run with --yes to let me install uv."
    fi
    printf '+ fetch https://astral.sh/uv/install.sh | sh\n'
    if [ "$DRY_RUN" = 1 ]; then
        return 0
    fi
    # UV_NO_MODIFY_PATH: leave the shell profile alone; PATH advice is printed at the end
    fetch_to_stdout https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
    PATH="$HOME/.local/bin:$PATH"
    have uv || die "uv was installed but is not on PATH; open a new shell and run this again"
}

choose_method() {
    if [ "$METHOD" != auto ]; then
        case "$METHOD" in
            uv) have uv || die "--method uv, but uv is not installed (https://docs.astral.sh/uv/)" ;;
            pipx) have pipx || die "--method pipx, but pipx is not installed (https://pipx.pypa.io)" ;;
            venv) PYTHON="$(find_python)" || die "--method venv needs Python 3.10+ with the venv module (on Debian/Ubuntu: apt install python3-venv)" ;;
        esac
        return 0
    fi
    if have uv; then METHOD=uv
    elif have pipx; then METHOD=pipx
    elif PYTHON="$(find_python)"; then METHOD=venv
    else
        bootstrap_uv
        METHOD=uv
    fi
}

command_bin_dir() {
    case "$METHOD" in
        uv) uv tool dir --bin 2>/dev/null || printf '%s' "$BIN_DIR" ;;
        pipx) pipx environment --value PIPX_BIN_DIR 2>/dev/null || printf '%s' "$BIN_DIR" ;;
        *) printf '%s' "$BIN_DIR" ;;
    esac
}

# ---- uninstall -----------------------------------------------------------------------------------

do_uninstall() {
    removed=0
    if have uv && uv tool list 2>/dev/null | grep -q "^$PACKAGE "; then
        run uv tool uninstall "$PACKAGE"; removed=1
    fi
    if have pipx && pipx list --short 2>/dev/null | grep -q "^$PACKAGE "; then
        run pipx uninstall "$PACKAGE"; removed=1
    fi
    if [ -d "$DATA_DIR/venv" ]; then
        link="$BIN_DIR/devorch"
        if [ -L "$link" ] && [ "$(readlink "$link" 2>/dev/null)" = "$DATA_DIR/venv/bin/devorch" ]; then
            run rm -f "$link"
        fi
        run rm -rf "$DATA_DIR/venv"
        removed=1
    fi
    if [ "$removed" = 0 ]; then
        say "DevOrch was not installed by uv, pipx or this script; nothing to remove."
        say "(If you installed with pip, run: pip uninstall devorch)"
    else
        info "DevOrch removed"
    fi
    say "Your config, sessions and memory in ~/.devorch were kept. Delete them with:  rm -rf ~/.devorch"
}

# ---- install -------------------------------------------------------------------------------------

do_install() {
    PYTHON=""
    choose_method
    spec="$(package_spec)"
    info "Installing $spec using $METHOD"

    case "$METHOD" in
        uv) run uv tool install --force "$spec" ;;
        pipx) run pipx install --force "$spec" ;;
        venv)
            run mkdir -p "$DATA_DIR" "$BIN_DIR"
            [ -d "$DATA_DIR/venv" ] || run "$PYTHON" -m venv "$DATA_DIR/venv"
            run "$DATA_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
            run "$DATA_DIR/venv/bin/python" -m pip install --upgrade "$spec"
            run ln -sf "$DATA_DIR/venv/bin/devorch" "$BIN_DIR/devorch"
            ;;
    esac

    if [ "$DRY_RUN" = 1 ]; then
        info "Dry run: nothing was changed"
        return 0
    fi

    bin_dir="$(command_bin_dir)"
    exe="$bin_dir/devorch"
    [ -x "$exe" ] || exe="$(command -v devorch 2>/dev/null || true)"
    [ -n "$exe" ] && [ -x "$exe" ] || die "installed, but I could not find the devorch command (looked in $bin_dir)"

    installed_version="$("$exe" --version 2>/dev/null)" || die "installed, but '$exe --version' failed"
    info "Installed: $installed_version  ($exe)"

    if ! on_path "$bin_dir"; then
        warn "$bin_dir is not on your PATH, so 'devorch' will not be found yet."
        say "Add it to your shell profile (for example ~/.bashrc or ~/.zshrc), then open a new terminal:"
        say "    export PATH=\"$bin_dir:\$PATH\""
    fi
    say ""
    say "Next:  devorch          start chatting (it walks you through choosing a provider and API key)"
    say "       devorch doctor   check your setup"
    say "Upgrade later by running this installer again; remove with:  sh install.sh --uninstall"
}

if [ "$UNINSTALL" = 1 ]; then
    do_uninstall
else
    do_install
fi
