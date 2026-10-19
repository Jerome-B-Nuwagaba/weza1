from fastapi import APIRouter, Request, Response, HTTPException, status
from weza.config import settings
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# 1. Meta Challenge Verification (Required by Meta when saving Webhook URL)
@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")

# 2. Inbound Message Receiver
@router.post("/whatsapp")
async def handle_whatsapp_message(request: Request):
    body = await request.json()
    
    try:
        entries = body.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                
                if messages:
                    msg = messages[0]
                    from_phone = msg.get("from") # Customer E.164 phone number
                    
                    # Extract text or interactive button response
                    msg_type = msg.get("type")
                    text_content = ""
                    if msg_type == "text":
                        text_content = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        text_content = msg.get("interactive", {}).get("button_reply", {}).get("title", "")
                    
                    # Pass message to WEZA Router (checks info requests, consent, or natural language intake)
                    await process_inbound_customer_message(from_phone, text_content)

    except Exception as e:
        logger.error(f"Error parsing WhatsApp webhook: {str(e)}")
        
    return {"status": "success"} # Meta requires a 200 OK within 3 seconds