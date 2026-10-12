**Experimental — outside the restricted-area pilot. Observation APIs are not live visual detectors.**

# Six security case studies: owner review brief

**Status:** proposal, 7 October 2026. The first five cases follow the owner request. Case 6 treats Telegram/WhatsApp incident notification as the sixth shared case. This numbering can change when the owner confirms the missing case.

**Pilot premise:** one consenting site with mapped cameras, zones, access rules, an incident reviewer and an approved response procedure. A detection creates an evidence-backed *suspected event* for review. It does not by itself prove identity, intent, intoxication or a policy violation.

## What exists today

The current DARSON working tree has event ingestion, restricted-zone incident construction, a review and response workflow, protected evidence handling, and a durable local notification record. The case study prototype now adds policy-backed observation intake, a plate allowlist, review incidents and configurable Telegram/WhatsApp alert adapters. Its local delivery records a suppressed alert and sends nothing externally. Visual detectors and site identity/asset integrations remain proposed work. The working tree has extensive uncommitted changes; this brief does not certify a running deployment. See [case-study-prototype.md](case-study-prototype.md) for the implemented API and demo.

## Common event and response flow

`Camera / door / inventory / DLP signal → normalize with site and zone → apply a versioned rule → create one incident → preserve scoped evidence → route to the on-duty reviewer → acknowledge / verify / dismiss → log action and outcome`

Each case needs camera coverage and time synchronization, a named policy owner, a human review path, a safe response instruction, evidence retention, access controls, and measurements for missed events as well as false alerts. Critical alerts should remain in the operator queue even if a messaging provider fails.

## 1. Suspected reading of a restricted book, paper or screen

**Scenario.** A person is seen consulting a specifically restricted item in a controlled area, such as an exam paper or marked confidential binder.

**Detectable signal.** A camera can identify a person holding or reading a paper-like object. It generally cannot reliably read its title or determine whether the person is authorized from an ordinary overhead CCTV view. Use a controlled reading station with a close camera or a registered visible marker on the item when the exact item matters. For a digital document, use document access logs or DLP events rather than attempting to read a distant screen from video.

**Rule and evidence.** Raise a review event only when an item identifier or restricted workstation/document access event joins with a person in the relevant zone and time window. Store the source event, camera frame or short clip, item identifier if available, and the applicable rule version. Mask document contents in routine notifications.

**Pilot demonstration.** Stage authorized reading, restricted-item reading, an unmarked ordinary book, occlusion and two people near one desk. Measure event precision, missed restricted-item events, reviewer time and whether the item identity was actually visible or came from a trusted access log.

**Key dependency:** item registry and controlled capture or digital access integration. A generic “person reading” detector alone does not satisfy this case.

## 2. Removal or replacement of confidential materials

**Scenario.** A registered file, sealed box or confidential object is removed from a protected shelf, safe or desk, or a different item is put in its place.

**Detectable signal.** Fixed-camera before/after comparison can flag a changed location, but shadows, cleaning, occlusion and camera movement cause errors. Confirm the asset with a barcode/RFID scan, cabinet sensor, seal or inventory transaction when the item itself matters. A pixel match cannot certify that a replacement contains the same documents.

**Rule and evidence.** Treat an object change as a candidate event. Join it to asset ID, permitted movement window, cabinet/door activity and custody log. Preserve before/after images, a short clip, timestamps, asset record and any sensor/scan event. Alert the reviewer on an unexplained change; record a verified removal/replacement only after investigation.

**Pilot demonstration.** Stage legitimate checkout, unlogged removal, visually similar replacement, lighting change, obstruction and camera shift. Measure change-detection recall, false alerts per shelf-day, and the share of cases resolved with an asset record.

**Key dependency:** registered assets and a reliable custody workflow.

## 3. Smoking and alcohol-related activity in restricted areas

**Scenario.** Smoking or visible drinking occurs in a defined no-smoking/no-alcohol zone.

**Detectable signal.** Video may show a cigarette/cigar, smoke, a bottle/can and drinking motion. It cannot reliably establish the liquid is alcohol or that a person is intoxicated. Smoke sensors or site safety alarms can strengthen smoking evidence; the presence of a bottle is insufficient for an alcohol accusation.

**Rule and evidence.** Define separate policy labels: `suspected_smoking`, `suspected_drinking`, and `verified_policy_breach`. Apply them only in configured zones and hours. A guard or supervisor verifies the event before any disciplinary conclusion. For immediate fire risk, follow the site's existing alarm procedure.

**Pilot demonstration.** Stage cigarette/cigar use where permitted, smoking in a restricted area, steam/dust, an ordinary beverage, and drinking from an ambiguous container. Measure precision by label, false alerts per camera-hour and response time.

**Key dependency:** a site policy stating zones and permitted exceptions.

## 4. Unauthorized entry to a restricted or confidential area

**Scenario.** Someone enters a protected room, crosses a virtual line, tailgates through a door or remains in a restricted zone without a matching authorization event.

**Detectable signal.** Camera person tracking, door contact and access-control logs can establish presence and passage. A badge event proves a credential was used, not necessarily which visible person used it. Match by door, time and direction, and mark ambiguous matches for human review. Avoid claiming identity from appearance correlation alone.

**Rule and evidence.** An entry or dwell event without a valid access event in the agreed time window creates a high-priority suspected entry case. Include the zone map, clip, door and badge event references, and explicit ambiguity. A failed camera, clock mismatch or missing access feed should show `verification unavailable` rather than `unauthorized`.

**Pilot demonstration.** Stage valid entry, no-badge entry, tailgating, door held open, two-person entry, clock drift and access-system outage. Measure entry recall, false alerts per door-day, and time to guard acknowledgement.

**Key dependency:** access-control integration, synchronized clocks and a maintained authorization roster.

## 5. Car and motorcycle number plates with allowlist checks

**Scenario.** A car or motorcycle reaches a site gate; its plate is compared with an approved vehicle list and current access window.

**Detectable signal.** A gate camera captures the vehicle and plate; plate detection plus OCR returns candidate text and image quality. Normalize plate format without silently changing uncertain characters. Read front and rear views where site geometry permits. A plate match authorizes a *registered vehicle*, not its driver or passengers.

**Rule and evidence.** Check the candidate plate against site, schedule, vehicle type and permit status. Low-confidence or obstructed plates go to manual review. Use a second factor such as guard check or access credential for high-security gates. Preserve cropped plate, full vehicle frame, OCR alternatives, rule result and gate decision. The application should not auto-open a barrier during the first pilot.

**Pilot demonstration.** Include day/night, rain/glare, motorcycles, two-line plates, dirty/occluded plates, approved, expired and unknown plates. Measure exact-plate read rate on readable images, false allowlist matches, manual-review rate and gate delay.

**Key dependency:** site-specific camera placement and a current vehicle permit list.

## 6. Automated Telegram or WhatsApp incident notification

**Scenario.** A relevant incident reaches the correct on-duty person, who can acknowledge it; unanswered urgent cases escalate to the supervisor.

**Trigger.** Route confirmed high-risk signals or site-approved suspected events by tenant, site, zone, category, severity and shift. Send one concise alert containing case ID, location, time, reason, urgency and a link to the authenticated case. Do not put confidential document images, full plate lists or unrestricted video in a chat message.

**Delivery.** Build adapters on the existing durable notification record and worker. Store an idempotency key, destination reference, provider attempt, provider acceptance, failure/retry state and human acknowledgement separately. Give operators a queue view when delivery fails. Telegram's Bot API supports text messages to a known chat ID; private users generally need to start the bot first. WhatsApp should use the official Business Platform/Cloud API and its approved template flow for business-initiated alerts. Provider setup, recipient consent, templates and delivery rules must be checked during integration.

**Pilot demonstration.** Send test alerts for each case to enrolled staff; repeat the same incident; simulate provider timeout, wrong destination, off-duty recipient and no acknowledgement. Measure creation-to-provider acceptance, acknowledgement time, duplicate messages, delivery failure recovery and correct routing. Provider acceptance is not proof that the person read or acted on the alert.

**Key dependency:** approved business accounts, enrolled recipients, shift roster, escalation policy and a secure external case link.

## Recommended build order

1. **Restricted entry** on one door/zone: this best reuses the present incident pipeline and yields a clear guard response.
2. **Plate allowlist** at one controlled gate: add a human gate decision and a maintained permit list.
3. **Material removal** for a small registered asset set: combine camera change with inventory or cabinet events.
4. **Smoking** in a clearly posted zone: evaluate visual signal quality before adding alcohol-related labels.
5. **Restricted reading** only after the owner identifies exact items and a controlled capture/access source.
6. **Notifications** are a shared capability built with the first pilot case, then reused for the others.

## Owner decisions needed before a live pilot

- Name the sixth detection case if notification is intended to be shared infrastructure rather than case 6.
- Pick the first site, camera/door/gate, policy owner and on-duty responder.
- Identify exact restricted materials and how their identity or custody is recorded.
- Approve the access-control, inventory, DLP and vehicle lists available for integration.
- Choose Telegram, WhatsApp or both; provide business account ownership and enrolled recipients.
- Agree on alert thresholds, human verification, retention, and the emergency fallback procedure.

## Reference points

- Repository status: `README.md`, `docs/pilot-implementation-gaps.md`, `backend/app/operations/notifications.py` in this working tree.
- Telegram Bot API and bot onboarding: https://core.telegram.org/bots/api and https://core.telegram.org/bots/tutorial
- Meta's WhatsApp Cloud API examples/documentation: https://github.com/fbsamples/whatsapp-api-examples and https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api
