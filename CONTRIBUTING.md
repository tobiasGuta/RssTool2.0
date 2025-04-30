 Contributing to RssTool2.0 Bot

Thanks for your interest in contributing! This tool is designed for asynchronous, automation friendly RSS feed monitoring with Discord webhook support. Whether you're fixing bugs, adding features, or improving docs, you're welcome here.

---

🧰 Project Structure

- `rss.py`: Standard bot version that sends feed updates via a single webhook.
- `rss_alerts.py`: Extended version with an additional notification webhook (operational heartbeats).
- `slash_control_bot.py`: Optional module for Discord slash command support.
- `requirements.txt`: Python dependencies.
- `rss.txt`: Feed sources (one URL per line).
- `seen_entries.txt`: Tracks already-processed entries.
- `config_web_ui.py`: Web Interfaces
---

📐 Contribution Guidelines
✅ What you can contribute:
New RSS parsing features or format support (Atom, JSONFeed, etc.)

Slash command expansions

Feed filtering or keyword matching

Discord UI enhancements (button support, richer embeds)

Logging or notification improvements

Web UI or dashboard

Dockerization / deploy scripts

🧼 Code Style:
Use clear, descriptive variable names

Keep functions focused (single responsibility)

Follow Python's PEP8 formatting

Use black or ruff for auto-formatting

💡 Before submitting:
Test your code thoroughly

Comment where logic isn't obvious

Submit 1 feature per pull request

Link related issues in your PR message
