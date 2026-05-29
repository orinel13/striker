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

## Типы отчётов

- `report.docx` — основной text-only OSINT-отчёт по Telegram-публикациям, сгруппированный по населённым пунктам. По умолчанию он не открывает Telegram через Playwright, не создаёт PNG/cards и не вставляет изображения.
- `technical_report.docx` — техническая диагностика кейсов, координат, FIRMS и scoring; используется для проверки парсинга и сопоставления.
- `evidence.zip` — пакет с `report.docx`, `report.html`, metadata и копией исходного `.docx`, если она передана в export.

По умолчанию `python -m app.cli export-report` создаёт быстрый text-only OSINT-отчёт только по `approved` и `auto_approved` публикациям текущего batch. Технический режим:

```bash
python -m app.cli export-report --style technical
```

Опциональные slow/debug режимы:

```bash
python -m app.cli export-report --with-local-cards
python -m app.cli export-report --external-screenshots
python -m app.cli export-report --include-pending
```

## Ежедневные задания / batches

Telegram archive живёт отдельно и постоянно пополняется. Каждый Word-документ создаёт отдельный batch с кейсами, матчами, review и export. Очистка batch не удаляет `channels`, `messages`, `message_keywords`, `message_places` и Telegram session.

Основные команды:

```bash
python -m app.cli list-batches
python -m app.cli show-batch 1
python -m app.cli activate-batch 1
python -m app.cli archive-batch 1
python -m app.cli delete-batch 1 --yes
python -m app.cli clear-current-batch --yes
python -m app.cli clear-all-batches --yes --keep-telegram
```

Обычный ежедневный CLI-flow:

```bash
python -m app.cli import-docx data/inbox/strikes.docx --document-date 2026-05-29
python -m app.cli match-cases
# review approved/auto_approved через /review
python -m app.cli export-report
```

## Импорт табличных актов ударов

Для актов в таблицах `.docx` сначала проверь распознавание строк без записи в базу:

```bash
python -m app.cli inspect-docx data/inbox/strikes29.docx --document-date 2026-05-20
```

Затем импортируй, сопоставь и собери отчёт:

```bash
python -m app.cli import-docx data/inbox/strikes29.docx --document-date 2026-05-20
python -m app.cli match-cases
python -m app.cli export-report
```

Если документ содержит дату без года, например `20.05`, укажи год:

```bash
python -m app.cli inspect-docx data/inbox/strikes29.docx --default-year 2026
python -m app.cli import-docx data/inbox/strikes29.docx --default-year 2026
```

Если документ вообще без даты, укажи дату суток события через `--document-date`. Координаты вида `5415616 7395885` автоматически конвертируются из СК-42/Гаусс-Крюгер в WGS84; исходные northing/easting и источник координат сохраняются в базе и отчёте.

## Импорт документов за ночь с одной даты на другую

Для календарного дня используй `--document-date`. Для ночных актов, например ночь с 28 на 29 мая, используй период:

```bash
python -m app.cli inspect-docx data/inbox/strikes.docx --period-start 2026-05-28 --period-end 2026-05-29 --night-mode
python -m app.cli import-docx data/inbox/strikes.docx --period-start 2026-05-28 --period-end 2026-05-29 --night-mode
```

В ночном режиме времена `18:00-23:59` относятся к `--period-start`, а `00:00-11:59` относятся к `--period-end`. Значение `--rollover-hour 12` означает, что все времена до 12:00 считаются утренней частью конечной даты периода.

## CLI

```bash
python -m app.cli init-db
python -m app.cli load-places
python -m app.cli make-password-hash
python -m app.cli telegram-login
python -m app.cli collect-once
python -m app.cli collect-loop
python -m app.cli worker-loop
python -m app.cli inspect-docx data/inbox/strikes.docx --document-date 2026-05-20
python -m app.cli import-docx data/inbox/strikes.docx --document-date 2026-05-20
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

## Первичный сбор Telegram-архива

`collect-latest-once` собирает последние сообщения активных каналов и выставляет курсор `last_message_id` на максимальный актуальный Telegram message id. После этого `collect-loop` добирает только новые сообщения.

Backfill старой истории должен быть отдельной задачей и не должен мешать свежему архиву. Если раньше был выполнен багованный сбор старейших сообщений, восстанови курсоры и свежую выборку:

```bash
sudo systemctl stop striker-collector striker-worker
/opt/striker/.venv/bin/python -m app.cli reset-channel-cursors --all
/opt/striker/.venv/bin/python -m app.cli collect-latest-once
/opt/striker/.venv/bin/python -m app.cli archive-stats
/opt/striker/.venv/bin/python -m app.cli reindex-message-places
/opt/striker/.venv/bin/python -m app.cli match-cases
sudo systemctl start striker-worker striker-collector
```

Полезная диагностика:

```bash
/opt/striker/.venv/bin/python -m app.cli search-archive Прилуки --date 2026-05-29
/opt/striker/.venv/bin/python -m app.cli search-archive взрыв --date 2026-05-29
/opt/striker/.venv/bin/python -m app.cli debug-match-case 1 --limit 50
/opt/striker/.venv/bin/python -m app.cli search-by-case 1 --limit 50
```

`match-cases` использует быстрый candidate-first алгоритм: сначала ограничивает сообщения SQL-окном по времени и городским alias, затем считает scoring только по кандидатам. Это должно завершаться за секунды или минуты на нескольких тысячах сообщений.

## Review и качество матчей

`match-cases` создаёт Telegram-кандидаты со статусами review:

- `auto_approved` — сильное совпадение A с прямым местом, сильным impact и близким временем.
- `pending` — кандидаты B/C, требующие ручной проверки.
- `approved` / `rejected` — ручное решение на странице `/review`.

Основной OSINT-отчёт по умолчанию включает только `approved` и `auto_approved`. Pending-кандидаты не попадают в `report.docx`, пока их не принять на `/review`.

Настройки:

```env
TELEGRAM_ARCHIVE_DAYS=3
MATCH_MAX_PER_CASE=5
```

Очистка rolling archive:

```bash
/opt/striker/.venv/bin/python -m app.cli prune-archive --days 3 --vacuum
```

## FIRMS Caveat

FIRMS shows thermal anomaly / active fire detection. FIRMS does not prove the cause of a fire. Treat it only as a contextual verification layer alongside Telegram archive data, time, place, and source evidence. If FIRMS is the only nearby evidence, reports mark it with this caveat.

## Backups

```bash
sudo bash /opt/striker/scripts/deploy/backup_data.sh
sudo bash /opt/striker/scripts/deploy/restore_data.sh /opt/striker-backups/striker-backup-YYYY-MM-DD_HH-MM-SS.tar.gz
```
