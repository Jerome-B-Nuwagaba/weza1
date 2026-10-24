"""Conventional Meta webhook path for WhatsApp: /api/v1/webhooks/whatsapp.

This module is only an address. The live implementation lives in `weza.api.v1.public`:
`whatsapp_verify` (the GET challenge) and `whatsapp_webhook` (the POST that verifies the
X-Hub-Signature-256 signature, stores the message in the durable inbox and queues it for the
worker). Both are re-used verbatim, so the webhook cannot be reached through a weaker path.

The canonical channel path remains /api/v1/channels/whatsapp/webhook — Meta may point at either.
"""

from fastapi import APIRouter

from weza.api.v1.public import whatsapp_verify, whatsapp_webhook

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

router.add_api_route("/whatsapp", whatsapp_verify, methods=["GET"], include_in_schema=False)
router.add_api_route("/whatsapp", whatsapp_webhook, methods=["POST"], include_in_schema=False)
