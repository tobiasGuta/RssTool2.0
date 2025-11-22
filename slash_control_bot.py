import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
import requests
from discord.ui import Select, View, Button
import asyncio
from dotenv import load_dotenv

load_dotenv()

CONFIG_FILE = "feeds_config.json"
DEFAULT_CATEGORY = "General"
BOT_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("Discord")
if not BOT_TOKEN:
    raise ValueError(" Discord token not set. Please set DISCORD_TOKEN in .env file")

MAX_LEN = 1900

def resolve_youtube_feed_url(handle_or_url):
    # Normalize handle input
    if handle_or_url.startswith("@"):
        handle = handle_or_url[1:]
    else:
        # Try extracting handle from full URL if possible
        m = re.match(r"https?://www\.youtube\.com/(@[\w\d_-]+)", handle_or_url)
        if m:
            handle = m.group(1)[1:]
        else:
            # If looks like a full feed URL, just return it as-is
            if "youtube.com/feeds/videos.xml?channel_id=" in handle_or_url:
                return handle_or_url
            # Otherwise fail
            raise ValueError(" Input isn't a valid handle or feed URL")

    # Query the YouTube search page filtered to channels only
    search_url = f"https://www.youtube.com/results?search_query={handle}"  # channels only filter
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                      " Chrome/90.0.4430.85 Safari/537.36"
    }
    res = requests.get(search_url, headers=headers, timeout=8)
    if res.status_code != 200:
        raise ValueError(f" YouTube search page request failed with status {res.status_code}")

    html = res.text

    # Extract ytInitialData JSON from the page
    initial_data_match = re.search(r"ytInitialData\s*=\s*({.*?});</script>", html, re.DOTALL)
    if not initial_data_match:
        # Sometimes ytInitialData ends with '};' instead of '};</script>'
        initial_data_match = re.search(r"ytInitialData\s*=\s*({.*?});", html, re.DOTALL)
        if not initial_data_match:
            raise ValueError(" Couldn't find ytInitialData JSON in search page")

    yt_initial_data = initial_data_match.group(1)

    try:
        data = json.loads(yt_initial_data)
    except json.JSONDecodeError as e:
        raise ValueError(f" Failed to parse ytInitialData JSON: {e}")

    # Navigate through the JSON to find the channelId of the first channel matching the handle
    try:
        sections = data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"]["sectionListRenderer"]["contents"]

        for section in sections:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                channel = item.get("channelRenderer")
                if channel:
                    channel_id = channel.get("channelId")
                    # Check if this channel’s customUrl or title matches the handle
                    custom_url = channel.get("customUrl", "")
                    title = channel.get("title", {}).get("runs", [{}])[0].get("text", "")

                    if custom_url.lower() == handle.lower() or title.lower() == handle.lower():
                        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

        # If none match perfectly, fallback to first found channel
        for section in sections:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                channel = item.get("channelRenderer")
                if channel:
                    channel_id = channel.get("channelId")
                    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    except Exception as e:
        raise ValueError(f" Error parsing channels: {e}")

    raise ValueError(" No YouTube channel found for that handle")


class ChannelSelect(Select):
    def __init__(self, channels, on_select_callback):
        # channels is list of tuples (channel_name, feed_url)
        options = [
            discord.SelectOption(label=name, description=url[:100], value=url)
            for name, url in channels
        ]
        super().__init__(placeholder="Select a YouTube channel", options=options, min_values=1, max_values=1)
        self.on_select_callback = on_select_callback

    async def callback(self, interaction: discord.Interaction):
        selected_url = self.values[0]
        await self.on_select_callback(interaction, selected_url)
        self.view.stop()

class ChannelSelectView(View):
    def __init__(self, channels, on_select_callback):
        super().__init__(timeout=60)
        self.add_item(ChannelSelect(channels, on_select_callback))

def get_youtube_channel_name(channel_id):
    url = f"https://www.youtube.com/channel/{channel_id}"
    try:
        res = requests.get(url, timeout=6)
        # Extract channel name from <title> tag
        match = re.search(r'<title>(.*?) - YouTube</title>', res.text)
        if match:
            return match.group(1)
        return "YouTube Channel"
    except Exception:
        return "YouTube Channel"

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

@bot.event
async def on_ready():
    print(f"[+] Logged in as {bot.user} (ID: {bot.user.id})")

    try:
        synced = await bot.tree.sync()
        print(f"[+] Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"[ERROR] Sync failed: {e}")

async def send_long_message(interaction, content):
    lines = content.split('\n')
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > MAX_LEN:
            await interaction.followup.send(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await interaction.followup.send(chunk)

class ConfirmAddView(View):
    def __init__(self, channel_name, url, on_confirm):
        super().__init__(timeout=30)
        self.url = url
        self.channel_name = channel_name
        self.on_confirm = on_confirm

    @discord.ui.button(label=" Confirm", style=discord.ButtonStyle.green, custom_id="confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_confirm(interaction, self.url, self.channel_name)
        self.stop()

    @discord.ui.button(label=" Cancel", style=discord.ButtonStyle.red, custom_id="cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=" Cancelled.", embed=None, view=None)
        self.stop()

# /rss_list command: lists feeds in this channel
@bot.tree.command(name="rss_list", description="List feeds in this channel")
async def rss_list(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    config = load_config()
    feed_count = 0

    webhooks = await interaction.channel.webhooks()
    channel_whs = [wh.url for wh in webhooks if wh.user == interaction.guild.me]

    msg = ""
    for url, entry in config.items():
        if entry["webhook"] in channel_whs:
            if "youtube.com/feeds/videos.xml?channel_id=" in url:
                channel_id = re.search(r"channel_id=([^&]+)", url).group(1)
                channel_name = get_youtube_channel_name(channel_id)
                msg += f"• **{entry.get('category', 'Unknown')}** → {channel_name} ({url})\n"
            else:
                msg += f"• **{entry.get('category', 'Unknown')}** → {url}\n"
            feed_count += 1

    if feed_count == 0:
        await interaction.followup.send(" No feeds configured in this channel.")
    else:
        await send_long_message(interaction, f"📡 **Feeds in {interaction.channel.mention}:**\n{msg}")

async def search_youtube_channels_no_browser_async(query, max_results=5):
    query = query.replace(' ', '+')
    url = f"https://www.youtube.com/results?search_query={query}&sp=EgIQAg%3D%3D"  # filter to channels only

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/113.0.0.0 Safari/537.36',
    }

    # Run blocking request in executor for async compatibility
    loop = asyncio.get_running_loop()
    def fetch():
        import requests
        return requests.get(url, headers=headers, timeout=8).text

    try:
        html = await loop.run_in_executor(None, fetch)
    except Exception as e:
        raise ValueError(f" YouTube request error: {e}")

    try:
        import json, re
        initial_data_match = re.search(r'var ytInitialData = ({.*?});</script>', html, re.DOTALL)
        if not initial_data_match:
            initial_data_match = re.search(r'window\["ytInitialData"\] = ({.*?});', html, re.DOTALL)
        if not initial_data_match:
            raise ValueError(" Could not find ytInitialData JSON on page")

        initial_data = initial_data_match.group(1)
        data = json.loads(initial_data)
    except Exception as e:
        raise ValueError(f" Failed to extract initial data: {e}")

    channels = []

    try:
        sections = data.get('contents', {}) \
                       .get('twoColumnSearchResultsRenderer', {}) \
                       .get('primaryContents', {}) \
                       .get('sectionListRenderer', {}) \
                       .get('contents', [])

        for section in sections:
            item_section = section.get('itemSectionRenderer', {})
            items = item_section.get('contents', [])
            for item in items:
                channel = item.get('channelRenderer')
                if channel:
                    name = None
                    title_obj = channel.get('title')
                    if title_obj:
                        runs = title_obj.get('runs')
                        if runs and len(runs) > 0:
                            name = runs[0].get('text')
                        else:
                            name = title_obj.get('simpleText')
                    if not name:
                        continue

                    channel_id = channel.get('channelId')

                    url = None
                    if 'navigationEndpoint' in channel and 'browseEndpoint' in channel['navigationEndpoint']:
                        browse = channel['navigationEndpoint']['browseEndpoint']
                        if 'canonicalBaseUrl' in browse:
                            url = "https://www.youtube.com" + browse['canonicalBaseUrl']
                        elif 'browseId' in browse:
                            url = "https://www.youtube.com/channel/" + browse['browseId']
                    if not url and channel_id:
                        url = f"https://www.youtube.com/channel/{channel_id}"

                    desc_runs = channel.get('descriptionSnippet', {}).get('runs', [])
                    description = ''.join([run.get('text', '') for run in desc_runs]) if desc_runs else "No description available."

                    channels.append((name, url, channel_id, description))

                    if len(channels) >= max_results:
                        break
            if len(channels) >= max_results:
                break

    except Exception as e:
        raise ValueError(f" Failed parsing channels JSON: {e}")

    return channels

@bot.tree.command(name="rss_add", description="Add an RSS or YouTube feed to this channel")
@app_commands.describe(url="The RSS feed URL or YouTube handle to monitor")
async def rss_add(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)
    config = load_config()
    category = DEFAULT_CATEGORY

    # Detect YouTube handle or URL
    if url.startswith("@") or "youtube.com" in url:
        query = url.lstrip("@")

        try:
            channels = await search_youtube_channels_no_browser_async(query)
            if not channels:
                await interaction.followup.send(" No YouTube channels found with that handle or name.")
                return

            async def on_channel_selected(inter, selected_url):
                channel_id = re.search(r"channel_id=([^&]+)", selected_url).group(1)
                channel_name = get_youtube_channel_name(channel_id)

                webhooks = await inter.channel.webhooks()
                wh = next((w for w in webhooks if w.user == inter.guild.me), None)
                if not wh:
                    wh = await inter.channel.create_webhook(name="RSSBot")

                config[selected_url] = {
                    "category": "YouTube",
                    "webhook": wh.url
                }
                save_config(config)

                await inter.response.edit_message(content=f" Added YouTube feed: **{channel_name}**\n→ `{selected_url}`", view=None, embed=None)

            # Build ChannelSelectView options from new data:
            options = []
            for name, url_, channel_id, desc in channels:
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                options.append((name, feed_url))

            view = ChannelSelectView(options, on_channel_selected)
            await interaction.followup.send("Select the YouTube channel you want to add:", view=view)

        except Exception as e:
            await interaction.followup.send(f" Could not resolve YouTube channel: {e}")
        return

    # Existing RSS handling code remains...
    webhooks = await interaction.channel.webhooks()
    wh = next((w for w in webhooks if w.user == interaction.guild.me), None)
    if not wh:
        wh = await interaction.channel.create_webhook(name="RSSBot")

    config[url] = {
        "category": "RSS",
        "webhook": wh.url
    }
    save_config(config)
    await interaction.followup.send(f" Added RSS feed:\n→ `{url}`")


# /rss_remove command: remove a feed by URL
@bot.tree.command(name="rss_remove", description="Remove a feed from this channel")
@app_commands.describe(url="The RSS feed URL to remove")
async def rss_remove(interaction: discord.Interaction, url: str):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    config = load_config()
    webhooks = await interaction.channel.webhooks()
    channel_whs = [wh.url for wh in webhooks if wh.user == interaction.guild.me]

    if url in config and config[url]["webhook"] in channel_whs:
        del config[url]
        save_config(config)
        await interaction.followup.send(f" Removed feed:\n• `{url}` from {interaction.channel.mention}")
    else:
        await interaction.followup.send(" Feed not found in this channel.")

# Twitch commands

@bot.tree.command(name="twitch_add", description="Add a Twitch streamer to monitor in this channel")
@app_commands.describe(channel="Twitch username (no URL, just the name)")
async def twitch_add(interaction: discord.Interaction, channel: str):
    config = load_config()

    try:
        webhooks = await interaction.channel.webhooks()
        wh = next((w for w in webhooks if w.user == interaction.guild.me), None)
        if not wh:
            wh = await interaction.channel.create_webhook(name="RSSBot")

        key = f"twitch:{channel}"
        config[key] = {
            "category": "Twitch",
            "webhook": wh.url
        }
        save_config(config)

        await interaction.response.send_message(
            f" Twitch feed added:\n• `{key}` → {interaction.channel.mention}",
            ephemeral=True
        )

    except discord.HTTPException as e:
        print(f"[HTTP ERROR] {e.status} - {e.text}")
        if not interaction.response.is_done():
            await interaction.response.send_message(" HTTP error occurred.", ephemeral=True)

    except Exception as e:
        print(f"[FATAL] twitch_add error: {type(e).__name__} - {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(" Internal error occurred.", ephemeral=True)

@bot.tree.command(name="twitch_list", description="List Twitch feeds in this channel")
async def twitch_list(interaction: discord.Interaction):
    config = load_config()
    webhooks = await interaction.channel.webhooks()
    channel_whs = [wh.url for wh in webhooks if wh.user == interaction.guild.me]

    msg = ""
    count = 0
    for key, entry in config.items():
        if key.startswith("twitch:") and entry["webhook"] in channel_whs:
            msg += f"• `{key}`\n"
            count += 1

    if count == 0:
        await interaction.response.send_message(" No Twitch feeds in this channel.", ephemeral=True)
    else:
        await interaction.response.send_message(f" **Twitch Feeds in {interaction.channel.mention}:**\n{msg}", ephemeral=True)

@bot.tree.command(name="twitch_remove", description="Remove a Twitch feed from this channel")
@app_commands.describe(channel="Twitch username to remove")
async def twitch_remove(interaction: discord.Interaction, channel: str):
    config = load_config()
    key = f"twitch:{channel}"
    webhooks = await interaction.channel.webhooks()
    channel_whs = [wh.url for wh in webhooks if wh.user == interaction.guild.me]

    if key in config and config[key]["webhook"] in channel_whs:
        del config[key]
        save_config(config)
        await interaction.response.send_message(f" Removed Twitch feed: `{key}`", ephemeral=True)
    else:
        await interaction.response.send_message(" Twitch feed not found in this channel.", ephemeral=True)

bot.run(BOT_TOKEN)
