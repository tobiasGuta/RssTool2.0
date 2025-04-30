import discord
import json
import asyncio

OUTPUT_FILE = "guild_channels.json"
BOT_TOKEN = os.getenv("Discord")

if not BOT_TOKEN:
    raise ValueError("❌ Discord not set. Use: export Discord='your_token'")

intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[+] Logged in as {client.user}")
    data = {}
    for guild in client.guilds:
        data[guild.id] = {
            "guild_name": guild.name,
            "channels": [(channel.id, channel.name) for channel in guild.text_channels]
        }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=4)

    print(f"[+] Saved guild/channel data to {OUTPUT_FILE}")
    await client.close()

if __name__ == "__main__":
    asyncio.run(client.start(BOT_TOKEN))
