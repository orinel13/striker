#!/usr/bin/env bash
set -euo pipefail
if [ $# -ne 1 ]; then
  echo "Usage: restore_data.sh /path/to/striker-backup.tar.gz" >&2
  exit 2
fi
systemctl stop striker-web striker-collector striker-worker || true
cd /opt/striker
tar -xzf "$1" -C /opt/striker
systemctl start striker-web striker-collector striker-worker

