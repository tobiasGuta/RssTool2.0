from flask import Flask, render_template, request, redirect
import json
import subprocess
import os
import asyncio
import discord

CONFIG_FILE = 'feeds_config.json'
INPUT_FILE = 'webhook_request.json'
OUTPUT_FILE = 'webhook_result.json'
BOT_TOKEN = os.getenv("Discord")

if not BOT_TOKEN:
    raise ValueError("❌ Discord not set. Use: export Discord='your_token'")

app = Flask(__name__)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)


def fetch_live_guild_channels():
    class FetcherClient(discord.Client):
        def __init__(self):
            intents = discord.Intents.default()
            intents.guilds = True
            super().__init__(intents=intents)
            self.guild_data = {}

        async def on_ready(self):
            for guild in self.guilds:
                self.guild_data[guild.id] = {
                    "guild_name": guild.name,
                    "channels": [(c.id, c.name) for c in guild.text_channels]
                }
            await self.close()

    client = FetcherClient()
    asyncio.run(client.start(BOT_TOKEN))
    return client.guild_data


@app.route('/')
def index():
    feeds = load_config()
    guilds = fetch_live_guild_channels()  
    return render_template('index.html', feeds=feeds, guilds=guilds)

@app.route('/add', methods=['POST'])
def add_feed():
    rss_url = request.form['url']
    category = request.form['category']
    guild_id = int(request.form['guild_id'])
    channel_id = int(request.form['channel_id'])

    with open(INPUT_FILE, 'w') as f:
        json.dump({
            "guild_id": guild_id,
            "channel_id": channel_id,
            "name": "RSSBot"
        }, f)

    subprocess.run(["python3", "create_webhook_runner.py"])

    with open(OUTPUT_FILE, 'r') as f:
        result = json.load(f)
        webhook_url = result["webhook_url"]

    feeds = load_config()
    feeds[rss_url] = {
        "category": category,
        "webhook": webhook_url
    }
    save_config(feeds)

    return redirect('/')

@app.route('/delete', methods=['POST'])
def delete_feed():
    url = request.form['url']
    feeds = load_config()
    if url in feeds:
        del feeds[url]
        save_config(feeds)
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
