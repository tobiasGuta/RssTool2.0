"""
slash_control_bot.py — Discord slash-command management bot for RssTool2.0

Bug fixes applied:
  • get_youtube_channel_name now runs in executor (no event-loop blocking)
  • Removed dead code: resolve_youtube_feed_url(), ConfirmAddView
  • All slash commands require manage_channels permission
  • aiohttp ClientTimeout used (not bare int)
  • Redundant imports inside functions removed
  • on_app_command_error handler added for clean user-facing errors

Improvements added:
  • SQLite via db.py (atomic, no JSON corruption risk)
  • /rss_pause, /rss_resume commands
  • /rss_keywords command (set/clear keyword filters per feed)
  • /rss_status shows feed health table
  • /rss_add accepts category and keywords arguments
  • /rss_list shows pause state and keywords
  • Webhook helper function deduplicates webhook logic
"""

import discord
from discord.ext import commands
from discord import app_commands
import re
import os
import asyncio
import aiohttp
from aiohttp import ClientTimeout
from dotenv import load_dotenv
import db

load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("Discord")
if not BOT_TOKEN:
    raise ValueError("Discord token not set. Add DISCORD_TOKEN to your .env file.")

MAX_LEN          = 1900
DEFAULT_CATEGORY = "General"
REQUEST_TIMEOUT  = ClientTimeout(total=10)
WEBHOOK_NAME = os.getenv("WEBHOOK_NAME", "RssTool2.0")
WEBHOOK_AVATAR_PATH = os.getenv("WEBHOOK_AVATAR_PATH", "avatar.png")

intents        = discord.Intents.default()
intents.guilds = True
bot            = commands.Bot(command_prefix="!", intents=intents)


def _get_db():
    return db.get_connection()


def _get_youtube_channel_name_sync(channel_id: str) -> str:
    """Synchronous HTTP call — always run via run_in_executor."""
    import requests
    try:
        res = requests.get(
            f"https://www.youtube.com/channel/{channel_id}", timeout=6
        )
        m = re.search(r"<title>(.*?) - YouTube</title>", res.text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "YouTube Channel"


async def _search_youtube_channels(query: str, max_results: int = 5) -> list:
    import json as _json
    encoded = query.replace(" ", "+")
    url     = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAg%3D%3D"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/113.0.0.0 Safari/537.36"
        )
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as resp:
            html = await resp.text()

    m = re.search(r"var ytInitialData = ({.*?});</script>", html, re.DOTALL)
    if not m:
        m = re.search(r'window\["ytInitialData"\] = ({.*?});', html, re.DOTALL)
    if not m:
        raise ValueError("Could not extract YouTube data from page.")

    data     = _json.loads(m.group(1))
    sections = (
        data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
    )
    channels = []
    for section in sections:
        for item in section.get("itemSectionRenderer", {}).get("contents", []):
            ch = item.get("channelRenderer")
            if not ch:
                continue
            title_obj = ch.get("title", {})
            name = (
                (title_obj.get("runs") or [{}])[0].get("text")
                or title_obj.get("simpleText", "")
            )
            if not name:
                continue
            cid  = ch.get("channelId", "")
            desc = "".join(
                r.get("text", "")
                for r in ch.get("descriptionSnippet", {}).get("runs", [])
            ) or "No description"
            channels.append((name, cid, desc))
            if len(channels) >= max_results:
                break
        if len(channels) >= max_results:
            break
    return channels


async def _get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook:
    webhooks = await channel.webhooks()
    wh = next((w for w in webhooks if w.user == channel.guild.me), None)
    if not wh:
        avatar_bytes = None
        if os.path.exists(WEBHOOK_AVATAR_PATH):
            with open(WEBHOOK_AVATAR_PATH, "rb") as f:
                avatar_bytes = f.read()
        else:
            print(f"Warning: Webhook avatar file not found at {WEBHOOK_AVATAR_PATH}")
            
        wh = await channel.create_webhook(name=WEBHOOK_NAME, avatar=avatar_bytes)
    return wh


async def _send_long(interaction: discord.Interaction, content: str):
    chunk = ""
    for line in content.split("\n"):
        if len(chunk) + len(line) + 1 > MAX_LEN:
            await interaction.followup.send(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await interaction.followup.send(chunk)


class _ChannelSelect(discord.ui.Select):
    def __init__(self, channels: list, callback):
        options = [
            discord.SelectOption(label=name[:100], description=desc[:100], value=cid)
            for name, cid, desc in channels
        ]
        super().__init__(placeholder="Select a YouTube channel", options=options,
                         min_values=1, max_values=1)
        self._cb = callback

    async def callback(self, interaction: discord.Interaction):
        await self._cb(interaction, self.values[0])
        self.view.stop()


class _ChannelSelectView(discord.ui.View):
    def __init__(self, channels: list, callback):
        super().__init__(timeout=60)
        self.add_item(_ChannelSelect(channels, callback))


@bot.event
async def on_ready():
    print(f"[+] Logged in as {bot.user} (ID: {bot.user.id})")
    db.init_db()
    try:
        synced = await bot.tree.sync()
        print(f"[+] Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"[ERROR] Command sync failed: {e}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need **Manage Channels** permission to use this command."
    else:
        msg = f"Error: {error}"
    if interaction.response.is_done():
        await interaction.followup.send(f"❌ {msg}", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {msg}", ephemeral=True)


@bot.tree.command(name="rss_list", description="List all feeds in this channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def rss_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    conn     = _get_db()
    feeds    = db.get_all_feeds(conn)
    webhooks = await interaction.channel.webhooks()
    ch_whs   = {wh.url for wh in webhooks if wh.user == interaction.guild.me}
    loop     = asyncio.get_running_loop()

    lines = []
    for feed in feeds:
        if feed["webhook"] not in ch_whs:
            continue
        status = "✅" if feed["enabled"] else "⏸️"
        kw     = f"  🔍 `{feed['keywords']}`" if feed["keywords"] else ""
        if "youtube.com/feeds/videos.xml?channel_id=" in feed["url"]:
            cid  = re.search(r"channel_id=([^&]+)", feed["url"]).group(1)
            name = await loop.run_in_executor(None, _get_youtube_channel_name_sync, cid)
            lines.append(f"{status} **{feed['category']}** → {name}{kw}")
        else:
            lines.append(f"{status} **{feed['category']}** → `{feed['url']}`{kw}")

    if not lines:
        await interaction.followup.send("No feeds configured in this channel.")
    else:
        await _send_long(interaction,
            f"📡 **Feeds in {interaction.channel.mention}** ({len(lines)} total):\n"
            + "\n".join(lines))


@bot.tree.command(name="rss_add", description="Add an RSS or YouTube feed to this channel")
@app_commands.describe(
    url="RSS feed URL or YouTube handle (e.g. @mkbhd)",
    category="Category label (default: General)",
    keywords="Comma-separated keywords to filter articles (optional)",
)
@app_commands.checks.has_permissions(manage_channels=True)
async def rss_add(interaction: discord.Interaction, url: str,
                  category: str = DEFAULT_CATEGORY, keywords: str = ""):
    await interaction.response.defer(ephemeral=True)
    conn = _get_db()

    is_channel_id = (
        not url.startswith("http") and
        not url.startswith("@") and
        " " not in url and
        re.match(r'^[A-Za-z0-9_-]{20,30}$', url)
    )

    if is_channel_id:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={url}"
        wh = await _get_or_create_webhook(interaction.channel)
        db.add_feed(conn, feed_url, wh.url, category="YouTube", keywords=keywords)
        await interaction.followup.send(f"✅ Added YouTube channel ID: **{url}** → feed saved.")
        return

    # If it's not an http link, or it is a youtube link but not a feed link, try to search it
    is_youtube_search = (
        not url.startswith("http") or 
        ("youtube.com" in url and "youtube.com/feeds/videos.xml" not in url)
    )

    if is_youtube_search:
        query = url.lstrip("@")
        try:
            channels = await _search_youtube_channels(query)
            if not channels:
                await interaction.followup.send("❌ No YouTube channels found.")
                return

            async def _on_select(inter: discord.Interaction, channel_id: str):
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                loop     = asyncio.get_running_loop()
                name     = await loop.run_in_executor(
                    None, _get_youtube_channel_name_sync, channel_id)
                wh = await _get_or_create_webhook(inter.channel)
                db.add_feed(conn, feed_url, wh.url, category="YouTube", keywords=keywords)
                await inter.response.edit_message(
                    content=f"✅ Added YouTube feed: **{name}**\n→ `{feed_url}`",
                    view=None)

            await interaction.followup.send(
                "Select the YouTube channel to add:",
                view=_ChannelSelectView(channels, _on_select))
        except Exception as e:
            await interaction.followup.send(f"❌ Could not resolve YouTube channel: {e}")
        return

    wh = await _get_or_create_webhook(interaction.channel)
    db.add_feed(conn, url, wh.url, category=category, keywords=keywords)
    suffix = f"\n🔍 Keywords: `{keywords}`" if keywords else ""
    await interaction.followup.send(
        f"✅ Added RSS feed:\n→ `{url}`\n📂 Category: **{category}**{suffix}")


async def rss_remove_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    conn = _get_db()
    feeds = db.get_all_feeds(conn)
    try:
        webhooks = await interaction.channel.webhooks()
        ch_whs = {wh.url for wh in webhooks if wh.user == interaction.guild.me}
    except Exception:
        ch_whs = set()
    
    channel_feeds = [f["url"] for f in feeds if f["webhook"] in ch_whs]
    matching = [url for url in channel_feeds if current.lower() in url.lower()]
    return [app_commands.Choice(name=url[:100], value=url) for url in matching][:25]


@bot.tree.command(name="rss_remove", description="Remove a feed from this channel")
@app_commands.describe(url="The RSS feed URL to remove")
@app_commands.autocomplete(url=rss_remove_autocomplete)
@app_commands.checks.has_permissions(manage_channels=True)
async def rss_remove(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)
    conn     = _get_db()
    feed     = db.get_feed(conn, url)
    webhooks = await interaction.channel.webhooks()
    ch_whs   = {wh.url for wh in webhooks if wh.user == interaction.guild.me}

    if feed and feed["webhook"] in ch_whs:
        db.remove_feed(conn, url)
        await interaction.followup.send(f"✅ Removed: `{url}`")
    else:
        await interaction.followup.send("❌ Feed not found in this channel.")


@bot.tree.command(name="rss_pause", description="Pause a feed (stops alerts, keeps config)")
@app_commands.describe(url="Feed URL to pause")
@app_commands.checks.has_permissions(manage_channels=True)
async def rss_pause(interaction: discord.Interaction, url: str):
    db.toggle_feed(_get_db(), url, enabled=False)
    await interaction.response.send_message(f"⏸️ Paused: `{url}`", ephemeral=True)


@bot.tree.command(name="rss_resume", description="Resume a paused feed")
@app_commands.describe(url="Feed URL to resume")
@app_commands.checks.has_permissions(manage_channels=True)
async def rss_resume(interaction: discord.Interaction, url: str):
    db.toggle_feed(_get_db(), url, enabled=True)
    await interaction.response.send_message(f"▶️ Resumed: `{url}`", ephemeral=True)


@bot.tree.command(name="rss_keywords", description="Set or clear keyword filter for a feed")
@app_commands.describe(
    url="Feed URL to update",
    keywords="Comma-separated keywords (empty to remove filter)",
)
@app_commands.checks.has_permissions(manage_channels=True)
async def rss_keywords(interaction: discord.Interaction, url: str, keywords: str = ""):
    db.update_feed_keywords(_get_db(), url, keywords)
    msg = (f"🔍 Keywords set for `{url}`:\n`{keywords}`" if keywords
           else f"🔍 Keyword filter cleared for `{url}`")
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="rss_status", description="Show health status of all feeds")
@app_commands.checks.has_permissions(manage_channels=True)
async def rss_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    health = db.get_feed_health(_get_db())
    if not health:
        await interaction.followup.send(
            "No health data yet — let the bot complete at least one check cycle.")
        return
    lines = ["**📊 Feed Health Report:**"]
    for row in health:
        icon = "✅" if row["fail_count"] == 0 else ("⚠️" if row["fail_count"] < 5 else "❌")
        lines.append(f"{icon} `{row['url'][:60]}` — failures: **{row['fail_count']}**")
        if row["last_error"]:
            lines.append(f"    └ _{str(row['last_error'])[:100]}_")
    await _send_long(interaction, "\n".join(lines))


@bot.tree.command(name="twitch_add", description="Monitor a Twitch streamer in this channel")
@app_commands.describe(channel="Twitch username")
@app_commands.checks.has_permissions(manage_channels=True)
async def twitch_add(interaction: discord.Interaction, channel: str):
    await interaction.response.defer(ephemeral=True)
    wh = await _get_or_create_webhook(interaction.channel)
    db.add_feed(_get_db(), f"twitch:{channel}", wh.url, category="Twitch")
    await interaction.followup.send(f"✅ Twitch monitor added: **{channel}**")


@bot.tree.command(name="twitch_list", description="List Twitch streams in this channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def twitch_list(interaction: discord.Interaction):
    conn     = _get_db()
    feeds    = db.get_all_feeds(conn)
    webhooks = await interaction.channel.webhooks()
    ch_whs   = {wh.url for wh in webhooks if wh.user == interaction.guild.me}
    lines    = [
        f"{'✅' if f['enabled'] else '⏸️'} `{f['url'].split('twitch:')[1]}`"
        for f in feeds
        if f["url"].startswith("twitch:") and f["webhook"] in ch_whs
    ]
    if not lines:
        await interaction.response.send_message("No Twitch feeds here.", ephemeral=True)
    else:
        await interaction.response.send_message(
            f"🟣 **Twitch Feeds:**\n" + "\n".join(lines), ephemeral=True)


@bot.tree.command(name="twitch_remove", description="Remove a Twitch stream from this channel")
@app_commands.describe(channel="Twitch username to remove")
@app_commands.checks.has_permissions(manage_channels=True)
async def twitch_remove(interaction: discord.Interaction, channel: str):
    conn     = _get_db()
    key      = f"twitch:{channel}"
    feed     = db.get_feed(conn, key)
    webhooks = await interaction.channel.webhooks()
    ch_whs   = {wh.url for wh in webhooks if wh.user == interaction.guild.me}
    if feed and feed["webhook"] in ch_whs:
        db.remove_feed(conn, key)
        await interaction.response.send_message(f"✅ Removed: **{channel}**", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Not found in this channel.", ephemeral=True)


@bot.tree.command(name="twitch_pause", description="Pause Twitch alerts for a streamer")
@app_commands.describe(channel="Twitch username")
@app_commands.checks.has_permissions(manage_channels=True)
async def twitch_pause(interaction: discord.Interaction, channel: str):
    db.toggle_feed(_get_db(), f"twitch:{channel}", enabled=False)
    await interaction.response.send_message(f"⏸️ Paused: **{channel}**", ephemeral=True)


@bot.tree.command(name="twitch_resume", description="Resume Twitch alerts for a streamer")
@app_commands.describe(channel="Twitch username")
@app_commands.checks.has_permissions(manage_channels=True)
async def twitch_resume(interaction: discord.Interaction, channel: str):
    db.toggle_feed(_get_db(), f"twitch:{channel}", enabled=True)
    await interaction.response.send_message(f"▶️ Resumed: **{channel}**", ephemeral=True)


bot.run(BOT_TOKEN)
