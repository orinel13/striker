#!/usr/bin/env bash
set -euo pipefail

apt update
apt install -y python3 python3-venv python3-pip git nginx unzip curl build-essential

if [ ! -d /opt/striker/.git ]; then
  rm -rf /opt/striker
  git clone https://github.com/orinel13/striker.git /opt/striker
fi

cd /opt/striker
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required. Install a newer python3 package before continuing.")
print(f"Using Python {sys.version.split()[0]}")
PY
python3 -m venv /opt/striker/.venv
/opt/striker/.venv/bin/python -m pip install --upgrade pip
/opt/striker/.venv/bin/pip install -e .
/opt/striker/.venv/bin/playwright install --with-deps chromium

mkdir -p data/inbox data/exports data/media data/screenshots data/maps data/tmp /opt/striker-backups
if [ ! -f .env ]; then
  cp .env.example .env
fi

cat <<'EOF'
Bootstrap complete.
Next commands:
  /opt/striker/.venv/bin/python -m app.cli make-password-hash
  /opt/striker/.venv/bin/python -m app.cli telegram-login
  sudo cp scripts/deploy/striker-*.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now striker-web striker-collector striker-worker
EOF
