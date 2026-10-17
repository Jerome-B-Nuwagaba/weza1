# Workstream 5: Web UX, Accessibility And Manual QA

## Goal

Make the web surfaces testable and release-ready: admin config UX, accessibility, API typing and repeatable manual QA.

## Why It Matters

The backend has broad capability, but users experience WEZA through customer, institution and admin screens. V1 needs accessible, stable, low-surprise UI.

## Repo Orientation

- Web app: `apps/web`.
- API client: `apps/web/lib/api.ts` (COORDINATE WITH WHATSAPP OWNER).
- Customer pages: `apps/web/app/start`, `apps/web/app/c`.
- Institution pages: `apps/web/app/institution`.
- Admin pages: `apps/web/app/admin`.
- Shared UI: `apps/web/components`.
- Run `npm install`, `npm run dev`, `npm run typecheck`, `npm run build`.
- Backend API must be running for manual flows.
- Do not edit `/whatsapp-sim` or "Continue on WhatsApp" without WhatsApp-owner coordination.
- Coordinate API contract changes with WS3/WS4.

## Backlog Order

1. B-008 UI part: admin/config view for question paths if backend exposes it.
2. B-019: Accessibility QA pass and automated checks.
3. B-026: Frontend API type generation/shared contracts.
4. B-025: Localisation foundation or documented English-only V1.
5. B-028: Admin UX smoke/manual scripts.

## Owns / Avoids

Owns `apps/web` except WhatsApp simulator/channel surfaces. Avoid backend changes unless paired with WS3/WS4.

## Verification

Run typecheck/build. Manual smoke: landing/start, customer status/profile/documents, institution feed/opportunity/product/appetite/routing/billing, admin graph/config/deliveries.

## Definition Of Done

Critical flows build cleanly, accessibility findings are fixed or documented, and manual QA has exact steps and expected results.

## First-Day Checklist

Run web build, list pages against blueprint screen inventory, then start B-019.
