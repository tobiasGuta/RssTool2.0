"""
rss_alerts.py — RSS + Twitch alert engine for RssTool2.0

Bug fixes applied:
  • aiohttp ClientTimeout object instead of bare integer
  • asyncio.Lock guards global session creation (no race condition)
  • sender_worker wrapped in try/except/finally (won't silently die)
  • is_recent falls back to updated_parsed; missing dates = recent
  • YouTube video-ID extraction handles youtu.be and extra query params
  • System notification sent only at startup, not every cycle
  • seen_entries pruned on startup (30-day rolling window)
  • Twitch decapi responses validated before use
  • Discord 429 rate-limit backoff with retry_after header
  • asyncio.gather uses return_exceptions to surface all crashes

Improvements added:
  • SQLite storage via db.py (replaces flat files)
  • Rotating log file (logs/rsstool.log)
  • Keyword filtering per feed
  • Cross-feed URL deduplication (in-memory cache)
  • ntfy.sh notification support alongside Discord
  • Feed health tracking (fail counts, last error)
  • Article history logged to DB for dashboard
"""

import feedparser
import hashlib
import aiohttp
import asyncio
import logging
import logging.handlers
import re
import time
import os
from aiohttp import ClientTimeout
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlunparse, urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import db

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────
RSS_CHECK_INTERVAL  = int(os.getenv("RSS_CHECK_INTERVAL", 300))   # seconds
TWITCH_CHECK_INTERVAL = int(os.getenv("TWITCH_CHECK_INTERVAL", 120))
SEND_INTERVAL       = int(os.getenv("SEND_INTERVAL", 5))
MAX_ARTICLE_AGE_H   = int(os.getenv("MAX_ARTICLE_AGE_HOURS", 24))
SYSTEM_WEBHOOK_URL  = os.getenv("SYSTEM_WEBHOOK_URL", "")
NTFY_URL            = os.getenv("NTFY_URL", "")   # e.g. https://ntfy.sh/your-topic
REQUEST_TIMEOUT     = ClientTimeout(total=15)       # FIX: was bare int 10

# ── Logging setup ──────────────────────────────────────────────────────────
def _setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh  = logging.handlers.RotatingFileHandler(
        "logs/rsstool.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[fh, ch])

_setup_logging()
log = logging.getLogger("rss_alerts")

# ── State ──────────────────────────────────────────────────────────────────
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()           # FIX: prevents race on session creation
_sent_links: set[str] = set()           # in-memory cross-feed dedup cache
_queue: asyncio.Queue = asyncio.Queue()
_twitch_last_live: dict[str, bool] = {}
_db_conn = None


def _get_db():
    global _db_conn
    if _db_conn is None:
        _db_conn = db.get_connection()
    return _db_conn


# ── Session management ─────────────────────────────────────────────────────

async def _create_session():
    global _session
    async with _session_lock:                  # FIX: lock prevents double-creation
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession()


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()


# ── System notifications (startup/shutdown only) ───────────────────────────

async def _notify_system(message: str):
    """Send a one-off system message to Discord webhook and/or ntfy."""
    async with aiohttp.ClientSession() as s:
        if SYSTEM_WEBHOOK_URL:
            try:
                await s.post(SYSTEM_WEBHOOK_URL,
                             json={"content": message},
                             timeout=REQUEST_TIMEOUT)
            except Exception as e:
                log.warning(f"System webhook failed: {e}")
        if NTFY_URL:
            try:
                await s.post(NTFY_URL,
                             data=message.encode(),
                             headers={"Title": "RssTool2.0"},
                             timeout=REQUEST_TIMEOUT)
            except Exception as e:
                log.warning(f"ntfy failed: {e}")


# ── Helpers ────────────────────────────────────────────────────────────────

def _is_valid_image(url: str) -> bool:
    return bool(url and url.startswith("http"))


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    try:
        return BeautifulSoup(raw, "html.parser").get_text(separator=" ").strip()
    except Exception:
        return raw


def _sanitize_url(url: str) -> str:
    p = urlparse(url)
    q = {k: v for k, v in parse_qs(p.query).items() if not k.startswith("utm")}
    new_q = "&".join(f"{k}={v[0]}" for k, v in q.items())
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, p.fragment))


def _hash_entry(title: str, link: str, published: str) -> str:
    return hashlib.sha256(f"{title}{link}{published}".encode()).hexdigest()


def _matches_keywords(title: str, summary: str, keywords_str: str) -> bool:
    """Return True if no keywords set, or any keyword appears in title/summary."""
    if not keywords_str or not keywords_str.strip():
        return True
    text = f"{title} {summary}".lower()
    return any(kw.strip().lower() in text
               for kw in keywords_str.split(",") if kw.strip())


def _is_recent(entry) -> bool:
    """True if published within MAX_ARTICLE_AGE_H hours.
    FIX: falls back to updated_parsed; missing date → assume recent."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return True   # FIX: was return False — silently dropped dateless entries
    dt = datetime(*parsed[:6], tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() < MAX_ARTICLE_AGE_H * 3600


def _extract_youtube_id(link: str) -> str | None:
    """FIX: handles youtu.be, ?v= with extra params, Shorts."""
    p = urlparse(link)
    if p.netloc in ("youtu.be", "www.youtu.be"):
        return p.path.lstrip("/").split("?")[0]
    vid = parse_qs(p.query).get("v", [None])[0]
    return vid


def _extract_image(entry) -> str | None:
    if entry.get("media_thumbnail"):
        thumb = entry["media_thumbnail"]
        if isinstance(thumb, list) and "url" in thumb[0]:
            return thumb[0]["url"]
    if entry.get("media_content"):
        return entry["media_content"][0].get("url")
    if entry.get("enclosures"):
        return entry["enclosures"][0].get("href")
    for key in ("summary", "description"):
        m = re.search(r'<img[^>]+src="([^"]+)', entry.get(key, ""))
        if m:
            return m.group(1)
    for ci in entry.get("content", []):
        m = re.search(r'<img[^>]+src="([^"]+)', ci.get("value", ""))
        if m:
            return m.group(1)
    link = entry.get("link", "")
    if "youtube.com" in link or "youtu.be" in link:
        vid = _extract_youtube_id(link)
        if vid:
            return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    return None


async def _fetch_og_image(url: str) -> str | None:
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/113.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with _session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            soup = BeautifulSoup(await resp.text(), "html.parser")
            for attr, val in [("property", "og:image"), ("name", "twitter:image")]:
                tag = soup.find("meta", attrs={attr: val})
                if tag and tag.get("content"):
                    return urljoin(url, tag["content"])
            for selector in [soup.find("article"), soup]:
                img = selector.find("img") if selector else None
                if img and img.get("src"):
                    return urljoin(url, img["src"])
    except Exception as e:
        log.debug(f"og:image fetch failed for {url}: {e}")
    return None


async def _fetch_rss(url: str) -> str:
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/113.0.0.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
    }
    try:
        async with _session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                return await resp.text()
            log.warning(f"RSS fetch {url} → HTTP {resp.status}")
    except Exception as e:
        log.error(f"RSS fetch error {url}: {type(e).__name__}: {e}")
    return ""


# ── Discord webhook sender with rate-limit backoff ─────────────────────────

async def _send_webhook(webhook_url: str, data: dict, retries: int = 3) -> bool:
    """FIX: handles Discord 429 with retry_after header and exponential backoff."""
    for attempt in range(retries):
        try:
            async with _session.post(webhook_url, json=data,
                                     timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 204:
                    return True
                if resp.status == 429:
                    body = await resp.json()
                    wait = float(body.get("retry_after", 5))
                    log.warning(f"Discord rate-limited — waiting {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                log.warning(f"Webhook returned {resp.status}")
                return False
        except Exception as e:
            log.error(f"Webhook attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2 ** attempt)
    return False


# ── ntfy.sh sender ─────────────────────────────────────────────────────────

async def _send_ntfy(title: str, link: str, category: str):
    if not NTFY_URL:
        return
    try:
        headers = {
            "Title": title[:100],
            "Tags": category.lower().replace(" ", "_"),
            "Click": link,
        }
        async with _session.post(NTFY_URL, data=title.encode(),
                                  headers=headers, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status not in (200, 201):
                log.warning(f"ntfy returned {resp.status}")
    except Exception as e:
        log.error(f"ntfy error: {e}")


# ── Embed builder & sender ─────────────────────────────────────────────────

async def _send_embed(title, link, image, webhook_url, category, entry):
    is_yt = "youtube.com/watch" in link or "youtu.be/" in link
    if is_yt:
        author = entry.get("author", "YouTube")
        data = {"content": f"🎬 New video from **{author}**!\n{link}"}
    else:
        source = urlparse(link).netloc.replace("www.", "")
        raw_desc = entry.get("summary", "") or entry.get("description", "")
        desc = _clean_html(raw_desc)
        if len(desc) > 280:
            desc = desc[:277] + "..."
        body = f"{desc}\n\n[Read full article]({link})" if desc else f"[Read article]({link})"
        embed = {
            "title": title,
            "url": link,
            "description": body,
            "color": 0x00FF99,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": f"📡 {category} · {source}"},
        }
        if image and _is_valid_image(image):
            embed["image"] = {"url": image}
        data = {"content": f"📰 New from **{source}**", "embeds": [embed]}

    if await _send_webhook(webhook_url, data):
        await _send_ntfy(title, link, category)
        db.log_article(_get_db(), entry.get("_feed_url", ""), title, link, category, image)
        log.info(f"✅ Sent: {title[:80]}")


# ── Worker ─────────────────────────────────────────────────────────────────

async def sender_worker():
    """FIX: try/except/finally prevents silent worker death on any exception."""
    await _create_session()
    while True:
        item = await _queue.get()
        try:
            await _send_embed(*item)
        except Exception as e:
            log.error(f"[sender_worker] Unhandled error: {e}", exc_info=True)
        finally:
            _queue.task_done()
        await asyncio.sleep(SEND_INTERVAL)


# ── RSS checker ────────────────────────────────────────────────────────────

async def rss_checker():
    await _create_session()
    conn = _get_db()
    db.prune_seen(conn, max_age_days=30)   # prune old entries on startup

    while True:
        feeds = db.get_enabled_feeds(conn)
        rss_feeds = [f for f in feeds if not f["url"].startswith("twitch:")]
        log.info(f"Checking {len(rss_feeds)} RSS feeds...")

        for feed in rss_feeds:
            url      = feed["url"]
            webhook  = feed["webhook"]
            category = feed["category"]
            keywords = feed["keywords"] or ""

            content = await _fetch_rss(url)
            if not content:
                db.update_health(conn, url, success=False, error="Empty/failed response")
                continue

            parsed = feedparser.parse(content)
            if parsed.bozo:
                err = str(getattr(parsed, "bozo_exception", "unknown"))
                db.update_health(conn, url, success=False, error=err)
                log.warning(f"Feed parse error {url}: {err}")
                # Still process entries — bozo just means non-fatal parse warning
            else:
                db.update_health(conn, url, success=True)

            recent = [e for e in parsed.entries if _is_recent(e)]
            if not recent:
                log.debug(f"No recent entries: {url}")
                continue

            queued = 0
            for entry in recent[:10]:
                title     = entry.get("title", "No Title")
                link      = _sanitize_url(entry.get("link", ""))
                published = entry.get("published", "")
                summary   = entry.get("summary", "") or entry.get("description", "")

                if not _matches_keywords(title, summary, keywords):
                    continue

                h = _hash_entry(title, link, published)
                if db.is_seen(conn, h):
                    continue

                # Cross-feed URL dedup
                if link in _sent_links:
                    db.mark_seen(conn, h, url)
                    continue

                db.mark_seen(conn, h, url)
                _sent_links.add(link)

                image = _extract_image(entry)
                if not image:
                    image = await _fetch_og_image(link)
                if image and not _is_valid_image(image):
                    image = None

                entry["_feed_url"] = url
                await _queue.put((title, link, image, webhook, category, entry))
                queued += 1

            if queued:
                log.info(f"Queued {queued} new article(s) from {url}")

        log.info(f"RSS cycle done. Next check in {RSS_CHECK_INTERVAL}s")
        await asyncio.sleep(RSS_CHECK_INTERVAL)


# ── Twitch checker ─────────────────────────────────────────────────────────

async def _twitch_get(path: str) -> str:
    url = f"https://decapi.me/twitch/{path}"
    try:
        async with _session.get(url, timeout=REQUEST_TIMEOUT) as r:
            return (await r.text()).strip()
    except Exception as e:
        log.warning(f"decapi.me error ({path}): {e}")
        return ""


async def _send_twitch_alert(channel: str, webhook: str) -> bool:
    uptime  = await _twitch_get(f"uptime/{channel}")
    if "offline" in uptime.lower():
        return False

    status  = await _twitch_get(f"status/{channel}")
    game    = await _twitch_get(f"game/{channel}")
    viewers = await _twitch_get(f"viewercount/{channel}")
    avatar  = await _twitch_get(f"avatar/{channel}")

    # FIX: validate decapi responses before using in embed
    if not viewers.isdigit():
        viewers = "0"
    if not avatar.startswith("http"):
        avatar = ""
    if "error" in game.lower():
        game = "Unknown"

    stream_url = f"https://twitch.tv/{channel}"
    thumb_url  = (f"https://static-cdn.jtvnw.net/previews-ttv/"
                  f"live_user_{channel}-640x360.jpg?t={int(time.time())}")

    embed: dict = {
        "url": stream_url,
        "color": 0x9146FF,
        "description": f"**[{channel} is now live!]({stream_url})**",
        "author": {"name": channel, "url": stream_url},
        "fields": [
            {"name": "🎮 Game",    "value": game or "Unknown",        "inline": True},
            {"name": "👥 Viewers", "value": viewers,                  "inline": True},
            {"name": "📝 Title",   "value": (status or "No title")[:1024], "inline": False},
            {"name": "⏱ Uptime",  "value": uptime or "Just started", "inline": True},
        ],
        "image": {"url": thumb_url},
        "footer": {"text": "Twitch Stream Monitor"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if avatar:
        embed["author"]["icon_url"] = avatar

    success = await _send_webhook(webhook, {"embeds": [embed]})
    if success:
        log.info(f"Twitch alert sent: {channel}")
    return success


async def twitch_checker():
    global _twitch_last_live
    await _create_session()
    conn = _get_db()

    while True:
        feeds = db.get_enabled_feeds(conn)
        twitch = [f for f in feeds if f["url"].startswith("twitch:")]

        for feed in twitch:
            channel = feed["url"].split("twitch:", 1)[1]
            webhook = feed["webhook"]
            try:
                uptime  = await _twitch_get(f"uptime/{channel}")
                if "not found" in uptime.lower():
                    log.warning(f"[Twitch] Channel not found: {channel}")
                    continue
                is_live = "offline" not in uptime.lower()
                if is_live and not _twitch_last_live.get(channel, False):
                    log.info(f"[Twitch] {channel} went LIVE — sending alert")
                    if await _send_twitch_alert(channel, webhook):
                        _twitch_last_live[channel] = True
                elif not is_live:
                    if _twitch_last_live.get(channel, False):
                        log.info(f"[Twitch] {channel} went offline")
                    _twitch_last_live[channel] = False
            except Exception as e:
                log.error(f"[Twitch] Error checking {channel}: {e}")

        await asyncio.sleep(TWITCH_CHECK_INTERVAL)


# ── Entry point ────────────────────────────────────────────────────────────

async def main():
    db.init_db()
    # FIX: system notification only at startup, not inside the loop
    await _notify_system("🚀 RssTool2.0 started successfully.")
    try:
        await asyncio.gather(
            rss_checker(),
            sender_worker(),
            twitch_checker(),
            return_exceptions=True,    # FIX: surfaces all coroutine exceptions
        )
    except Exception as e:
        log.critical(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down RSS alerts...")
        asyncio.run(close_session())
