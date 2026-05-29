# Striker

Self-hosted retrospective OSINT archive and evidence system for documenting strikes against Ukraine. Striker is not a real-time alerting or live tracking tool. It archives Telegram channels available to the user, imports known incidents from Word documents, matches archived posts and FIRMS thermal anomaly data, then builds evidence reports.

## Local Development On Windows

```powershell
git clone https://github.com/orinel13/striker.git
cd striker
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium
copy .env.example .env
python -m app.cli init-db
```

Edit `.env`, then create the admin password hash:

```powershell
python -m app.cli make-password-hash
```

Put the printed hash into `ADMIN_PASSWORD_HASH`. Set `APP_SECRET_KEY` and `API_TOKEN` to long random values.

Run locally:

```powershell
python -m app.cli run-web
python -m app.cli worker-loop
```

## First Push

```powershell
git add .
git commit -m "Initial striker OSINT archive system"
git push origin main
```

Runtime files are ignored: `.env`, SQLite DB, Telegram sessions, inbox `.docx`, exports, screenshots, maps, media, and tokens must not be committed.

## Deploy On VPS

```bash
ssh root@VPS_IP
git clone https://github.com/orinel13/striker.git /opt/striker
cd /opt/striker
bash scripts/deploy/bootstrap_vps.sh
```

The bootstrap script uses the server default `python3` and checks that it is Python 3.11 or newer. Ubuntu 24.04/Noble usually provides Python 3.12 as `python3`, which is supported.

Configure environment:

```bash
nano /opt/striker/.env
/opt/striker/.venv/bin/python -m app.cli make-password-hash
```

Telegram login on VPS:

```bash
/opt/striker/.venv/bin/python -m app.cli telegram-login
```

Start services:

```bash
sudo cp scripts/deploy/striker-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now striker-web striker-collector striker-worker
```

Check logs:

```bash
journalctl -u striker-web -f
journalctl -u striker-collector -f
journalctl -u striker-worker -f
```

Install nginx reverse proxy:

```bash
sudo cp scripts/deploy/nginx_striker.conf /etc/nginx/sites-available/striker
sudo ln -sf /etc/nginx/sites-available/striker /etc/nginx/sites-enabled/striker
sudo nginx -t
sudo systemctl reload nginx
```

Open `http://VPS_IP/`. If you have a domain, install Certbot and issue HTTPS certificates, then set `APP_BASE_URL=https://your-domain`.

## Word Workflow From PC

Browser workflow:

1. Open `https://domain-or-ip/`.
2. Login.
3. Upload `.docx` on `/upload`.
4. Wait for the job to become `done`.
5. Download `report.docx`, `report.html`, or `evidence.zip` from `/exports`.

PowerShell workflow:

```powershell
./scripts/windows/upload-docx.ps1 -ServerUrl "https://domain-or-ip" -ApiToken "token-from-env" -FilePath "C:\Users\User\Documents\strikes.docx"
./scripts/windows/download-latest-export.ps1 -ServerUrl "https://domain-or-ip" -ApiToken "token-from-env" -OutPath "C:\Users\User\Downloads\evidence.zip"
./scripts/windows/open-striker-ui.ps1 -ServerUrl "https://domain-or-ip"
```

## CLI

```bash
python -m app.cli init-db
python -m app.cli load-places
python -m app.cli make-password-hash
python -m app.cli telegram-login
python -m app.cli collect-once
python -m app.cli collect-loop
python -m app.cli worker-loop
python -m app.cli import-docx data/inbox/strikes.docx
python -m app.cli fetch-firms
python -m app.cli match-cases
python -m app.cli render-evidence
python -m app.cli export-report
python -m app.cli run-web
python -m app.cli approve-channel channel_username
python -m app.cli reject-channel channel_username
python -m app.cli create-job-from-docx data/inbox/strikes.docx
python -m app.cli cleanup-exports
```

## Telegram Flood Wait

Do not run aggressive global searches. Archive channels gradually from `data/seed_channels.txt` and approved candidates. Striker handles `FloodWaitError`, sleeps, logs per-channel errors, and continues with other channels.

## FIRMS Caveat

FIRMS shows thermal anomaly / active fire detection. FIRMS does not prove the cause of a fire. Treat it only as a contextual verification layer alongside Telegram archive data, time, place, and source evidence. If FIRMS is the only nearby evidence, reports mark it with this caveat.

## Backups

```bash
sudo bash /opt/striker/scripts/deploy/backup_data.sh
sudo bash /opt/striker/scripts/deploy/restore_data.sh /opt/striker-backups/striker-backup-YYYY-MM-DD_HH-MM-SS.tar.gz
```
