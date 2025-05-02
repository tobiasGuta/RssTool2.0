import discord
from discord.ext import commands
from discord import app_commands
import json
import os

CONFIG_FILE = "feeds_config.json"
DEFAULT_CATEGORY = "General"
BOT_TOKEN = os.getenv("Discord")

if not BOT_TOKEN:
    raise ValueError("❌ Discord not set. Use: export Discord='your_token'")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def find_channel_webhooks(channel: discord.TextChannel):
    return [wh.url for wh in channel.webhooks if wh.user == channel.guild.me]

@bot.event
async def on_ready():
    try:
        await bot.wait_until_ready()
        synced = await bot.tree.sync()
        print(f"[+] Synced {len(synced)} slash commands.")
        print(f"[+] Logged in as {bot.user}")
    except Exception as e:
        print(f"[ERROR] Sync failed: {e}")

# /rss list
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
            msg += f"• **{entry.get('category', 'Unknown')}** → {url}\n"
            feed_count += 1

    if feed_count == 0:
        await interaction.followup.send("📭 No feeds configured in this channel.")
    else:
        await interaction.followup.send(f"📡 **Feeds in {interaction.channel.mention}:**\n{msg}")

# /rss add <url>
@bot.tree.command(name="rss_add", description="Add a feed to this channel")
@app_commands.describe(url="The RSS feed URL to monitor")
async def rss_add(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)
    config = load_config()
    webhooks = await interaction.channel.webhooks()

    wh = None
    for w in webhooks:
        if w.user == interaction.guild.me:
            wh = w
            break

    if not wh:
        wh = await interaction.channel.create_webhook(name="RSSBot")

    config[url] = {
        "category": DEFAULT_CATEGORY,
        "webhook": wh.url
    }

    save_config(config)
    await interaction.followup.send(f"✅ Feed added:\n• `{url}` → {interaction.channel.mention}")

# /rss remove <url>
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
        await interaction.followup.send(f"🗑️ Removed feed:\n• `{url}` from {interaction.channel.mention}")
    else:
        await interaction.followup.send("⚠️ Feed not found in this channel.")

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
            f"✅ Twitch feed added:\n• `{key}` → {interaction.channel.mention}",
            ephemeral=True
        )

    except discord.HTTPException as e:
        print(f"[HTTP ERROR] {e.status} - {e.text}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ HTTP error occurred.", ephemeral=True)

    except Exception as e:
        print(f"[FATAL] twitch_add error: {type(e).__name__} - {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Internal error occurred.", ephemeral=True)


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
        await interaction.response.send_message("📭 No Twitch feeds in this channel.", ephemeral=True)
    else:
        await interaction.response.send_message(f"🎮 **Twitch Feeds in {interaction.channel.mention}:**\n{msg}", ephemeral=True)

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
        await interaction.response.send_message(f"🗑️ Removed Twitch feed: `{key}`", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Twitch feed not found in this channel.", ephemeral=True)

bot.run(BOT_TOKEN)
