# RssTool2.0
RSSBot Elite delivers real-time RSS, YouTube, and Twitch feed notifications across multiple Discord channels. It features rich embeds with images, smart descriptions, and efficient performance.

## Key Features
- **Multi-Channel Feed Routing** – Assign specific feeds to specific Discord channels using webhooks.
- **Rich Notifications** – Automatically extracts images and descriptions from articles for beautiful Discord embeds.
- **Discord Slash Command Control** – Manage feeds directly in Discord with `/rss_add`, `/rss_remove`, `/rss_list`, `/twitch_add`, etc.
- **High Performance** – Checks RSS feeds every 5 minutes and Twitch streams every 2 minutes.
- **Smart Webhook Reuse** – Automatically detects existing webhooks to avoid clutter.
- **YouTube Integration** – Add YouTube channel feeds using native RSS and get notified on uploads.
- **Twitch Integration** – Get instant notifications when your favorite streamers go live.
- **Duplicate Prevention** – Avoid reposts with hash-based tracking of feed entries.
- **Live JSON Reloading** – No restart required when feeds are added or removed.
- **Systemd Ready** – Built to run 24/7 on a VPS with background service support.

## Example Use Case
- Push CTF writeups to `#ctf`
- Send vuln news to `#cyber-news`
- Post YouTube uploads from LiveOverflow to `#youtube-drops`
- Get notified when a streamer goes live in `#streams`

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/tobiasGuta/RssTool2.0.git
   cd RssTool2.0
   ```

2. **Create a virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip3 install -r requirements.txt
   ```

4. **Configuration**
   - Copy the example environment file:
     ```bash
     cp .env.example .env
     ```
   - Edit `.env` and add your Discord Bot Token:
     ```
     DISCORD_TOKEN=your_token_here
     ```
   - (Optional) Add `SYSTEM_WEBHOOK_URL` in `.env` if you want system status notifications.

5. **Run the application**
   You can start all services (RSS Checker, Discord Bot) with a single command:
   ```bash
   python3 start.py
   ```

## Manual Run (Optional)
If you prefer to run services individually:
```bash
python3 rss_alerts.py &
python3 slash_control_bot.py
```

## Creating a Discord Bot
- Visit https://discord.com/developers/docs/intro
- Create a new application and add a bot.
- Enable **Message Content Intent** and **Server Members Intent** in the bot settings.
- Invite the bot to your server with `applications.commands` and `bot` scopes.

### Required Permissions
- **View Channels**
- **Send Messages**
- **Embed Links**
- **Manage Webhooks** (Critical: The bot creates webhooks to post updates)
- **Use Slash Commands**

## Configuration Details
- **RSS Check Interval**: 5 minutes
- **Twitch Check Interval**: 2 minutes
- **Feeds Config**: Stored in `feeds_config.json` (managed automatically via slash commands)


## That's It.
Once the token is set, you can:

- Add feeds via Discord Slash Commands

- Start the application with `python3 start.py`

- Run 24/7 via systemd if desired

## Examples:

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



