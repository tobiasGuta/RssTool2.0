from flask import Flask, render_template, request, redirect
import json
import subprocess
import os

CONFIG_FILE = 'feeds_config.json'
INPUT_FILE = 'webhook_request.json'
OUTPUT_FILE = 'webhook_result.json'
GUILDS_FILE = 'guild_channels.json'

app = Flask(__name__)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def load_guilds():
    if os.path.exists(GUILDS_FILE):
        with open(GUILDS_FILE, 'r') as f:
            return json.load(f)
    return {}

@app.route('/')
def index():
    feeds = load_config()
    guilds = load_guilds()
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
