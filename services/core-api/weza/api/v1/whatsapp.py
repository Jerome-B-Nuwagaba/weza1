import httpx

from weza.config import settings


async def send_whatsapp_text(to_phone: str, message_text: str):
    url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {"body": message_text}
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()