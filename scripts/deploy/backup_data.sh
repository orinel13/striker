#!/usr/bin/env bash
set -euo pipefail
cd /opt/striker
mkdir -p /opt/striker-backups
name="/opt/striker-backups/striker-backup-$(date +%F_%H-%M-%S).tar.gz"
tar -czf "$name" .env data/osint.sqlite3 data/telegram.session data/inbox data/exports data/media data/screenshots data/maps 2>/dev/null || true
echo "$name"

