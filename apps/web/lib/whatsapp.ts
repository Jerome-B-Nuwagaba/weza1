/** Deep link into the business WhatsApp number. The first message carries the customer's need (so the chat
 * starts where the website left off) and a short acquisition reference the API reads and strips:
 * "(ref:src~cmp~ptn~ref)". Keep this format in sync with weza/domains/notification/whatsapp_inbound.py. */
export function whatsappHref(number: string, text: string, attribution: Record<string, string> = {}): string {
  const clean = (v?: string) => (v || "").replace(/[^A-Za-z0-9_.-]/g, "").slice(0, 40);
  const parts = ["src", "cmp", "ptn", "ref"].map((k) => clean(attribution[k]));
  const ref = parts.some(Boolean) ? `\n(ref:${parts.join("~")})` : "";
  return `https://wa.me/${number}?text=${encodeURIComponent((text.trim() || "Hi") + ref)}`;
}
