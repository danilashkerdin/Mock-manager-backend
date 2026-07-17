import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class SlackNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
    
    async def send(self, message: str, title: Optional[str] = None):
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured")
            return
        
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": title or "Mock Manager Notification"
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": message
                            }
                        }
                    ]
                }
                await client.post(self.webhook_url, json=payload)
                logger.info("Slack notification sent")
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")