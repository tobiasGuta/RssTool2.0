"""
start.py — RssTool2.0 process supervisor

FIX: replaces the original crash-and-exit approach with a proper supervisor
that restarts each service independently with exponential backoff.

Services started:
  rss_alerts.py       — RSS + Twitch polling engine
  slash_control_bot.py — Discord slash-command interface
  dashboard.py        — local web dashboard (phone + desktop)
"""

import asyncio
import sys
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [supervisor] %(message)s",
)
log = logging.getLogger("supervisor")

SERVICES = [
    {"name": "RSS Alerts",  "script": "rss_alerts.py"},
    {"name": "Discord Bot", "script": "slash_control_bot.py"},
    {"name": "Dashboard",   "script": "dashboard.py"},
]

MAX_RESTARTS = int(os.getenv("MAX_RESTARTS", 10))
BASE_DELAY   = 2


async def _supervise(service: dict):
    name   = service["name"]
    script = service["script"]

    if not os.path.exists(script):
        log.warning(f"[{name}] {script} not found — skipping.")
        return

    restarts = 0
    while True:
        log.info(f"[{name}] Starting (attempt {restarts + 1})...")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def _stream():
            async for raw in proc.stdout:
                print(f"[{name}] {raw.decode(errors='replace').rstrip()}", flush=True)

        st = asyncio.create_task(_stream())
        await proc.wait()
        st.cancel()

        code = proc.returncode
        if code == 0:
            log.info(f"[{name}] Exited cleanly.")
            return

        restarts += 1
        if restarts > MAX_RESTARTS:
            log.error(f"[{name}] Exceeded {MAX_RESTARTS} restarts — giving up.")
            return

        delay = min(BASE_DELAY ** restarts, 60)
        log.warning(f"[{name}] Crashed (exit {code}). Restart {restarts}/{MAX_RESTARTS} in {delay}s...")
        await asyncio.sleep(delay)


async def main():
    log.info("=" * 50)
    log.info("  RssTool2.0 Supervisor starting")
    log.info("=" * 50)
    tasks = [asyncio.create_task(_supervise(s)) for s in SERVICES]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    log.info("All services have stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[supervisor] Shutting down — goodbye.")
