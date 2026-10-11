import { PublicShell } from "@/components/PublicShell";
import { Button } from "@/components/ui";

export const metadata = { title: "For institutions" };

export default function ForInstitutions() {
  return (
    <PublicShell>
      <section className="border-b border-line bg-surface">
        <div className="mx-auto max-w-5xl px-4 py-16">
          <p className="mb-3 text-[13px] font-semibold uppercase tracking-[0.14em] text-gold-700">WEZA Institutional</p>
          <h1 className="max-w-3xl font-serif text-4xl leading-tight text-ink sm:text-5xl">Tell WEZA what customers you want.</h1>
          <p className="mt-4 max-w-2xl text-[17px] text-muted">
            Join the WEZA network, configure your products and current lending appetite, and receive consented, qualified opportunities — without connecting your core banking system or sharing a single existing customer record.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button href="/institution/join" size="lg">Join WEZA</Button>
            <Button href="/login" size="lg" variant="secondary">Sign in</Button>
          </div>
        </div>
      </section>
      <section className="mx-auto grid max-w-5xl gap-4 px-4 py-12 md:grid-cols-2">
        {[
          ["Zero core integration", "No core banking, CRM, LOS or data-warehouse connection. You configure everything inside WEZA."],
          ["Products and appetite, separately", "Products say what you can offer. Appetite says who you want WEZA to find now — simulate it against real anonymised demand before going live."],
          ["Qualified, consented opportunities", "Every opportunity is phone-verified, profiled, matched with explainable reasons and shared only with explicit customer consent."],
          ["You keep the credit decision", "WEZA routes and tracks. You do KYC, underwriting, approval and disbursement through your own process, and report lightweight outcomes."],
        ].map(([t, d]) => (
          <div key={t} className="rounded-xl border border-line bg-surface p-5">
            <div className="font-semibold text-ink">{t}</div>
            <p className="mt-1 text-[14px] text-muted">{d}</p>
          </div>
        ))}
      </section>
    </PublicShell>
  );
}
