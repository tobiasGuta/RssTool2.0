import discord
import asyncio
import json
import os


INPUT_FILE = "webhook_request.json"
OUTPUT_FILE = "webhook_result.json"
BOT_TOKEN = os.getenv("Discord")

if not BOT_TOKEN:
    raise ValueError(" Discord not set. Use: export Discord='your_token'")

intents = discord.Intents.default()
intents.guilds = True

class WebhookBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.result = None

    async def on_ready(self):
        try:
            print(f"[+] Logged in as {self.user}")
            with open(INPUT_FILE, 'r') as f:
                data = json.load(f)

            guild_id = int(data['guild_id'])
            channel_id = int(data['channel_id'])
            name = data.get("name", "RSSBot")

            guild = discord.utils.get(self.guilds, id=guild_id)
            if not guild:
                print("Guild not found")
                await self.close()
                await self.http._HTTPClient__session.close()
                return

            channel = discord.utils.get(guild.text_channels, id=channel_id)
            if not channel:
                print("Channel not found")
                await self.close()
                await self.http._HTTPClient__session.close()
                return

            
            existing_webhooks = await channel.webhooks()
            for webhook in existing_webhooks:
                if webhook.name == name:
                    self.result = webhook.url
                    print(f"[+] Found existing webhook: {self.result}")
                    break

           
            if not self.result:
                webhook = await channel.create_webhook(name=name)
                self.result = webhook.url
                print(f"[+] Created new webhook: {self.result}")

            
            with open(OUTPUT_FILE, 'w') as f:
                json.dump({"webhook_url": self.result}, f)

        except Exception as e:
            print(f"[ERROR] {e}")

        await self.close()
        await self.http._HTTPClient__session.close()

def run_bot():
    client = WebhookBot(intents=intents)
    asyncio.run(client.start(BOT_TOKEN))

if __name__ == "__main__":
    run_bot()
