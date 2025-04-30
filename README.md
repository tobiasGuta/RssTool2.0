# RssTool2.0
RSSBot Elite delivers real-time RSS and YouTube feed notifications across multiple Discord channels, each with custom categories and smart webhook routing.

## 🚀 Key Features
- Multi-Channel Feed Routing – Assign specific feeds to specific Discord channels using webhooks.

- Web UI Dashboard – Add, view, and remove feeds from a clean Tailwind-powered interface.

- Discord Slash Command Control – Manage feeds directly in Discord with /rss list, /rss add, /rss remove.

- Smart Webhook Reuse – Automatically detects existing webhooks to avoid clutter.

- YouTube Integration – Add YouTube channel feeds using native RSS and get notified on uploads.

- Duplicate Prevention – Avoid reposts with hash-based tracking of feed entries.

- Live JSON Reloading – No restart required when feeds are added or removed.

- Systemd Ready – Built to run 24/7 on a VPS with background service support.

## 🛠️ Example Use Case
- Push CTF writeups to #ctf

- Send vuln news to #cyber-news

- Post YouTube uploads from LiveOverflow to #youtube-drops

- Control feeds with Discord slash commands 

## ⚙️ Setup
- This bot is plug-and-play. The only thing you need to insert manually is your Discord bot token.

Use Environment Variables:

```bash
export DISCORD_BOT_TOKEN="your-token"
```

## 🔧 Inside rss.py:

```bash
CHECK_INTERVAL = 125  # ⏱️ How often to check feeds (in seconds) – you can change this
```

With your actual bot token from the Discord Developer Portal.

## ✅ That's It.
Once the token is set, you can:

- Add feeds via the Web UI or Discord

- Start both bots with python3 rss.py and python3 slash_control_bot.py

- Run 24/7 via systemd if desired

## Examples:
### Web

![image](https://github.com/user-attachments/assets/5f8cfabc-15c6-4c93-bd85-7856a5d14e38)

### Discord

- /rss_list 

- /rss_add

- /rss_delete

![Screenshot 2025-04-30 140458](https://github.com/user-attachments/assets/9313ca2c-d9fe-402d-a9ac-70473400173c)


