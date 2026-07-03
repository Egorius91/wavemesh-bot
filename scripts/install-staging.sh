#!/usr/bin/env bash
set -Eeuo pipefail

APP_USER="${APP_USER:-wavemesh}"
APP_DIR="${APP_DIR:-/opt/wavemesh/staging}"
SERVICE_NAME="${SERVICE_NAME:-wavemesh-staging.service}"
REPO_URL="${REPO_URL:-https://github.com/Egorius91/wavemesh-bot.git}"
BRANCH="${BRANCH:-feature/yookassa-recurring-subscriptions}"
DATABASE_PATH="${DATABASE_PATH:-${APP_DIR}/database/wavemesh_bot_staging.db}"

log() {
  printf '\n[WaveMesh staging] %s\n' "$*"
}

fail() {
  printf '\n[WaveMesh staging error] %s\n' "$*" >&2
  exit 1
}

trim_value() {
  local value="$1"
  value="${value//$'\r'/}"
  value="${value//$'\n'/}"
  value="${value//[[:space:]]/}"
  printf '%s' "$value"
}

validate_bot_token_format() {
  local token="$1"
  [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]]
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "Run as root: sudo bash scripts/install-staging.sh"
fi

read -r -p "Repository URL [${REPO_URL}]: " input_repo
REPO_URL="$(trim_value "${input_repo:-$REPO_URL}")"

read -r -p "Branch [${BRANCH}]: " input_branch
BRANCH="$(trim_value "${input_branch:-$BRANCH}")"

read -r -s -p "Staging Telegram BOT_TOKEN: " BOT_TOKEN
printf '\n'
BOT_TOKEN="$(trim_value "$BOT_TOKEN")"
[[ -n "${BOT_TOKEN}" ]] || fail "BOT_TOKEN is required"
validate_bot_token_format "${BOT_TOKEN}" || fail "BOT_TOKEN format is invalid"

read -r -p "Admin Telegram IDs, comma-separated without spaces: " ADMIN_IDS
ADMIN_IDS="$(trim_value "$ADMIN_IDS")"
[[ "${ADMIN_IDS}" =~ ^[0-9]+(,[0-9]+)*$ ]] || fail "ADMIN_IDS must look like 123456789 or 123456789,987654321"

log "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git sudo python3 python3-venv python3-pip sqlite3 build-essential

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  log "Creating system user ${APP_USER}"
  useradd --system --create-home --home-dir "/var/lib/${APP_USER}" --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "$(dirname "${APP_DIR}")"

if [[ -d "${APP_DIR}/.git" ]]; then
  log "Updating repository in ${APP_DIR}"
  git -C "${APP_DIR}" fetch origin
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
else
  log "Cloning repository into ${APP_DIR}"
  git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
fi

mkdir -p "${APP_DIR}/database" "${APP_DIR}/logs" "${APP_DIR}/backup"

log "Writing staging .env"
cat > "${APP_DIR}/.env" <<EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
DATABASE_PATH=${DATABASE_PATH}
GITHUB_REPO_URL=${REPO_URL}
SQLITE_JOURNAL_MODE=WAL
SQLITE_SYNCHRONOUS=NORMAL
SQLITE_BUSY_TIMEOUT_MS=10000
SQLITE_CACHE_SIZE_KB=32768
SQLITE_TEMP_STORE=MEMORY
SQLITE_MMAP_SIZE_BYTES=134217728
EOF

log "Writing staging config.py"
cp "${APP_DIR}/deploy/config.staging.py.example" "${APP_DIR}/config.py"

chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
chmod 600 "${APP_DIR}/.env" "${APP_DIR}/config.py"

log "Creating Python virtual environment"
sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

log "Installing systemd service"
cp "${APP_DIR}/systemd/wavemesh-staging.service" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

log "Running migrations on staging database"
sudo -u "${APP_USER}" env $(grep -v '^#' "${APP_DIR}/.env" | xargs) bash -lc "cd '${APP_DIR}' && .venv/bin/python - <<'PY'
from database.migrations import run_migrations
from database.connection import DB_PATH
run_migrations()
print(f'migrations ok: {DB_PATH}')
PY"

log "Starting staging service"
systemctl restart "${SERVICE_NAME}"
sleep 3
systemctl --no-pager --full status "${SERVICE_NAME}" || true

cat <<EOF

WaveMesh staging installation finished.

Useful commands:
  systemctl status ${SERVICE_NAME}
  journalctl -u ${SERVICE_NAME} -f
  sqlite3 ${DATABASE_PATH}

EOF
