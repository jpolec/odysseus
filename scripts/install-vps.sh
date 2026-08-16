#!/usr/bin/env bash
# Install Odysseus as a loopback-only systemd service. SSH tunnelling is the
# secure default; --tailscale adds a private tailnet URL for phones/tablets, and
# --domain adds nginx Basic auth and obtains TLS with certbot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR='/opt/odysseus'
STATE_DIR='/var/lib/odysseus'
SERVICE_USER="$(id -un)"
SERVICE_HOME=''
PORT='8741'
DOMAIN=''
WEB_USER='odysseus'
TAILSCALE='0'
TAILSCALE_NAME=''

usage() {
  printf '%s\n' \
    'Usage: scripts/install-vps.sh [options]' \
    '' \
    'Options:' \
    '  --install-dir DIR   Application directory (default: /opt/odysseus)' \
    '  --state-dir DIR     Persistent state directory (default: /var/lib/odysseus)' \
    '  --service-user USER Existing Linux user that owns agent credentials' \
    '  --port PORT         Loopback HTTP port (default: 8741)' \
    "  --domain DOMAIN     Configure nginx + Basic auth + Let's Encrypt (optional)" \
    '  --web-user USER     HTTP Basic auth username (default: odysseus)' \
    '  --tailscale         Configure Tailscale Serve for private mobile/browser access' \
    '  --tailscale-name N  Tailnet DNS name to print in the final URL (optional)' \
    '  -h, --help          Show this help'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL_DIR="${2:?missing directory}"; shift 2 ;;
    --state-dir) STATE_DIR="${2:?missing directory}"; shift 2 ;;
    --service-user) SERVICE_USER="${2:?missing user}"; shift 2 ;;
    --port) PORT="${2:?missing port}"; shift 2 ;;
    --domain) DOMAIN="${2:?missing domain}"; shift 2 ;;
    --web-user) WEB_USER="${2:?missing username}"; shift 2 ;;
    --tailscale) TAILSCALE='1'; shift ;;
    --tailscale-name) TAILSCALE='1'; TAILSCALE_NAME="${2:?missing name}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$PORT" in ''|*[!0-9]*) printf 'Invalid port: %s\n' "$PORT" >&2; exit 2 ;; esac
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  printf 'Linux user does not exist: %s\n' "$SERVICE_USER" >&2
  exit 2
fi
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
for tool in python3 systemctl rsync sed; do
  command -v "$tool" >/dev/null 2>&1 || { printf 'Required command is missing: %s\n' "$tool" >&2; exit 1; }
done
if [ "$TAILSCALE" = '1' ]; then
  command -v tailscale >/dev/null 2>&1 || { printf '%s\n' 'tailscale is required for --tailscale' >&2; exit 1; }
fi

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

sed \
  -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
  -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
  -e "s|__STATE_DIR__|$STATE_DIR|g" \
  -e "s|__SERVICE_HOME__|$SERVICE_HOME|g" \
  -e "s|__PORT__|$PORT|g" \
  "$SOURCE_DIR/deploy/vps/odysseus.service.in" >"$stage/odysseus.service"

sudo install -d -m 0755 "$INSTALL_DIR"
sudo install -d -m 0700 -o "$SERVICE_USER" -g "$(id -gn "$SERVICE_USER")" "$STATE_DIR"
sudo rsync -a --delete --exclude '.git' --exclude '__pycache__' "$SOURCE_DIR/" "$INSTALL_DIR/"
sudo chown -R root:root "$INSTALL_DIR"
sudo chown -R "$SERVICE_USER:$(id -gn "$SERVICE_USER")" "$STATE_DIR"
sudo install -m 0644 "$stage/odysseus.service" /etc/systemd/system/odysseus.service
sudo systemctl daemon-reload
sudo systemctl enable --now odysseus.service

if [ "$TAILSCALE" = '1' ]; then
  sudo tailscale serve --yes --bg --http="$PORT" "127.0.0.1:$PORT"
  if [ -z "$TAILSCALE_NAME" ]; then
    TAILSCALE_NAME="$(tailscale status --json 2>/dev/null | python3 -c 'import json, sys
try:
    self = json.load(sys.stdin).get("Self") or {}
except Exception:
    self = {}
print(str(self.get("DNSName") or self.get("HostName") or "").rstrip("."))' || true)"
  fi
fi

if [ -n "$DOMAIN" ]; then
  for tool in nginx certbot htpasswd; do
    command -v "$tool" >/dev/null 2>&1 || { printf '%s is required for --domain\n' "$tool" >&2; exit 1; }
  done
  sed -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__PORT__|$PORT|g" \
    "$SOURCE_DIR/deploy/vps/nginx-http.conf.in" >"$stage/odysseus.nginx"
  printf 'Choose the HTTPS password for user %s.\n' "$WEB_USER"
  sudo htpasswd -c /etc/nginx/odysseus.htpasswd "$WEB_USER"
  sudo install -m 0644 "$stage/odysseus.nginx" /etc/nginx/sites-available/odysseus
  sudo ln -sfn /etc/nginx/sites-available/odysseus /etc/nginx/sites-enabled/odysseus
  sudo nginx -t
  sudo systemctl reload nginx
  sudo certbot --nginx -d "$DOMAIN" --redirect
  printf 'Odysseus is available at https://%s/\n' "$DOMAIN"
else
  printf '%s\n' \
    'Odysseus is bound to VPS loopback only.' \
    "From your computer run: ssh -N -L ${PORT}:127.0.0.1:${PORT} ${SERVICE_USER}@YOUR_VPS" \
    "Then open: http://127.0.0.1:${PORT}/"
fi

if [ "$TAILSCALE" = '1' ]; then
  if [ -n "$TAILSCALE_NAME" ]; then
    printf '%s\n' \
      'Tailscale Serve is enabled for private tailnet access.' \
      "On a signed-in phone or tablet, open: http://${TAILSCALE_NAME}:${PORT}/"
  else
    printf '%s\n' \
      'Tailscale Serve is enabled for private tailnet access.' \
      "Run: tailscale serve status" \
      "Then open the shown tailnet URL on a signed-in phone or tablet."
  fi
fi
