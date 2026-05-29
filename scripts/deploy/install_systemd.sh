#!/usr/bin/env bash
set -euo pipefail
cp /opt/striker/scripts/deploy/striker-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now striker-web striker-collector striker-worker

