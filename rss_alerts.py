import json
import feedparser
import hashlib
import aiohttp
import asyncio
import logging
import re
import time
import os
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlunparse, urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

CONFIG_FILE = 'feeds_config.json'
SEEN_FILE = 'seen_entries.txt'
RSS_CHECK_INTERVAL = 300   # 5 minutes for RSS
TWITCH_CHECK_INTERVAL = 120  # 2 minutes for Twitch
SEND_INTERVAL = 5
twitch_last_live = {}

logging.basicConfig(level=logging.INFO)
sent_articles = set()
queue = asyncio.Queue()
session = None

# Optional: System notifications webhook
DISCORD_WEBHOOK_URL = os.getenv("SYSTEM_WEBHOOK_URL")

async def send_discord_notification(message):
    if not DISCORD_WEBHOOK_URL:
        logging.info(f"[System Notification] {message}")
        return

    async with aiohttp.ClientSession() as session:
        payload = {"content": message}
        try:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as resp:
                text = await resp.text()
                if resp.status == 204:
                    logging.info("Notification sent successfully.")
                else:
                    logging.error(f"Failed to send notification ({resp.status}): {text}")
        except Exception as e:
            logging.error(f"Error sending notification: {type(e).__name__} - {e}")

def is_valid_image_url(url):
    # Relaxed check: just ensure it's a http URL. Discord handles the rest.
    return url and url.startswith("http")

def clean_html(raw_html):
    if not raw_html:
        return ""
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(separator=" ").strip()
    except Exception:
        return raw_html

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
        match = re.search(r'<img[^>]+src="([^"]+)', content)
        if match:
            return match.group(1)
    if "content" in entry:
        for content_item in entry["content"]:
            match = re.search(r'<img[^>]+src="([^"]+)', content_item.get("value", ""))
            if match:
                return match.group(1)
    if "youtube.com/watch" in entry.get("link", ""):
        video_id = entry["link"].split("v=")[-1]
        return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    return None

async def fetch_og_image(url):
    try:
        await create_session()
        # Use a realistic browser header to avoid being blocked
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status != 200:
                logging.warning(f"[IMAGE FETCH FAILED] Status {resp.status} for {url}")
                return None
                
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            
            # Try og:image
            og_tag = soup.find("meta", attrs={"property": "og:image"})
            if og_tag:
                img_url = og_tag.get("content", "")
                if img_url:
                    return urljoin(url, img_url)
            
            # Try twitter:image
            twitter_tag = soup.find("meta", attrs={"name": "twitter:image"})
            if twitter_tag:
                img_url = twitter_tag.get("content", "")
                if img_url:
                    return urljoin(url, img_url)
            
            # Try first article image
            article = soup.find("article")
            if article:
                img = article.find("img")
                if img and img.get("src"):
                    return urljoin(url, img.get("src"))
                    
            # Fallback to any image
            img = soup.find("img")
            if img and img.get("src"):
                return urljoin(url, img.get("src"))
                
    except Exception as e:
        logging.warning(f"[IMAGE FETCH FAILED] {url} :: {type(e).__name__} - {e}")
    return None

def is_recent(entry):
    published = entry.get("published_parsed")
    if not published:
        return False
    # Convert struct_time to datetime
    entry_dt = datetime(*published[:6], tzinfo=timezone.utc)
    now_dt = datetime.now(timezone.utc)
    # Check if within last 24 hours (86400 seconds)
    return (now_dt - entry_dt).total_seconds() < 86400

async def create_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()

async def close_session():
    if session and not session.closed:
        await session.close()

async def fetch_rss_content(url):
    await create_session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    try:
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                return await resp.text()
            else:
                logging.warning(f"Failed to fetch RSS from {url} (status {resp.status})")
    except Exception as e:
        logging.error(f"Error fetching RSS feed from {url}: {type(e).__name__} - {e}")
    return ""

async def send_embed(title, link, image, webhook_url, category, entry):
    is_youtube = "youtube.com/watch" in link or "youtu.be/" in link
    if is_youtube:
        channel_name = entry.get("author", "YouTube")
        message = f"New video from **{channel_name}**!\n{link}"
        data = {"content": message}
    else:
        source = urlparse(link).netloc.replace("www.", "")
        message = f"New article from **{source}**!"
        
        # Extract and clean description
        raw_desc = entry.get("summary", "") or entry.get("description", "")
        clean_desc = clean_html(raw_desc)
        
        # Truncate if too long (limit to 280 chars)
        if len(clean_desc) > 280:
            clean_desc = clean_desc[:277] + "..."
            
        # Add read more link
        if clean_desc:
            final_desc = f"{clean_desc}\n\n[Read full article]({link})"
        else:
            final_desc = f"[Click to read article]({link})"

        embed = {
            "title": title,
            "url": link,
            "description": final_desc,
            "color": 0x00ff00,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": category}
        }
        if image and is_valid_image_url(image):
            embed["image"] = {"url": image}
        data = {"content": message, "embeds": [embed]}
    try:
        async with session.post(webhook_url, json=data) as resp:
            if resp.status == 204:
                logging.info(f"Sent: {title}")
            else:
                logging.warning(f"Failed to send ({resp.status})")
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
        feeds = load_config()
        logging.info("Checking feeds...")
        await send_discord_notification("RSS Bot is checking feeds now...")
        for url, config in feeds.items():
            if url.startswith("twitch:"):
                continue
            webhook = config["webhook"]
            category = config.get("category", "RSS")
            feed_content = await fetch_rss_content(url)
            parsed = feedparser.parse(feed_content)
            # Filter for entries from the last 24 hours
            entries_recent = [e for e in parsed.entries if is_recent(e)]
            
            if not entries_recent:
                logging.info(f"[{url}] No recent entries (last 24h).")
                continue
                
            for entry in entries_recent[:5]: # Limit to 5 to avoid spamming on startup
                title = entry.get("title", "No Title")
                link = sanitize_url(entry.get("link", ""))
                published = entry.get("published", "")
                image = extract_image(entry)
                if not image:
                    image = await fetch_og_image(link)
                if image and not is_valid_image_url(image):
                    image = None
                entry_hash = hash_entry(title, link, published)
                key = f"{url}::{entry_hash}"
                if key in seen:
                    continue
                seen.add(key)
                await queue.put((title, link, image, webhook, category, entry))
        save_seen_entries(seen)
        logging.info(f"Cycle complete. Sleeping {RSS_CHECK_INTERVAL}s\n")
        await asyncio.sleep(RSS_CHECK_INTERVAL)

async def twitch_checker():
    global twitch_last_live
    await create_session()
    while True:
        feeds = load_config()
        twitch_feeds = {k: v for k, v in feeds.items() if k.startswith("twitch:")}
        logging.info(f"[Twitch] Loaded {len(twitch_feeds)} twitch feeds")
        for twitch_key, config in twitch_feeds.items():
            channel = twitch_key.split("twitch:")[1]
            webhook = config["webhook"]
            # logging.info(f"[Twitch] Checking live status for: {channel}")
            try:
                uptime = await twitch_check_uptime(channel)
                
                if "not found" in uptime.lower():
                    logging.warning(f"[Twitch] Channel not found: {channel}")
                    continue

                is_live = "offline" not in uptime.lower()
                
                if is_live and not twitch_last_live.get(channel, False):
                    logging.info(f"[Twitch] {channel} is LIVE! Sending alert...")
                    sent = await send_twitch_alert(channel, webhook)
                    if sent:
                        twitch_last_live[channel] = True
                elif not is_live:
                    if twitch_last_live.get(channel, False):
                        logging.info(f"[Twitch] {channel} went offline.")
                    twitch_last_live[channel] = False
            except Exception as e:
                logging.error(f"[Twitch Check ERROR] {channel}: {e}")
        await asyncio.sleep(TWITCH_CHECK_INTERVAL)

async def twitch_check_uptime(channel):
    url = f"https://decapi.me/twitch/uptime/{channel}"
    async with session.get(url) as resp:
        return await resp.text()

async def twitch_check_game(channel):
    url = f"https://decapi.me/twitch/game/{channel}"
    async with session.get(url) as resp:
        return await resp.text()

async def twitch_get_status(channel):
    url = f"https://decapi.me/twitch/status/{channel}"
    async with session.get(url) as resp:
        return await resp.text()

async def twitch_get_viewers(channel):
    url = f"https://decapi.me/twitch/viewercount/{channel}"
    async with session.get(url) as resp:
        return await resp.text()

async def twitch_get_avatar(channel):
    url = f"https://decapi.me/twitch/avatar/{channel}"
    async with session.get(url) as resp:
        return await resp.text()

async def send_twitch_alert(channel, webhook):
    try:
        uptime = await twitch_check_uptime(channel)
        if "offline" in uptime.lower():
            return False
        status = await twitch_get_status(channel)
        game = await twitch_check_game(channel)
        viewers = await twitch_get_viewers(channel)
        avatar = await twitch_get_avatar(channel)
        stream_url = f"https://twitch.tv/{channel}"
        thumbnail_url = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{channel}-640x360.jpg?rand={int(time.time())}"
        embed = {
            "url": stream_url,
            "color": 0x9146FF,
            "description": f" **[{channel} is now streaming!]({stream_url})**",
            "author": {
                "name": channel,
                "url": stream_url,
                "icon_url": avatar
            },
            "fields": [
                {"name": " Game", "value": game or "Unknown", "inline": True},
                {"name": " Viewers", "value": viewers or "0", "inline": True},
                {"name": " Title", "value": status or "No title", "inline": False},
                {"name": " Uptime", "value": uptime or "Just started", "inline": True}
            ],
            "image": {"url": thumbnail_url},
            "footer": {
                "text": " Twitch Stream Monitor",
                "icon_url": "https://cdn.icon-icons.com/icons2/2429/PNG/512/twitch_logo_icon_147272.png"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        payload = {"embeds": [embed]}
        async with session.post(webhook, json=payload) as resp:
            if resp.status == 204:
                logging.info(f" Twitch alert sent: {channel}")
                return True
            else:
                logging.warning(f" Failed Twitch alert ({resp.status})")
    except Exception as e:
        logging.error(f"[Twitch Alert ERROR] {channel}: {e}")
    return False

async def main():
    await asyncio.gather(rss_checker(), sender_worker(), twitch_checker())

async def full_start():
    await send_discord_notification(" RSS Bot is starting up.")
    await main()

if __name__ == "__main__":
    try:
        asyncio.run(full_start())
    except KeyboardInterrupt:
        print("Shutting down...")
        asyncio.run(close_session())
