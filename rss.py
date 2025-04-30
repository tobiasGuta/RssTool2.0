import json
import feedparser
import hashlib
import aiohttp
import asyncio
import logging
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlunparse

CONFIG_FILE = 'feeds_config.json'
SEEN_FILE = 'seen_entries.txt'
CHECK_INTERVAL = 125  # change this
SEND_INTERVAL = 5

logging.basicConfig(level=logging.INFO)
sent_articles = set()
queue = asyncio.Queue()
session = None

# --- Helpers ---
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def load_seen_entries():
    try:
        with open(SEEN_FILE, "r") as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_seen_entries(seen):
    with open(SEEN_FILE, "w") as f:
        for item in seen:
            f.write(item + "\n")

def sanitize_url(url):
    parsed = urlparse(url)
    clean_query = {k: v for k, v in parse_qs(parsed.query).items() if not k.startswith('utm')}
    new_query = '&'.join(f"{k}={v[0]}" for k, v in clean_query.items())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

def hash_entry(title, link, published):
    h = hashlib.sha256()
    h.update(f"{title}{link}{published}".encode())
    return h.hexdigest()

def extract_image(entry):
    if entry.get("media_content"):
        return entry["media_content"][0].get("url")
    if entry.get("media_thumbnail"):
        return entry["media_thumbnail"][0].get("url")
    if "enclosures" in entry and entry["enclosures"]:
        return entry["enclosures"][0].get("href")
    summary = entry.get("summary", "")
    match = re.search(r'<img[^>]+src="([^"]+)"', summary)
    if match:
        return match.group(1)
    return None

async def create_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()

async def close_session():
    if session and not session.closed:
        await session.close()

async def send_embed(title, link, image, webhook_url, category):
    embed = {
        "title": title,
        "url": link,
        "description": f"[Click to read]({link})",
        "color": 0x00ff00,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": category}
    }
    if image:
        embed["image"] = {"url": image}

    data = {"embeds": [embed]}

    try:
        async with session.post(webhook_url, json=data) as resp:
            if resp.status == 204:
                logging.info(f"✅ Sent: {title}")
            else:
                logging.warning(f"❌ Failed to send ({resp.status})")
    except Exception as e:
        logging.error(f"[ERROR] {e}")

async def sender_worker():
    await create_session()
    while True:
        item = await queue.get()
        await send_embed(*item)
        await asyncio.sleep(SEND_INTERVAL)

async def rss_checker():
    seen = load_seen_entries()

    while True:
        feeds = load_config()  # 🔥 reload config every loop
        logging.info("🔁 Checking feeds...")

        for url, config in feeds.items():
            webhook = config["webhook"]
            category = config.get("category", "RSS")

            parsed = feedparser.parse(url)
            for entry in parsed.entries:
                title = entry.get("title", "No Title")
                link = sanitize_url(entry.get("link", ""))
                published = entry.get("published", "")
                image = extract_image(entry)

                entry_hash = hash_entry(title, link, published)
                key = f"{url}::{entry_hash}"

                if key in seen:
                    continue

                seen.add(key)
                await queue.put((title, link, image, webhook, category))

        save_seen_entries(seen)
        logging.info(f"✅ Cycle complete. Sleeping {CHECK_INTERVAL}s\n")
        await asyncio.sleep(CHECK_INTERVAL)

async def main():
    await asyncio.gather(rss_checker(), sender_worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
        asyncio.run(close_session())
