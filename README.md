# DARSON single-site pilot

The active pilot is one camera, one Frigate polygon and a restricted-hours schedule, with a guard task queue, acknowledgement/outcomes, protected incident evidence and guard/supervisor notification routing. See [the pilot runbook](docs/pilot/README.md) for configuration, retention, real-recorder testing, signed acceptance criteria and ML evaluation. Live recorder compatibility, hardware capacity, external phone delivery and offline sign-in remain unverified until tested at the site.

The six case-study and parking prototypes remain experimental and are blocked when `DARSON_PILOT_MODE=true`. They are not proven live detectors or pilot pitch claims. Research demos remain available only outside the pilot; development notifications are suppressed.

The guard UI, pilot backend, migrations and local regression checks are implemented; see [the dated validation record](docs/pilot/validation-2026-10-12.md). Open a safe local example with `powershell -ExecutionPolicy Bypass -File .\scripts\start-pilot-review.ps1` at `http://127.0.0.1:8081`. This uses its own simulated SQLite database and suppresses external messages.

DARSON turns source events into explainable incident cases, supports evidence review and accountable operator response, and provides service-health signals. It is a security decision-support and operational-coordination system. Detection, behaviour and cross-camera correlation results are signals for human review and are not proof of identity, criminal activity or wrongdoing.

## Current implementation

The current uncommitted workspace contains tenant/site-scoped ingestion and processing, correlation lineage and hypotheses, encrypted evidence handling, response/SOP actions, SLA breach records with a local notification adapter, OIDC API authorization and a browser sign-in flow, version-pinned asynchronous PDF/ZIP exports, camera/recording/evidence telemetry, and a restricted production Compose profile. JSON and CSV case exports remain available. Review the exact current gaps in [pilot-gap-audit.md](docs/pilot-gap-audit.md) and [pilot-implementation-gaps.md](docs/pilot-implementation-gaps.md).

The company-review interface and local path have been validated without Docker. The repository's old `.venv` points to a missing Python installation. Docker Desktop is running, but its current image-pull proxy returns an invalid HTTPS response for Docker Hub. This is not a production-readiness claim.

## Development and deterministic demo

Requirements: Python 3.12, Node 20+, and Docker Compose v2 for the full stack. The local API uses the development-only fixed `development/site_a` scope and a supervisor actor; it is not an authentication deployment pattern.

To open the site without Docker on this machine, run `powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1` from the repository root. It starts the API and background jobs worker on `127.0.0.1:8000` and the Vite frontend on `127.0.0.1:8080`, using isolated `backend/var/review-demo-v3.db`. Existing local databases are preserved. Open [http://127.0.0.1:8080](http://127.0.0.1:8080), select **Platform overview**, then **Load guided review**. Three synthetic cases are created through the canonical ingest, correlation and incident pipeline. Repeating the action is idempotent. One four-camera case has synthetic media in the protected vault, one has only single-camera context, and one deliberately has unavailable media. The same screen opens the case dossier and operations console. **Service assurance** connects camera health, monitoring metrics and assigned work; **Investigation** connects search and historical patterns. Missing probe data is shown as unknown rather than healthy. This local path does not run Frigate, MQTT or PostgreSQL.

```powershell
cd C:\Users\Noah\Darson\Darson\darson-intel
docker compose up -d --build
Invoke-RestMethod -Method Post http://localhost:8080/events/ingest/mock
Invoke-RestMethod -Method Post http://localhost:8080/tracks/correlate
Invoke-RestMethod -Method Post http://localhost:8080/incidents/build
```

The legacy `.\scripts\demo.ps1` and mock endpoints remain available for pipeline development. The owner-review fixture is `backend/scenarios/review_v1.json`; its manifest is available at `/api/v1/demo/manifest` in development. Its replay endpoint is disabled in production.

## Authentication and scope

The browser uses OIDC Authorization Code with PKCE when `DARSON_AUTH_ISSUER` and `DARSON_OIDC_CLIENT_ID` are configured as frontend build arguments. The API verifies bearer tokens against configured issuer, audience and HTTPS JWKS, then derives tenant/site/role from provisioned server-side grants. Caller-supplied tenant, site and actor headers are not trusted. Production requires an identity-provider SPA registration, exact redirect/logout origins, role grants, MFA policy where appropriate, and an authenticated TLS ingress. The browser session is held in memory; logout calls the API revocation endpoint and the identity provider's end-session endpoint when available.

The backend remains authoritative for incident, response, evidence, export and configuration permissions. Responders are limited to assigned work. PostgreSQL tenant policies and the SQLite ORM scope filters are defense-in-depth; live PostgreSQL role/RLS validation remains outstanding.

## Evidence, response and service levels

Evidence is stored in the encrypted local object store, authorized through the API, hash-checked on retrieval, audited, and subject to expiry/retention holds. Source URLs and object keys must not be exposed to the browser or in reports. Response episodes record assignment, acknowledgement, response, SOP steps, resolution and handover with optimistic version checks. SLA clocks are based on the configured policy snapshot; breach history is persisted and a local/no-send notification adapter records attempts. External delivery, real on-call escalation and multi-level escalation schedules require deployment-specific provider approval and remain incomplete.

PDF and ZIP reports are generated asynchronously from a pinned case snapshot and downloads recheck authorization and audit access. ZIP includes the report, case/timeline data, evidence hashes/provenance and available authorized media; missing or integrity-failed media is represented in its manifest. Reports are operational records and require human review.

Camera health separates stream, video quality, recording availability and evidence capture. Frame comparison is combined with source FPS and a debounce window; static scenes alone are not called frozen. These probes require a reachable, authenticated Frigate API and have not been tested against a live camera/VMS in this environment.

## Pilot deployment configuration

Use `docker-compose.production.yml` as a restricted single-host profile behind an authenticated TLS ingress. It removes public DB, MQTT and Frigate ports, separates app/database/source networks, runs Alembic through a migration service and uses a restricted runtime database URL. PostgreSQL bootstrap roles are created only when its data volume is initialized; existing volumes need a reviewed/manual role migration. The runtime role must not own the schema or be a superuser.

Supply secrets outside Git and image build arguments. Required deployment values include `POSTGRES_PASSWORD`, `DARSON_MIGRATION_DB_PASSWORD`, `DARSON_RUNTIME_DB_PASSWORD`, `DARSON_MIGRATION_DATABASE_URL`, `DARSON_RUNTIME_DATABASE_URL`, `DARSON_MQTT_PASSWORD`, `DARSON_EVIDENCE_KEY`, `DARSON_SPOOL_KEY`, OIDC issuer/audience/JWKS/client ID, worker tenant/site, source identity, and protected file paths for the Mosquitto password/ACL and Frigate config. `DARSON_FRIGATE_API_TOKEN` is server-side only. Use a deployment secret manager or protected files; never commit secret values. Verify Frigate token scope, broker ACLs, TLS termination, backup encryption, key recovery, retention/hold policy and staffed escalation ownership before a pilot.

The profile provides network isolation and configuration hooks; it does not prove external reachability restrictions, token scope, credential rotation, database least privilege, backup recovery, or customer-specific deployment security. The Frigate config must enable authentication and restrict the API to the application network. MQTT should deny anonymous access and limit the Frigate and DARSON accounts to required topics.

## Validation commands

```powershell
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
cd ..\frontend
npm ci
npm test
npm run build
npm run e2e:install
npm run e2e
```

For container validation, start the stack first and run `docker compose -f docker-compose.yml -f docker-compose.production.yml config` with deployment variables set. Browser E2E targets `http://localhost:8080`. Playwright requires the Docker stack and browser binary. Docker image pulls currently fail through Docker Desktop's proxy; do not report Docker/PostgreSQL/browser E2E as passed until rerun successfully.

## Backup, recovery and limitations

Back up PostgreSQL, encrypted evidence objects, encrypted spool state and their encryption keys together. Test restore into an isolated deployment before relying on recovery. Durable queues and encrypted spools support restart recovery, but live broker/database/object-store restart testing has not been performed here. The single-host local evidence store has no demonstrated replication or disaster-recovery guarantee. Legal compliance and security certification are not claimed.

## Controlled review demo status

The current owner-review replay has a fixed clock, versioned fixture, stable source event identifiers, isolated local database and three guided cases. It does not yet cover the full ten-scenario company-review package: pre-seeded dismissal, camera/recording fault, assignment/acknowledgement, SLA escalation, a client-safe service report and historical pattern are still outstanding as guided cases. Response, SLA and export functionality exists in the console but has not been turned into those complete walkthroughs. Do not present local SQLite replay validation as a production deployment or live VMS validation.
# Parking visit pilot

The parking-session prototype and its limits are documented in [docs/parking-visit-prototype.md](docs/parking-visit-prototype.md). It accepts registered ANPR, camera-detector and credential-link signals; gives the approved driver register priority over the temporary exit-track baseline; shows medium-priority yellow reviews for a high-quality appearance difference; and queues high-priority tampering or prolonged-loitering alerts to configured security and floor-guard contacts. It does not currently perform face recognition, plate OCR, or action detection itself.
