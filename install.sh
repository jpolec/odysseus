#!/usr/bin/env bash
# Install the Odysseus command from a checkout or a fresh GitHub clone.
set -euo pipefail

REPOSITORY="${ODYSSEUS_INSTALL_REPOSITORY:-https://github.com/jpolec/odysseus.git}"
REF="${ODYSSEUS_INSTALL_REF:-main}"
INSTALL_DIR="${ODYSSEUS_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/odysseus}"
BIN_DIR="${ODYSSEUS_BIN_DIR:-$HOME/.local/bin}"
RUN_DOCTOR=1

usage() {
  printf '%s\n' 'Usage: install.sh [--install-dir PATH] [--bin-dir PATH] [--ref REF] [--no-doctor]'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --no-doctor) RUN_DOCTOR=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
CHECKOUT_ROOT=''
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
  CANDIDATE_ROOT="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  if [ -x "$CANDIDATE_ROOT/bin/odysseus" ]; then
    CHECKOUT_ROOT="$CANDIDATE_ROOT"
  fi
fi

if [ -n "$CHECKOUT_ROOT" ]; then
  COMMAND_SOURCE="$CHECKOUT_ROOT/bin/odysseus"
  printf 'Using checkout: %s\n' "$CHECKOUT_ROOT"
else
  if ! command -v git >/dev/null 2>&1; then
    printf '%s\n' 'Git is required to install Odysseus.' >&2
    exit 1
  fi
  if [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR/.git" ]; then
    printf 'Install path exists and is not an Odysseus Git checkout: %s\n' "$INSTALL_DIR" >&2
    exit 1
  fi
  if [ -d "$INSTALL_DIR/.git" ]; then
    printf 'Updating Odysseus in %s\n' "$INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$REF"
    git -C "$INSTALL_DIR" merge --ff-only FETCH_HEAD
  else
    printf 'Installing Odysseus in %s\n' "$INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 --branch "$REF" "$REPOSITORY" "$INSTALL_DIR"
  fi
  COMMAND_SOURCE="$INSTALL_DIR/bin/odysseus"
fi

mkdir -p "$BIN_DIR"
COMMAND_LINK="$BIN_DIR/odysseus"
if [ -L "$COMMAND_LINK" ]; then
  EXISTING_TARGET="$(readlink "$COMMAND_LINK")"
  if [ "$EXISTING_TARGET" != "$COMMAND_SOURCE" ]; then
    printf 'Refusing to replace an unrelated command link: %s -> %s\n' "$COMMAND_LINK" "$EXISTING_TARGET" >&2
    exit 1
  fi
elif [ -e "$COMMAND_LINK" ]; then
  printf 'Refusing to replace an existing file: %s\n' "$COMMAND_LINK" >&2
  exit 1
fi
ln -sfn "$COMMAND_SOURCE" "$COMMAND_LINK"

printf '\nInstalled: %s\n' "$COMMAND_LINK"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf 'Add this directory to PATH: %s\n' "$BIN_DIR" ;;
esac

if [ "$RUN_DOCTOR" -eq 1 ]; then
  printf '\n'
  "$COMMAND_LINK" doctor
else
  printf 'Next: %s doctor\n' "$COMMAND_LINK"
fi
printf 'Start: %s start --open\n' "$COMMAND_LINK"
