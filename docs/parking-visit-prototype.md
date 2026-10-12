**Experimental — outside the restricted-area pilot. Observation APIs are not live visual detectors.**

# Parking visit monitor — pilot scope

## What is practical

A fixed entrance camera can read a plate and open a short parking visit. A camera covering the bay can associate one or more exit tracks with that visit. A detector can later report that a person near that car appears different from those exit tracks. DARSON shows this as a **yellow, medium-priority review**. A reported forced-entry, damage, or object-removal action raises a high-priority incident; a door/trunk handle action does so when the person was already flagged. The incidents use the existing evidence, operator review, response and alert workflows.

The first person leaving the car is **not** assumed to be its owner. The person might be a passenger, valet, employee, or authorized driver. A plate is a vehicle identifier, not a person credential. An approved vehicle/driver registry takes priority. A registered `access_control` source can link a camera track to a credential principal only when an active vehicle policy grants that principal access. The first exit track remains a provisional appearance baseline. When the register contains named drivers but no credential link is present, a similar-looking track remains **unverified**. The pilot stores detector-local person references and credential links for the visit. It does not store face templates or body embeddings. `appearance_match` and `comparison_quality` are upstream detector claims, not verified identity probabilities. Yellow means **review an unfamiliar appearance near this vehicle**, not unauthorized person or wrongdoing.

## Implemented intake and decision path

1. A manager registers `vehicle_anpr`, `camera_detector`, and, when available, `access_control` sources with `/api/v1/case-studies/sources`; each is bound to the authenticated source account. Approved drivers are registered as `vehicle` policies with the normalized plate in `subject` and the credential principal in `principal`.
2. `POST /api/v1/parking/sessions` opens a 12-hour visit from a plate read at confidence 0.85 or above. A weaker read is rejected; an audited manual correction workflow remains to be built.
3. `POST /api/v1/parking/sessions/{id}/signals` accepts `exit`, `approach`, `interaction`, or `departure` signals from the registered camera detector. The pilot requires the same camera for all signals in a session.
4. `exit` records an opaque person track reference. Multiple exit tracks are allowed. `POST /api/v1/parking/sessions/{id}/authorizations` accepts a trusted credential-to-track link and checks the active vehicle driver policy. `approach` with a different appearance result and quality of at least 0.8 creates the yellow review incident unless that track has an active approved credential link. Inconclusive comparisons do not imply a mismatch.
5. `interaction` creates a high-priority incident for `door_tamper`, `trunk_tamper`, `forced_entry`, `damage`, or `object_removal`. `door_handle`, `trunk_handle`, and prolonged `loitering` create one only for a previously flagged person reference. Loitering requires a detector-supplied `duration_seconds` meeting `DARSON_PARKING_LOITERING_SECONDS` (default 120 seconds; minimum effective value 30). The incident summary asks a guard to verify the observation. Repeated interaction signals for that person reference in the same visit are recorded without sending duplicate dispatch alerts.
6. In production, high-priority parking alerts are queued for the configured security and floor-guard Telegram/WhatsApp destinations. Yellow incidents remain in the operator console. Provider acceptance is tracked separately from human acknowledgment.

The body of a signal includes `source_event_id`, `source_instance`, `camera_id`, `observed_at`, `kind`, and, for person signals, `person_ref`. Approaches also include `appearance_match` (`same`, `different`, or `unknown`) and `comparison_quality`. Interactions include an `action` from the configured list. Credential-link messages include `person_ref` and `principal_ref`; the upstream access-control integration must establish that the track and credential belong to the same person at this vehicle. Duplicate event IDs are idempotent when the content is identical; changed content is rejected. The session and observation writes share one transaction.

Configure pilot dispatch with `DARSON_PARKING_SECURITY_TELEGRAM_CHAT_ID`, `DARSON_PARKING_FLOOR_GUARD_TELEGRAM_CHAT_ID`, `DARSON_PARKING_SECURITY_WHATSAPP_RECIPIENT`, and `DARSON_PARKING_FLOOR_GUARD_WHATSAPP_RECIPIENT`. Existing bot/API credentials and WhatsApp template settings are also required. Destinations are static pilot contacts; the on-duty floor guard must be kept current by operations. An unconfigured destination results in a local queue entry, not a delivered message.

## Work required before a camera pilot

- Obtain a site-approved vehicle/driver register and a reliable credential or gate event if the requirement is to decide whether a person is authorized. A camera exit track alone cannot establish ownership or authorization. Validate the credential-to-camera-track link and rejection cases on site footage.
- Choose cameras and lighting from actual bay footage. Plate capture and person capture often need different angles or cameras. Validate vehicle-to-person association at adjacent bays, multi-occupant exits, occlusions, nighttime, helmets, masks, reflections, and plate swaps.
- Integrate a real plate OCR, vehicle/person tracker, appearance comparator, and action detector. None is supplied by this endpoint. Calibrate thresholds and false-alert rates on site footage; the 0.8 comparison-quality gate is only an intake setting, not a verified accuracy claim.
- Link detector evidence to the protected evidence vault, configure retention and scheduled deletion for parking sessions, and document notices, access controls, and biometric governance before any face/body template is considered.
- Configure escalation ownership, the on-duty guard contact, delivery failure monitoring, and human acknowledgment. Run a shadow period, then measure plate-read quality, missed events, incorrect associations, yellow alerts per vehicle visit, guard response time, and confirmed incidents.

## Current limits

No model currently generates the `appearance_match` or interaction action signals from live video. No face or body recognition, owner verification, cross-camera identity matching, dynamic shift-based recipient routing, or automatic session purge is implemented. The prototype demonstrates the policy and dispatch workflow once a trusted detector supplies the signals. It is not a live theft detector or an autonomous accusation system.
