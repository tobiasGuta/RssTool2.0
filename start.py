import subprocess
import sys
import time
import os
from dotenv import load_dotenv

load_dotenv()

def main():
    print("Starting RssTool2.0 services...")

    processes = []

    try:
        # Start RSS Alerts
        print("[+] Starting RSS Alerts...")
        p1 = subprocess.Popen([sys.executable, "rss_alerts.py"])
        processes.append(p1)

        # Start Slash Control Bot
        print("[+] Starting Slash Control Bot...")
        p2 = subprocess.Popen([sys.executable, "slash_control_bot.py"])
        processes.append(p2)

        print("All services started. Press Ctrl+C to stop.")
        
        while True:
            time.sleep(1)
            # Check if any process has died
            for p in processes:
                if p.poll() is not None:
                    print(f"Process {p.args} died. Exiting...")
                    raise KeyboardInterrupt

    except KeyboardInterrupt:
        print("\nStopping services...")
        for p in processes:
            p.terminate()
        print("Services stopped.")

if __name__ == "__main__":
    main()
