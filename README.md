# RssTool2.0

A Discord-integrated RSS + Twitch monitor with a local web dashboard, managed via Discord slash commands. Accessible from any device on your local network.

---

## Quick Start

### 1. Clone & install
```bash
git clone https://github.com/tobiasGuta/RssTool2.0.git
cd RssTool2.0
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env and set DISCORD_TOKEN at minimum
```

### 3. Run
```bash
python start.py
```

The supervisor starts all three services:
- **RSS Alerts** — polls feeds and sends Discord messages
- **Discord Bot** — slash commands for managing feeds
- **Dashboard** — web UI at http://localhost:8080

---

## Docker (recommended for always-on use)

```bash
cp .env.example .env
# Edit .env

docker compose up -d
```

Dashboard: http://localhost:8080

---

## Access from Phone / Other Devices

1. Find your local IP:
   - **Linux/Mac:** `ip route get 1 | awk '{print $7}'`
   - **Windows:** `ipconfig | findstr "IPv4"`

2. Open `http://<your-local-ip>:8080` on your phone.

> **Tip:** Set a DHCP reservation in your router for the machine running RssTool so the local IP never changes.

---

## Discord Slash Commands

All commands require **Manage Channels** permission.

| Command | Description |
|---------|-------------|
| `/rss_add <url>` | Add an RSS feed or YouTube handle |
| `/rss_remove <url>` | Remove a feed |
| `/rss_list` | List feeds in this channel |
| `/rss_pause <url>` | Pause alerts without removing the feed |
| `/rss_resume <url>` | Resume a paused feed |
| `/rss_keywords <url> <keywords>` | Set comma-separated keyword filters |
| `/rss_status` | View feed health report |
| `/twitch_add <username>` | Monitor a Twitch streamer |
| `/twitch_remove <username>` | Remove a Twitch monitor |
| `/twitch_list` | List Twitch monitors in this channel |
| `/twitch_pause <username>` | Pause Twitch alerts |
| `/twitch_resume <username>` | Resume Twitch alerts |

---

## ntfy.sh Push Notifications (optional)

Get article alerts directly on your phone via [ntfy.sh](https://ntfy.sh) — no app account needed.

1. Install the ntfy app on your phone
2. Create a topic (e.g. `my-rss-alerts`)
3. Set in `.env`:
   ```
   NTFY_URL=https://ntfy.sh/my-rss-alerts
   ```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list.

Key variables:
- `DISCORD_TOKEN` — required
- `SYSTEM_WEBHOOK_URL` — optional, for startup/shutdown pings
- `NTFY_URL` — optional, for phone push notifications
- `RSS_CHECK_INTERVAL` — default 300s (5 min)
- `DASHBOARD_HOST` — default `0.0.0.0` (LAN-accessible)
- `DASHBOARD_PORT` — default `8080`

---

## Data

All data is stored in `data/rsstool.db` (SQLite). Feeds config is migrated automatically from the legacy `feeds_config.json` on first run.

Logs are stored in `logs/rsstool.log` with automatic rotation (5MB max, 3 backups).

## Example

<img width="1532" height="453" alt="image" src="https://github.com/user-attachments/assets/0bfbb7ca-a4b4-42cd-8687-67e9cc41fa12" />

----

<img width="839" height="263" alt="image" src="https://github.com/user-attachments/assets/6c0de231-b9cb-4c31-9dca-79c7ad8bf1dc" />

----

<img width="602" height="507" alt="image" src="https://github.com/user-attachments/assets/356434e3-137a-4210-94c1-e57a8352bbed" />

----

<img width="1910" height="942" alt="image" src="https://github.com/user-attachments/assets/4835f403-821b-4886-b3de-728eaad507b6" />

----

<img width="1903" height="934" alt="image" src="https://github.com/user-attachments/assets/80948b3b-04d0-43a1-af67-f7f563564376" />

----
## Migrating from v1

If you have an existing `feeds_config.json`, place it in the project root and run the bot — it will automatically import all feeds into the database and rename the file to `feeds_config.json.migrated`.
