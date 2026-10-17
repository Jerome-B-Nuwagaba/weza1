"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Badge, Banner, Button, Card, ErrorState, KV, Loading, PageHeader, Table, Td } from "@/components/ui";

/** Connect the organisation's WhatsApp Business app number to WEZA (coexistence) with Meta Embedded Signup.
 * The browser only receives a one-time code (valid ~30 s); the server exchanges it, subscribes the app to the
 * account's webhooks and reports the number's status. Nothing is registered or migrated. */

declare global {
  interface Window {
    FB?: any;
    fbAsyncInit?: () => void;
  }
}

type LaunchConfig = {
  ready: boolean; missing: string[]; app_id: string | null; config_id: string | null; graph_version: string;
  feature_type: string; session_info_version: string;
  current: { waba_id: string | null; phone_number_id: string | null };
};

type Session = { event?: string; waba_id?: string; phone_number_id?: string };

const SDK_SRC = "https://connect.facebook.net/en_US/sdk.js";

function fromFacebook(origin: string): boolean {
  try {
    const host = new URL(origin).hostname;
    return host === "facebook.com" || host.endsWith(".facebook.com");
  } catch {
    return false;
  }
}

export default function WhatsAppConnection() {
  const cfg = useApi<LaunchConfig>("/admin/whatsapp/embedded-signup");
  const [sdkReady, setSdkReady] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<any>(null);
  const session = useRef<Session>({});

  const c = cfg.data;

  // Load and initialise the Facebook JS SDK once the launch settings are known.
  useEffect(() => {
    if (!c?.ready || !c.app_id) return;
    window.fbAsyncInit = () => {
      window.FB.init({ appId: c.app_id, autoLogAppEvents: true, xfbml: false, version: c.graph_version });
      setSdkReady(true);
    };
    if (window.FB) window.fbAsyncInit();
    else if (!document.querySelector(`script[src="${SDK_SRC}"]`)) {
      const s = document.createElement("script");
      s.src = SDK_SRC;
      s.async = true;
      s.defer = true;
      s.crossOrigin = "anonymous";
      s.onerror = () => setNotice("Could not load the Facebook SDK. Check your connection or content blockers.");
      document.body.appendChild(s);
    }
  }, [c?.ready, c?.app_id, c?.graph_version]);

  // Session info from the Embedded Signup window (WABA id, finish/cancel event).
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!fromFacebook(event.origin) || typeof event.data !== "string") return;
      let data: any;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (data?.type !== "WA_EMBEDDED_SIGNUP") return;
      if (data.event === "CANCEL") {
        const why = data.data?.error_message || (data.data?.current_step ? `closed at step ${data.data.current_step}` : "closed");
        setNotice(`Sign-up was not finished (${why}). Nothing was changed.`);
        return;
      }
      session.current = { event: data.event, waba_id: data.data?.waba_id, phone_number_id: data.data?.phone_number_id };
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const submit = (code: string) => {
    setPending(true);
    setError(null);
    api("/admin/whatsapp/embedded-signup", {
      method: "POST",
      body: { code, waba_id: session.current.waba_id || null, event: session.current.event || null },
    })
      .then((r) => setResult(r))
      .catch((e) => setError(e as ApiError))
      .finally(() => setPending(false));
  };

  const launch = () => {
    if (!c || !window.FB) return;
    setNotice(null);
    setError(null);
    setResult(null);
    session.current = {};
    // The Facebook SDK rejects async callbacks: keep this a plain function. The code expires in ~30 s.
    window.FB.login(
      (response: any) => {
        const code = response?.authResponse?.code;
        if (code) submit(code);
        else setNotice((n) => n || "Sign-up was cancelled. Nothing was changed.");
      },
      {
        config_id: c.config_id,
        response_type: "code",
        override_default_response_type: true,
        extras: { setup: {}, featureType: c.feature_type, sessionInfoVersion: c.session_info_version },
      },
    );
  };

  return (
    <>
      <PageHeader
        title="WhatsApp connection"
        subtitle="Connect the organisation's WhatsApp Business app number to WEZA (coexistence). Staff keep using the app; WEZA answers through the Cloud API."
      />
      {cfg.loading ? <Loading /> : cfg.error ? <ErrorState error={cfg.error} onRetry={cfg.reload} /> : c && (
        <div className="space-y-4">
          {!c.ready && (
            <Banner tone="warning" title="Embedded Signup is not configured">
              Set {c.missing.join(", ")} in the API settings (scripts/configure_env.py) and restart the API.
              See docs/WHATSAPP_GO_LIVE.md, Phase 1–2.
            </Banner>
          )}

          <Card title="Before you start">
            <ul className="list-disc space-y-1 pl-5 text-[14px] text-ink">
              <li>Have the phone with the business number at hand, with WhatsApp Business app 2.24.17 or newer: WhatsApp shows a code there to confirm.</li>
              <li>Sign in with a Facebook account that administers the organisation's Business Portfolio.</li>
              <li>Choose to connect your <b>existing WhatsApp Business app</b> account. Do not delete the account from the app.</li>
              <li>WEZA does not register or migrate the number, and doesn't import past chats.</li>
            </ul>
            <div className="mt-4 flex items-center gap-3">
              <Button onClick={launch} disabled={!c.ready || !sdkReady || pending} pending={pending}>
                Connect WhatsApp Business app number
              </Button>
              {c.ready && !sdkReady && <span className="text-[13px] text-muted">Loading Facebook…</span>}
            </div>
          </Card>

          {notice && <Banner tone="warning">{notice}</Banner>}
          {error && <ErrorState error={error} />}

          {result && (
            <Card title="Result" subtitle="Copy the settings below into the API settings, restart, then run scripts/whatsapp_account_check.py.">
              <KV items={[
                ["WhatsApp Business Account", result.waba_id],
                ["Webhooks subscribed", result.subscribed ? <Badge tone="success">yes</Badge> : <Badge tone="danger">no</Badge>],
                ["Coexistence active", result.coexistence ? <Badge tone="success">yes</Badge> : <Badge tone="warning">not yet</Badge>],
                ["Meta event", result.event || "—"],
              ]} />
              {result.warnings.map((w: string) => <Banner key={w} tone="warning" className="mt-3">{w}</Banner>)}
              {result.phone_numbers.length > 0 && (
                <div className="mt-4">
                  <Table head={["Phone number ID", "Number", "Name", "Platform", "On the app", "Business number"]}>
                    {result.phone_numbers.map((n: any) => (
                      <tr key={n.id}>
                        <Td className="font-mono text-[12px]">{n.id}</Td>
                        <Td>{n.number}</Td>
                        <Td>{n.verified_name || "—"}</Td>
                        <Td>{n.platform_type || "—"}</Td>
                        <Td>{n.is_on_biz_app ? "yes" : "no"}</Td>
                        <Td>{n.is_business_number ? "yes" : "—"}</Td>
                      </tr>
                    ))}
                  </Table>
                </div>
              )}
              <div className="mt-4 text-[13px] font-semibold text-ink">
                {result.settings_already_match ? "The API settings already match." : "Settings to set (not secrets):"}
              </div>
              {!result.settings_already_match && (
                <pre className="mt-1 overflow-x-auto rounded-lg bg-canvas p-3 text-[12.5px]">
                  {Object.entries(result.settings).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join("\n")}
                </pre>
              )}
              <ol className="mt-3 list-decimal space-y-1 pl-5 text-[13.5px] text-muted">
                <li>Assign this WhatsApp Business Account to the system user behind WHATSAPP_TOKEN (Business Settings → System users).</li>
                <li>In the Meta app → WhatsApp → Configuration, subscribe the <b>messages</b> and <b>account_update</b> fields.</li>
                <li>Restart the API and run the live acceptance checklist (docs/WHATSAPP_GO_LIVE.md §7).</li>
              </ol>
            </Card>
          )}

          <Card title="Currently configured">
            <KV items={[["WABA ID", c.current.waba_id], ["Phone number ID", c.current.phone_number_id]]} />
          </Card>
        </div>
      )}
    </>
  );
}
