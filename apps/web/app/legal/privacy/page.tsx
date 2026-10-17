import type { Metadata } from "next";
import type { ReactNode } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Banner, Card, PageHeader } from "@/components/ui";

/* DRAFT privacy policy. Statements about what WEZA does are taken from the code (data collected, encryption,
 * redaction, providers). Everything in [BRACKETS] is a fact only the organisation can supply, and the whole text
 * needs legal review against Uganda's Data Protection and Privacy Act, 2019 before it is published.
 * When approved: fill the placeholders, set IS_DRAFT = false and update LAST_UPDATED. */
const IS_DRAFT = true;
const LAST_UPDATED = "[DATE]";
const ORG = "[ORGANISATION LEGAL NAME]";
const CONTACT = "[PRIVACY CONTACT EMAIL]";

export const metadata: Metadata = { title: "Privacy policy" };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card title={title}>
      <div className="space-y-3 text-[15px] leading-relaxed text-ink">{children}</div>
    </Card>
  );
}

export default function PrivacyPolicy() {
  return (
    <PublicShell>
      <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-8">
        <PageHeader title="Privacy policy" subtitle={`How WEZA handles your personal information. Last updated: ${LAST_UPDATED}.`} />
        {IS_DRAFT && (
          <Banner tone="warning" title="Draft — not yet approved">
            This text is awaiting legal review. Items in [brackets] are still to be completed by {ORG}.
          </Banner>
        )}

        <Section title="1. Who we are">
          <p>
            WEZA is operated by {ORG}, [REGISTERED ADDRESS], Uganda (&ldquo;WEZA&rdquo;, &ldquo;we&rdquo;). We are
            the data controller for the personal information described here. You can contact us about privacy at{" "}
            {CONTACT}. [DATA PROTECTION OFFICER NAME AND CONTACT, IF APPOINTED.]
          </p>
          <p>
            WEZA is a marketplace that connects people and businesses looking for financing with financial
            institutions. WEZA does not lend money or make credit decisions.
          </p>
        </Section>

        <Section title="2. What we collect">
          <ul className="list-disc space-y-1.5 pl-5">
            <li><b>Your phone number and messages</b> when you write to WEZA on WhatsApp or use our website, including button choices and the time of each message.</li>
            <li><b>Your financing request</b>: amount, purpose, whether you are an individual, business or farmer, sector and district.</li>
            <li><b>Profile answers</b> you choose to give about your business, employment or farm.</li>
            <li><b>Identity details</b> you choose to give, such as your name and National ID number.</li>
            <li><b>Financial information</b> you give us, such as turnover or income and existing repayments.</li>
            <li><b>Documents</b> you send us, such as payslips, bank or mobile-money statements, IDs and business registration documents (photos or PDFs).</li>
            <li><b>Consent records</b>: which institution you agreed to share with, what was shared, the consent version, and any withdrawal.</li>
            <li><b>Technical and security information</b>: one-time verification codes, request counts used to stop abuse, and a one-way coded (hashed) form of your IP address.</li>
            <li><b>Institution staff accounts</b>: name, work email, role and an activity (audit) log of actions taken in WEZA.</li>
          </ul>
        </Section>

        <Section title="3. How we use it">
          <ul className="list-disc space-y-1.5 pl-5">
            <li>To understand your financing request and ask the questions needed to complete it.</li>
            <li>To verify that you control your phone number.</li>
            <li>To match your request with financial institutions whose products and criteria fit it.</li>
            <li>To share your information with an institution <b>only after you give consent</b> for that institution.</li>
            <li>To send you updates about your request on the channel you use (WhatsApp or SMS).</li>
            <li>To keep WEZA secure, prevent fraud and abuse, keep an audit trail and meet legal obligations.</li>
            <li>To measure and improve how well matching works, using aggregated information.</li>
          </ul>
          <p>[LEGAL BASIS FOR EACH PURPOSE UNDER THE DATA PROTECTION AND PRIVACY ACT, 2019 — TO BE CONFIRMED BY LEGAL REVIEW.]</p>
        </Section>

        <Section title="4. Who we share it with">
          <ul className="list-disc space-y-1.5 pl-5">
            <li>
              <b>Financial institutions you choose.</b> Only after you consent, and only the categories listed on the
              consent screen (see <a className="underline" href="/legal/consent">Consent &amp; privacy</a>). Each
              institution makes its own checks and decisions and is responsible for the information it receives.
            </li>
            <li>
              <b>WhatsApp (Meta Platforms).</b> Messages between you and our WhatsApp number are carried by WhatsApp and
              are also subject to WhatsApp&rsquo;s own terms and privacy policy. Our staff may also see these messages in
              the WhatsApp Business app on our number.
            </li>
            <li>
              <b>AI service provider.</b> When enabled, the text of your request may be sent to an AI provider
              (Anthropic) so that WEZA can understand it. Phone numbers, National ID numbers and email addresses are
              removed from that text first. Decisions about matching are made by WEZA&rsquo;s own rules, and lending
              decisions are made by institutions.
            </li>
            <li><b>Infrastructure providers</b> who host WEZA and, where used, send SMS messages: [HOSTING AND SMS PROVIDERS].</li>
            <li><b>Authorities</b>, where the law requires it.</li>
          </ul>
          <p>We do not sell your personal information, and we do not use it for advertising.</p>
        </Section>

        <Section title="5. Transfers outside Uganda">
          <p>
            Some providers above may process information outside Uganda. [COUNTRIES AND SAFEGUARDS USED FOR THESE
            TRANSFERS — TO BE CONFIRMED BY LEGAL REVIEW.]
          </p>
        </Section>

        <Section title="6. How we protect it">
          <ul className="list-disc space-y-1.5 pl-5">
            <li>Identity details are kept in an encrypted identity vault, separate from your request.</li>
            <li>Uploaded documents are checked for malware and file type, then stored encrypted. Rejected files are deleted.</li>
            <li>Phone numbers used for look-ups are stored as keyed one-way codes rather than in plain text.</li>
            <li>WhatsApp messages waiting to be processed are stored encrypted and their content is wiped once processed.</li>
            <li>Staff access is limited by role and recorded in an audit log; administrator actions can require multi-factor authentication.</li>
          </ul>
        </Section>

        <Section title="7. How long we keep it">
          <p>[RETENTION PERIODS FOR EACH CATEGORY OF INFORMATION — TO BE DECIDED. WEZA does not yet delete records automatically, so the periods chosen here must also be implemented before publication.]</p>
        </Section>

        <Section title="8. Your rights">
          <p>Under Uganda&rsquo;s Data Protection and Privacy Act, 2019 you can, among other rights:</p>
          <ul className="list-disc space-y-1.5 pl-5">
            <li>ask for a copy of the personal information we hold about you;</li>
            <li>ask us to correct information that is wrong;</li>
            <li>object to processing, or ask us to delete your information where the law allows;</li>
            <li>withdraw a consent at any time in WEZA. Withdrawal stops future sharing by WEZA but cannot remove information an institution has already lawfully received.</li>
          </ul>
          <p>
            To use these rights, or to stop receiving messages from us, contact {CONTACT}. [RESPONSE TIME.] You can
            also complain to Uganda&rsquo;s Personal Data Protection Office.
          </p>
        </Section>

        <Section title="9. Cookies and browser storage">
          <p>
            The website uses no advertising or third-party tracking cookies. If you use the website, your browser
            stores a session token so that you can continue your request. Staff sign-in uses a secure, HTTP-only
            cookie.
          </p>
        </Section>

        <Section title="10. Changes to this policy">
          <p>We will post any changes on this page and update the date above. [HOW SIGNIFICANT CHANGES WILL BE NOTIFIED.]</p>
        </Section>
      </div>
    </PublicShell>
  );
}
