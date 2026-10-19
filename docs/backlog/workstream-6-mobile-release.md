# Workstream 6: Mobile Customer App And Release Packaging

## Goal

Harden the Flutter customer app for V1 demo/release and support QA where mobile scope ends.

## Why It Matters

V1 mobile is customer-only. It should reliably start/resume journeys, show requests and profile/status, and build as a credible APK artifact.

## Repo Orientation

- Mobile app: `apps/mobile`.
- API client: `apps/mobile/lib/api.dart`.
- Chat screen: `apps/mobile/lib/screens/chat.dart`.
- Requests/status: `apps/mobile/lib/screens/requests.dart`.
- Theme: `apps/mobile/lib/theme.dart`.
- Android config: `apps/mobile/android/app/build.gradle.kts`.
- CI mobile job: `.github/workflows/ci.yml:88-113`.
- Run `flutter pub get`, `flutter analyze`, `flutter test`, `flutter build apk --release --dart-define=WEZA_API_URL=<api>`.
- Backend API is same `/api/v1` as web.
- No institution mobile scope in V1.

## Backlog Order

1. B-020: Mobile release hardening.
2. Help WS5 with B-028 manual QA after B-020.
3. Support B-026 only if shared API types affect mobile docs/contracts.

## Owns / Avoids

Owns `apps/mobile`. Avoid API changes; request backend contract changes from WS3/WS4.

## Verification

Run Flutter analyze/test/build. Manual emulator flow: start journey, verify OTP display in dev mode, answer profile, view requests/status, withdraw opportunity where available.

## Definition Of Done

Android package metadata is no longer template-default, CI passes, and README/test notes explain API URL configuration.

## First-Day Checklist

Run current Flutter tests/build, inspect Android TODOs, then start B-020.
