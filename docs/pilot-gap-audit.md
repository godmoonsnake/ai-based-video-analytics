# DARSON pilot gap audit

Audited against the current working tree before adding new features.

| Area | Implemented | Partially implemented | Missing | Blocked |
|---|---|---|---|---|
| E5 response | assignment, response episodes, action audit, SOP snapshots/ordered steps, authenticated server actor, handover, optimistic incident version CAS | response detail panel has assign/ack/respond/steps but no full supervisor resolution UI, role-specific queue, accessible stale refresh | queue UX permissions/statuses and end-to-end browser-auth path | live authenticated workflow requires deployment OIDC |
| E6 SLA | immutable policy snapshot, deadline evaluation jobs, durable breach ledger, SLA read endpoint | worker creates repeated time-bucketed checks; no escalation levels or delivery state | provider abstraction, notification outbox, attempt/acceptance/ack state, retry UI | real provider intentionally disabled for demos |
| E7 UI | existing redesigned incident feed/detail; response panel; server-side role checks | no OIDC login/session UI; response panel lacks stale-state recovery and evidence status | auth lifecycle, role-aware site context, command center health/age/SLA/workload | live login depends on configured IdP |
| E8 exports | scoped JSON and formula-safe CSV; audit record on request | synchronous, not version-pinned, endpoint responds directly | durable export job, PDF, ZIP media package, expiry/download authorization/audit | media packaging depends on authorized production evidence storage |
| E9 health | DB readiness, aggregate queue/evidence/source counts; source lease freshness | no frame-level/recording probes; no separate live/recording/evidence quality model | FPS/freeze/black/blur/dark, retrieval gaps, freshness/latency metrics, maintenance windows | real stream tests need Frigate/video runtime |
| E10 pilot packaging | restricted Compose overlay, replay/mock fixtures, gap documentation | no deterministic full scenario manifest/reset or polished review mode | full scenario suite, demo banners, runbook/backup/restore and release evidence | live multi-service acceptance is blocked by unavailable Docker daemon |

This is a code inspection inventory, not a production-readiness assertion.
