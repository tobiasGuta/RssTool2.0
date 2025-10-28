# RssTool2.0
RSSBot Elite delivers real-time RSS and YouTube, Twitch feed notifications across multiple Discord channels, each with custom categories and smart webhook routing.

## Key Features
- Multi-Channel Feed Routing – Assign specific feeds to specific Discord channels using webhooks.

- Web UI Dashboard – Add, view, and remove feeds from a clean Tailwind-powered interface.

- Discord Slash Command Control – Manage feeds directly in Discord with /rss list, /rss add, /rss remove.

- Smart Webhook Reuse – Automatically detects existing webhooks to avoid clutter.

- YouTube Integration – Add YouTube channel feeds using native RSS and get notified on uploads.

- Twitch Integration - Add Twitch channel and get notified

- Duplicate Prevention – Avoid reposts with hash-based tracking of feed entries.

- Live JSON Reloading – No restart required when feeds are added or removed.

- Systemd Ready – Built to run 24/7 on a VPS with background service support.

## Example Use Case
- Push CTF writeups to #ctf

- Send vuln news to #cyber-news

- Post YouTube uploads from LiveOverflow to #youtube-drops

- Control feeds with Discord slash commands 

## Setup

```bash
python3 -m venv venv
```

```bash
source venv/bin/activate
```

```bash
pip3 install -r requirements.txt
```

- Visit https://discord.com/developers/docs/intro

- You need to create your own bot. You can use this as a guide: https://www.codedex.io/projects/build-a-discord-bot-with-python

Use Environment Variables:

```bash
export Discord="your-token"
```

**Note**: With your actual bot token from the Discord Developer Portal.

## Inside rss_alerts.py:

```bash
CHECK_INTERVAL = 125  #  How often to check feeds (in seconds) – you can change this
```

## That's It.
Once the token is set, you can:

- Add feeds via the Web UI or Discord Channels

- Start both bots with python3 rss_alerts.py and python3 slash_control_bot.py

- Run 24/7 via systemd if desired

## Examples:
### Web

![image](https://github.com/user-attachments/assets/5f8cfabc-15c6-4c93-bd85-7856a5d14e38)

### Discord

- /rss_list

- /rss_add <url>

- /rss_delete <url>

### Youtube :movie_camera:

/rss_add url:@Channelname

![image](https://github.com/user-attachments/assets/dc582e9f-a185-408a-a469-ced0d840ef1b)

### Article :newspaper: 
/rss_add url:https://projectdiscovery.io/rss.xml

![image](https://github.com/user-attachments/assets/5046ee90-87b1-44e7-a159-d856be18942d)

### Twitch :movie_camera:

- /twitch_add <username>

- /twitch_list

- /twitch_remove <username>

![image](https://github.com/user-attachments/assets/d6468a94-2f8a-427f-adbc-9533e4d23418)



