"""
dashboard.py — Local web dashboard for RssTool2.0

Accessible from any device on your local network.
Default: http://0.0.0.0:8080

Find your local IP:
  Linux/Mac:  ip route get 1 | awk '{print $7}'
  Windows:    ipconfig | findstr "IPv4"
Then open http://<local-ip>:8080 on your phone or any device.

Env vars: DASHBOARD_HOST (default 0.0.0.0), DASHBOARD_PORT (default 8080)
"""

import os
import socket
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
import requests
import feedparser
from urllib.parse import urlparse
import time
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import db

load_dotenv()

HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", 8080))

app = FastAPI(title="RssTool2.0 Dashboard", version="2.0")


class FeedCreate(BaseModel):
    url:      str
    webhook:  str
    category: str = "General"
    keywords: str = ""


class FeedUpdate(BaseModel):
    keywords: str | None = None
    enabled:  bool | None = None


class FeedTest(BaseModel):
    url: str


def _clean_html(raw: str) -> str:
    raw = re.sub(r'<br\s*/?>', '\n', raw)
    raw = re.sub(r'<[^>]+>', '', raw)
    return raw.strip()


def _conn() -> sqlite3.Connection:
    return db.get_connection()


@app.get("/api/feeds")
def list_feeds():
    return [dict(r) for r in db.get_all_feeds(_conn())]


@app.post("/api/feeds", status_code=201)
def add_feed(body: FeedCreate):
    db.add_feed(_conn(), body.url, body.webhook, body.category, body.keywords)
    return {"ok": True, "url": body.url}


@app.delete("/api/feeds/{url:path}")
def remove_feed(url: str):
    conn = _conn()
    if not db.get_feed(conn, url):
        raise HTTPException(404, "Feed not found")
    db.remove_feed(conn, url)
    return {"ok": True}


@app.patch("/api/feeds/{url:path}")
def update_feed(url: str, body: FeedUpdate):
    conn = _conn()
    if not db.get_feed(conn, url):
        raise HTTPException(404, "Feed not found")
    if body.keywords is not None:
        db.update_feed_keywords(conn, url, body.keywords)
    if body.enabled is not None:
        db.toggle_feed(conn, url, body.enabled)
    return {"ok": True}


@app.get("/api/articles")
def recent_articles(limit: int = 50):
    return [dict(r) for r in db.get_recent_articles(_conn(), limit)]


@app.get("/api/health")
def feed_health():
    return [dict(r) for r in db.get_feed_health(_conn())]


@app.get("/api/stats")
def stats():
    conn = _conn()
    return {
        "total_feeds":    conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0],
        "active_feeds":   conn.execute("SELECT COUNT(*) FROM feeds WHERE enabled=1").fetchone()[0],
        "total_articles": conn.execute("SELECT COUNT(*) FROM sent_articles").fetchone()[0],
        "last_article_at": (conn.execute(
            "SELECT sent_at FROM sent_articles ORDER BY sent_at DESC LIMIT 1"
        ).fetchone() or [None])[0],
    }


@app.post("/api/feeds/test")
def test_feed(body: FeedTest):
    conn = _conn()
    feed = db.get_feed(conn, body.url)
    if not feed:
        return {"ok": False, "error": "Feed not found in database"}
        
    url = feed["url"]
    webhook = feed["webhook"]
    category = feed["category"]
    
    try:
        if url.startswith("twitch:"):
            channel = url.split("twitch:", 1)[1]
            uptime = requests.get(f"https://decapi.me/twitch/uptime/{channel}").text
            
            if "offline" in uptime.lower() or "not found" in uptime.lower():
                data = {
                    "embeds": [{
                        "description": f"⚫ **{channel}** is currently offline.",
                        "color": 0x2b2d31,
                    }]
                }
                requests.post(webhook, json=data).raise_for_status()
                return {"ok": True}
                
            status  = requests.get(f"https://decapi.me/twitch/status/{channel}").text
            game    = requests.get(f"https://decapi.me/twitch/game/{channel}").text
            viewers = requests.get(f"https://decapi.me/twitch/viewercount/{channel}").text
            
            stream_url = f"https://twitch.tv/{channel}"
            thumb_url  = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{channel}-640x360.jpg?t={int(time.time())}"
            
            if not viewers.isdigit(): viewers = "0"
            if "error" in game.lower(): game = "Unknown"
            
            embed = {
                "url": stream_url,
                "color": 0x9146FF,
                "description": f"**[{channel} is now live!]({stream_url})**",
                "author": {"name": channel, "url": stream_url},
                "fields": [
                    {"name": "🎮 Game", "value": game or "Unknown", "inline": True},
                    {"name": "👥 Viewers", "value": viewers, "inline": True},
                    {"name": "📝 Title", "value": (status or "No title")[:1024], "inline": False},
                    {"name": "⏱ Uptime", "value": uptime or "Just started", "inline": True},
                ],
                "image": {"url": thumb_url},
            }
            requests.post(webhook, json={"embeds": [embed]}).raise_for_status()
            return {"ok": True}
            
        elif url.startswith("http"):
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.text)
            
            if not parsed.entries:
                return {"ok": False, "error": "No entries found in feed"}
                
            entry = parsed.entries[0]
            title = entry.get("title", "No Title")
            link = entry.get("link", url)
            
            image = None
            if "media_thumbnail" in entry and entry.media_thumbnail:
                image = entry.media_thumbnail[0].get("url")
            elif "media_content" in entry and entry.media_content:
                image = entry.media_content[0].get("url")
            elif "enclosures" in entry:
                for enc in entry.enclosures:
                    if enc.get("type", "").startswith("image/"):
                        image = enc.get("href")
                        break
            
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
                    "footer": {"text": f"📡 {category} · {source}"},
                }
                if image:
                    embed["image"] = {"url": image}
                data = {"content": f"📰 New from **{source}**", "embeds": [embed]}
                
            requests.post(webhook, json=data).raise_for_status()
            return {"ok": True}
            
        else:
            return {"ok": False, "error": "Unsupported feed type"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
def dashboard():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>static/index.html not found</h1>", 404)
    return HTMLResponse(index.read_text(encoding="utf-8"))


if __name__ == "__main__":
    db.init_db()
    local_ip = "localhost"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    print(f"\n{'='*50}")
    print(f"  RssTool2.0 Dashboard")
    print(f"  Local:   http://localhost:{PORT}")
    print(f"  Network: http://{local_ip}:{PORT}  ← open this on your phone")
    print(f"{'='*50}\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
