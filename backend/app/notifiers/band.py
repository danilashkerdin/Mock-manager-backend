import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class BandNotifier:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url
    
    async def send(self, message: str, title: Optional[str] = None):
        if not self.webhook_url:
            logger.warning("Band webhook URL not configured")
            return
        
        try:
            async with httpx.AsyncClient() as client:
                # Формат для Band/Mattermost webhook
                payload = {
                    "text": f"### {title or 'Mock Manager'}\n{message}",
                    "username": "Mock Manager",
                    "icon_url": "https://your-icon-url.com/icon.png"  # опционально
                }
                response = await client.post(self.webhook_url, json=payload)
                if response.status_code == 200:
                    logger.info("Band notification sent successfully")
                else:
                    logger.error(f"Band notification failed: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Failed to send Band notification: {e}")