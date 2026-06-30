#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="wavemesh-bot"
APP_USER="wavemesh"
APP_DIR="/opt/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
REPO_URL_DEFAULT="https://github.com/Egorius91/wavemesh-bot.git"
BRANCH_DEFAULT="main"

log() {
  printf '\n[WaveMesh] %s\n' "$*"
}

fail() {
  printf '\n[WaveMesh error] %s\n' "$*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "Run as root: sudo bash install.sh"
fi

read -r -p "Repository URL [${REPO_URL_DEFAULT}]: " REPO_URL
REPO_URL="${REPO_URL:-$REPO_URL_DEFAULT}"

read -r -p "Branch [${BRANCH_DEFAULT}]: " BRANCH
BRANCH="${BRANCH:-$BRANCH_DEFAULT}"

read -r -s -p "Telegram BOT_TOKEN: " BOT_TOKEN
printf '\n'
[[ -n "${BOT_TOKEN}" ]] || fail "BOT_TOKEN is required"

read -r -p "Admin Telegram IDs, comma-separated without spaces [123456789]: " ADMIN_IDS
ADMIN_IDS="${ADMIN_IDS:-123456789}"
[[ "${ADMIN_IDS}" =~ ^[0-9]+(,[0-9]+)*$ ]] || fail "ADMIN_IDS must look like 123456789 or 123456789,987654321"

log "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git sudo python3 python3-venv python3-pip sqlite3 build-essential

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  log "Creating system user ${APP_USER}"
  useradd --system --create-home --home-dir "/var/lib/${APP_USER}" --shell /usr/sbin/nologin "${APP_USER}"
fi

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
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

log "Creating Python virtual environment"
sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ -f "${APP_DIR}/config.py" ]]; then
  cp "${APP_DIR}/config.py" "${APP_DIR}/config.py.backup.$(date +%Y%m%d%H%M%S)"
fi

log "Writing config.py"
cat > "${APP_DIR}/config.py" <<PY
BOT_TOKEN = "${BOT_TOKEN}"
ADMIN_IDS = [${ADMIN_IDS}]
GITHUB_REPO_URL = "${REPO_URL}"

RETRY_CONFIG = {
    "max_attempts": 3,
    "delays": [1, 3, 9],
    "timeout_seconds": 15,
}

SQLITE_JOURNAL_MODE = "WAL"
SQLITE_SYNCHRONOUS = "NORMAL"
SQLITE_BUSY_TIMEOUT_MS = 10000
SQLITE_CACHE_SIZE_KB = 32768
SQLITE_TEMP_STORE = "MEMORY"
SQLITE_MMAP_SIZE_BYTES = 134217728
PY

chown "${APP_USER}:${APP_USER}" "${APP_DIR}/config.py"
chmod 600 "${APP_DIR}/config.py"

log "Installing systemd service"
cp "${APP_DIR}/systemd/wavemesh-bot.service" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

log "Running initial checks"
sudo -u "${APP_USER}" bash -lc "cd '${APP_DIR}' && .venv/bin/python -m compileall ."
sudo -u "${APP_USER}" bash -lc "cd '${APP_DIR}' && .venv/bin/python - <<'PY'
from database.migrations import run_migrations
run_migrations()
print('migrations ok')
PY"

log "Starting service"
systemctl restart "${SERVICE_NAME}"
sleep 3
systemctl --no-pager --full status "${SERVICE_NAME}" || true

cat <<EOF

WaveMesh Bot installation finished.

Useful commands:
  systemctl status ${SERVICE_NAME}
  journalctl -u ${SERVICE_NAME} -f
  systemctl restart ${SERVICE_NAME}
  systemctl stop ${SERVICE_NAME}

Project directory:
  ${APP_DIR}

Config:
  ${APP_DIR}/config.py

Database:
  ${APP_DIR}/database/wavemesh_bot.db

EOF
