import json
import feedparser
import hashlib
import aiohttp
import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlunparse
from bs4 import BeautifulSoup

CONFIG_FILE = 'feeds_config.json'
SEEN_FILE = 'seen_entries.txt'
CHECK_INTERVAL = 1200  # seconds
SEND_INTERVAL = 5

logging.basicConfig(level=logging.INFO)
sent_articles = set()
queue = asyncio.Queue()
session = None

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/xxxxxx"

async def send_discord_notification(message):
    async with aiohttp.ClientSession() as session:
        payload = {"content": message}
        try:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as resp:
                text = await resp.text()
                if resp.status == 204:
                    logging.info("✅ Notification sent successfully.")
                else:
                    logging.error(f"❌ Failed to send notification ({resp.status}): {text}")
        except Exception as e:
            logging.error(f"⚠️ Error sending notification: {type(e).__name__} - {e}")

def is_valid_image_url(url):
    return url and url.startswith("http") and url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))


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
    # YouTube thumbnail
    if "media_thumbnail" in entry:
        thumb = entry["media_thumbnail"]
        if isinstance(thumb, list) and "url" in thumb[0]:
            return thumb[0]["url"]

    if entry.get("media_content"):
        return entry["media_content"][0].get("url")

    if "enclosures" in entry and entry["enclosures"]:
        return entry["enclosures"][0].get("href")

    for key in ["summary", "description"]:
        content = entry.get(key, "")
        match = re.search(r'<img[^>]+src="([^"]+)"', content)
        if match:
            return match.group(1)

    if "content" in entry:
        for content_item in entry["content"]:
            match = re.search(r'<img[^>]+src="([^"]+)"', content_item.get("value", ""))
            if match:
                return match.group(1)

    if "youtube.com/watch" in entry.get("link", ""):
        video_id = entry["link"].split("v=")[-1]
        return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    return None

async def fetch_og_image(url):
    try:
        await create_session()  # Ensure session is alive

        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=6) as resp:
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")

            # Safely fetch og:image
            og_tag = soup.find("meta", attrs={"property": "og:image"})
            if og_tag:
                img_url = og_tag.get("content", None)
                if img_url and is_valid_image_url(img_url):
                    return img_url

            # Safely fetch twitter:image
            twitter_tag = soup.find("meta", attrs={"name": "twitter:image"})
            if twitter_tag:
                img_url = twitter_tag.get("content", None)
                if img_url and is_valid_image_url(img_url):
                    return img_url

            # <article> image
            article = soup.find("article")
            if article:
                img = article.find("img")
                if img:
                    img_url = img.get("src", None)
                    if img_url and is_valid_image_url(img_url):
                        return img_url

            # Fallback: any image
            img = soup.find("img")
            if img:
                img_url = img.get("src", None)
                if img_url and is_valid_image_url(img_url):
                    return img_url

    except Exception as e:
        logging.warning(f"[IMAGE FETCH FAILED] {url} :: {type(e).__name__} - {e}")

    return None



async def create_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()

async def close_session():
    if session and not session.closed:
        await session.close()

async def send_embed(title, link, image, webhook_url, category, entry):
    is_youtube = "youtube.com/watch" in link or "youtu.be/" in link

    if is_youtube:
        # YouTube mode
        channel_name = entry.get("author", "YouTube")
        message = f"🎥 New video from **{channel_name}**!\n{link}"

        data = {
            "content": message
        }

    else:
        # Article mode
        source = urlparse(link).netloc.replace("www.", "")
        message = f"📰 New article from **{source}**!"

        embed = {
            "title": title,
            "url": link,
            "description": f"[Click to read]({link})",
            "color": 0x00ff00,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": category}
        }

        if image and is_valid_image_url(image):
            embed["image"] = {"url": image}

        data = {
            "content": message,
            "embeds": [embed]
        }

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
        await send_discord_notification("🔁 RSS Bot is checking feeds now...")

        for url, config in feeds.items():
            webhook = config["webhook"]
            category = config.get("category", "RSS")

            parsed = feedparser.parse(url)
            for entry in parsed.entries:
                title = entry.get("title", "No Title")
                link = sanitize_url(entry.get("link", ""))
                published = entry.get("published", "")
                image = extract_image(entry)

                if not image:
                    logging.debug(f"[EXTRACT FAILED] Trying OG scrape for: {link}")
                    image = await fetch_og_image(link)

                if image:
                    logging.info(f"[IMAGE FOUND] {image}")
                else:
                    logging.warning(f"[NO IMAGE FOUND AFTER OG SCRAPE] {link}")

                # Validate image URL before sending to Discord
                if image and not is_valid_image_url(image):
                    logging.warning(f"[INVALID IMAGE URL FILTERED OUT] {image}")
                    image = None

                entry_hash = hash_entry(title, link, published)
                key = f"{url}::{entry_hash}"

                if key in seen:
                    continue

                seen.add(key)
                await queue.put((title, link, image, webhook, category, entry))

        save_seen_entries(seen)
        logging.info(f"✅ Cycle complete. Sleeping {CHECK_INTERVAL}s\n")
        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    await asyncio.gather(rss_checker(), sender_worker())

async def full_start():
    await send_discord_notification("✅ RSS Bot is starting up.")
    await main()

if __name__ == "__main__":
    try:
        asyncio.run(full_start())
    except KeyboardInterrupt:
        print("Shutting down...")
        asyncio.run(close_session())
