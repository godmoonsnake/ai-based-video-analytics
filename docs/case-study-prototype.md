**Experimental — outside the restricted-area pilot. Observation APIs are not live visual detectors.**

# Case study prototype

[IMPLEMENTED] This prototype implements the decision and incident path for five detection cases and a shared alert path. It accepts observations from a camera model, access system, asset system or operator through `POST /api/v1/case-studies/observations`. The current repository does **not** contain trained models for paper/title recognition, object identity, cigarette/smoke, alcohol, or number plate OCR. An incoming observation is a detector claim for review, not proof that the claimed activity occurred.

## Open the synthetic demo

Start the local stack as described in `README.md`, open the dashboard and select **Load six case study examples**. The development-only endpoint creates six suspected cases: restricted reading, protected file replacement, smoking, drinking, restricted entry and an unknown car plate. It also records an authorized bike plate observation without creating an incident. Each suspected case appears in the normal incident feed. The notification outbox records a local suppressed delivery when no external channel is configured. The demo uses no customer footage or real person identity.

The same synthetic setup is available with `POST /api/v1/case-studies/demo`. It is disabled in production and repeat calls return the same source event IDs. Synthetic observations always queue local suppressed alerts, even when external destinations are configured.

## Policy and observation API

Supervisors and configuration administrators can create policies with `POST /api/v1/case-studies/policies`. Operators and supervisors can submit observations. The API uses the authenticated tenant and site; client-supplied scope is ignored. `source_event_id` is the idempotency key within a site. Reusing it with different observation data returns 409. Every accepted observation creates a canonical event. Review decisions also create a shared incident, graph/timeline entry and audit record. The decision stores a snapshot and digest version of the policies applied at that time.

External sources must first be registered with `POST /api/v1/case-studies/sources` using `source_type`, `instance`, `actor` and `enabled`. The authenticated account submitting an observation must match the registered actor for that source and site. The development-only synthetic replay bypasses this check. Registration binds a claimed source to an account, but deployment still needs an OIDC service account and the external system's own event authentication and replay contract.

Policy kinds:

- `material`: register a restricted book, paper or document ID.
- `material_access`: grant a principal access to a registered item.
- `asset`: register a protected object or document bundle.
- `asset_transfer`: grant a principal a movement window for the asset.
- `prohibited_activity`: specify `smoking` or `drinking` as the subject and the prohibited zone.
- `restricted_zone`: register a zone as restricted.
- `area_access`: grant a principal access to the zone.
- `vehicle`: authorize a normalized plate for an optional zone and time window.

Example restricted zone and access grant:

```json
{"id":"zone-server","kind":"restricted_zone","subject":"server_room","zone":"server_room"}
```

```json
{"id":"grant-worker-17","kind":"area_access","subject":"server_room","zone":"server_room","principal":"worker-17","valid_from":1791334800,"valid_until":1791338400}
```

Example observation:

```json
{"source_event_id":"door-camera-17-000123","kind":"restricted_entry","camera_id":"door_camera_17","zone":"server_room","observed_at":1791335100,"principal_ref":"worker-17","confidence":0.91}
```

Supported observation `kind` values are `restricted_reading`, `material_change`, `smoking`, `drinking`, `restricted_entry`, and `vehicle_plate`. Reading and asset change require `item_id`. Material change also requires `action` of `removed` or `replaced`. Vehicle plate requires `plate` and `vehicle_type` (`car` or `bike`); OCR reads below 0.85 confidence always require review. An active allowlist match means the *vehicle* has a permit; it does not verify the driver.

For reading, asset movement and restricted entry, a missing `principal_ref` creates a suspected case when the subject or zone is registered. A camera track ID must not be substituted for an authenticated person ID. A matching grant can permit an observation only when `source_type` is `document_access`, `asset_custody` or `access_control`, respectively, and the source is registered to the authenticated account. A live connector must authenticate its upstream event independently before relying on it operationally. Policy matches are explicit and limited to the configured zone and validity window.

The response reports `decision` as `allowed`, `review`, or `unverified`, plus a reason and optional incident ID. `review` creates an incident with a timeline event in the existing console. `unverified` means the site register does not cover the observation, so the API does not claim a violation. The incident detail and PDF/ZIP export include the source, policy version, decision and reason without exposing plate text or document contents.

## Evidence intake

For a configured Frigate source, send `source_type: "camera_detector"`, the configured `source_instance`, `media_source: "frigate"`, and `has_snapshot` and/or `has_clip`. The case study observation creates capture requests in the existing durable worker. The worker fetches only from the configured Frigate API endpoint, with redirect and size controls, then stores media in the encrypted evidence vault. Event-supplied URLs are rejected.

An authenticated operator or supervisor can upload detector media directly with `PUT /api/v1/case-studies/observations/{observation_id}/evidence/snapshot` using `Content-Type: image/jpeg` or `image/png`, or `/clip` using `video/mp4`. The request body is raw media. The endpoint enforces the configured size and MIME limits, stores SHA-256 and provenance, links the object to the shared incident, and returns the existing object for an identical repeat upload. Different content for the same observation and kind returns 409. Review the media through the normal evidence endpoint; it is never served from the detector URL.

## Messaging setup

Alerts use the durable job worker. Configure one or both destinations through protected environment variables:

```text
DARSON_TELEGRAM_BOT_TOKEN
DARSON_TELEGRAM_CHAT_ID
DARSON_WHATSAPP_ACCESS_TOKEN
DARSON_WHATSAPP_PHONE_NUMBER_ID
DARSON_WHATSAPP_RECIPIENT
DARSON_WHATSAPP_TEMPLATE_NAME
DARSON_WHATSAPP_TEMPLATE_LANGUAGE=en_US
DARSON_WHATSAPP_API_VERSION=v21.0
```

The WhatsApp template must have three body parameters in this order: incident ID, case category, zone. Enroll recipients and approve the template in the business account before turning on the channel. Telegram recipients must start the bot or place it in an authorized group. External sends run only when `DARSON_ENVIRONMENT=production`; synthetic cases always use local suppressed delivery. The worker records `accepted`, `retrying`, or local `suppressed` state. `GET /api/v1/case-studies/alerts` shows provider status and the separate response acknowledgement timestamp to supervisors. Provider acceptance is not human acknowledgement, and delivery failure leaves the incident in the operator console.

Messages contain category, zone and case ID only. Document contents, images and plate text stay in the authenticated application. Do not put messaging credentials in source code or a browser build.

## Live integration still required

- Connect actual camera detectors for visible paper handling, object change, smoking and plate capture/OCR. Validate each against footage from the intended camera positions.
- Join door access, document access, asset custody and vehicle permits from the site's authoritative systems. The observation API alone cannot verify identity or authorization.
- Provide actual camera footage and detector outputs to evaluate the Frigate capture path. Synthetic case study observations currently have no media; the existing review replay contains separate synthetic media.
- Define site alert recipients by shift and add acknowledgement/escalation routing. The first prototype uses configured fixed destinations.
- Evaluate false alerts and missed events before operational use, especially under occlusion, glare and low light.
