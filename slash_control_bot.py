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
        synced = await bot.tree.sync()
        print(f"[+] Synced {len(synced)} slash commands.")
        print(f"[+] Logged in as {bot.user}")
    except Exception as e:
        print(f"[ERROR] Sync failed: {e}")

# /rss list
@bot.tree.command(name="rss_list", description="List feeds in this channel")
async def rss_list(interaction: discord.Interaction):
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

bot.run(BOT_TOKEN)
