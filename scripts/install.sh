#!/bin/sh
set -eu

REPO_GIT_URL="git+https://github.com/Alishahryar1/free-claude-code.git"
PYTHON_VERSION="3.14.0"
UV_INSTALL_URL="https://astral.sh/uv/install.sh"

dry_run=0
voice_nim=0
voice_local=0
voice_all=0
torch_backend=""

show_usage() {
    cat <<'USAGE'
Usage: install.sh [options]

Installs or updates Claude Code, uv, Python 3.14.0, and Free Claude Code.

Options:
  --voice-nim              Install NVIDIA NIM voice transcription support.
  --voice-local            Install local Whisper voice transcription support.
  --voice-all              Install all voice transcription backends.
  --torch-backend VALUE    Use a uv PyTorch backend, such as cu130. Requires local voice.
  --dry-run                Print commands without running them.
  --help                   Show this help text.
USAGE
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

step() {
    printf '\n==> %s\n' "$1"
}

quote_arg() {
    case "$1" in
        *[!A-Za-z0-9_./:@%+=,-]*|"")
            escaped=$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')
            printf '"%s"' "$escaped"
            ;;
        *)
            printf '%s' "$1"
            ;;
    esac
}

print_command() {
    printf '+'
    for arg in "$@"; do
        printf ' '
        quote_arg "$arg"
    done
    printf '\n'
}

run() {
    print_command "$@"
    if [ "$dry_run" -eq 0 ]; then
        "$@"
    fi
}

run_uv_installer() {
    printf '+ curl -LsSf %s | sh\n' "$UV_INSTALL_URL"
    if [ "$dry_run" -eq 0 ]; then
        command -v curl >/dev/null 2>&1 || fail "curl is required to install uv."
        curl -LsSf "$UV_INSTALL_URL" | sh
    fi
}

add_path_entry() {
    [ -n "$1" ] || return 0
    case ":$PATH:" in
        *":$1:"*) ;;
        *) PATH="$1:$PATH" ;;
    esac
}

add_uv_to_path() {
    if [ -n "${XDG_BIN_HOME:-}" ]; then
        add_path_entry "$XDG_BIN_HOME"
    fi

    if [ -n "${HOME:-}" ]; then
        add_path_entry "$HOME/.local/bin"
        add_path_entry "$HOME/.cargo/bin"
    fi

    export PATH
}

require_command() {
    if [ "$dry_run" -eq 0 ] && ! command -v "$1" >/dev/null 2>&1; then
        fail "$1 is required. Install it first, then rerun this installer."
    fi
}

install_or_update_claude() {
    if command -v claude >/dev/null 2>&1; then
        claude_path=$(command -v claude)
        if command -v npm >/dev/null 2>&1 && npm_prefix=$(npm prefix -g 2>/dev/null); then
            case "$claude_path" in
                "$npm_prefix"/*)
                    run npm install -g @anthropic-ai/claude-code@latest
                    return 0
                    ;;
            esac
        fi

        if [ -n "${claude_path:-}" ]; then
            run env CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE=1 "$claude_path" update
            return 0
        else
            run npm install -g @anthropic-ai/claude-code@latest
            return 0
        fi
    fi

    require_command npm
    run npm install -g @anthropic-ai/claude-code@latest
}

install_or_update_uv() {
    add_uv_to_path

    if command -v uv >/dev/null 2>&1; then
        run uv self update
        return 0
    fi

    run_uv_installer
    add_uv_to_path

    if [ "$dry_run" -eq 0 ] && ! command -v uv >/dev/null 2>&1; then
        fail "uv was installed, but it is not available on PATH. Open a new terminal or add uv's bin directory to PATH."
    fi
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --voice-nim)
                voice_nim=1
                ;;
            --voice-local)
                voice_local=1
                ;;
            --voice-all)
                voice_all=1
                ;;
            --torch-backend)
                shift
                [ "$#" -gt 0 ] || fail "--torch-backend requires a value."
                torch_backend="$1"
                [ -n "$torch_backend" ] || fail "--torch-backend requires a non-empty value."
                ;;
            --torch-backend=*)
                torch_backend="${1#*=}"
                [ -n "$torch_backend" ] || fail "--torch-backend requires a non-empty value."
                ;;
            --dry-run)
                dry_run=1
                ;;
            --help|-h)
                show_usage
                exit 0
                ;;
            *)
                show_usage >&2
                fail "unknown option: $1"
                ;;
        esac
        shift
    done
}

validate_args() {
    include_local=$voice_local

    if [ "$voice_all" -eq 1 ]; then
        include_local=1
    fi

    if [ -n "$torch_backend" ] && [ "$include_local" -ne 1 ]; then
        fail "--torch-backend requires --voice-local or --voice-all."
    fi
}

package_spec() {
    include_nim=$voice_nim
    include_local=$voice_local

    if [ "$voice_all" -eq 1 ]; then
        include_nim=1
        include_local=1
    fi

    if [ -n "$torch_backend" ] && [ "$include_local" -ne 1 ]; then
        fail "--torch-backend requires --voice-local or --voice-all."
    fi

    if [ "$include_nim" -eq 1 ] && [ "$include_local" -eq 1 ]; then
        printf 'free-claude-code[voice,voice_local] @ %s' "$REPO_GIT_URL"
    elif [ "$include_nim" -eq 1 ]; then
        printf 'free-claude-code[voice] @ %s' "$REPO_GIT_URL"
    elif [ "$include_local" -eq 1 ]; then
        printf 'free-claude-code[voice_local] @ %s' "$REPO_GIT_URL"
    else
        printf '%s' "$REPO_GIT_URL"
    fi
}

install_free_claude_code() {
    spec=$(package_spec)

    if [ -n "$torch_backend" ]; then
        run uv tool install --force --torch-backend "$torch_backend" "$spec"
    else
        run uv tool install --force "$spec"
    fi
}

parse_args "$@"
validate_args

step "Installing or updating Claude Code"
install_or_update_claude

step "Installing uv if missing, updating if present"
install_or_update_uv

step "Installing Python $PYTHON_VERSION"
run uv python install "$PYTHON_VERSION"

step "Installing or updating Free Claude Code"
install_free_claude_code

printf '\nFree Claude Code is installed. Start the proxy with: fcc-server\n'
