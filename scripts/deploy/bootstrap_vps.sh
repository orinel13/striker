#!/usr/bin/env bash
set -euo pipefail

apt update
apt install -y python3.11 python3.11-venv python3-pip git nginx unzip curl build-essential

if [ ! -d /opt/striker/.git ]; then
  rm -rf /opt/striker
  git clone https://github.com/orinel13/striker.git /opt/striker
fi

cd /opt/striker
python3.11 -m venv /opt/striker/.venv
/opt/striker/.venv/bin/python -m pip install --upgrade pip
/opt/striker/.venv/bin/pip install -e .
/opt/striker/.venv/bin/playwright install chromium

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

