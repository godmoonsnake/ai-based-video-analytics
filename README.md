# DARSON

DARSON is a security operations pilot for a restricted area. The intended first deployment uses one camera: Frigate reports a person in a configured zone during restricted hours, DARSON opens a task at the on-site guard desk, and the assigned guard records a response. A supervisor reviews the outcome.

**Current status:** The software and a simulated local review are implemented. Recorder compatibility, real phone delivery, site hardware capacity, PostgreSQL access policies, offline sign-in and detection accuracy have not been validated at a pilot site. No ML model has been trained in this repository.

## Pilot workflow

1. Frigate sends camera event updates through local MQTT; DARSON evaluates current zone presence and the site's time window.
2. A person track matching the rule creates one guard task with the camera, time, instruction and protected incident evidence. Stale or finished tracks do not start new tasks.
3. The desk displays the task immediately. An on-shift assigned guard can receive a Telegram or direct WhatsApp notice; failures, no guard on shift and overdue acknowledgement remain visible for escalation.
4. The guard acknowledges and records **Real incident**, **False alarm** or **Need help** with an observation note. A supervisor separately verifies completed outcomes before using them as labels for accuracy work.

Provider acceptance means the provider accepted a request. It does not establish phone delivery, viewing or human acknowledgement. Evidence has access controls, an audit trail, retention expiry and holds.

The guard desk is the default pilot UI and works at desk and phone widths. The existing investigation console remains available to supervisors. The six case-study and parking prototypes are experimental; pilot mode hides their routes and does not claim they are live visual detectors. Cross-camera ReID, a line-drawing editor and a native Android app are outside this pilot implementation.

## Run the simulated review on Windows

From the repository root, install Python 3.12 backend dependencies and Node 20+ frontend dependencies in working environments, then run:

```powershell
cd backend
python -m pip install -r requirements-dev.txt
cd ..\frontend
npm ci
cd ..
powershell -ExecutionPolicy Bypass -File .\scripts\start-pilot-review.ps1
```

Open <http://127.0.0.1:8081>. The script creates an isolated, **SIMULATED** task in `backend/var/pilot-review-v1.db`, starts its own local API, worker and web processes, and suppresses external messages. It does not connect a recorder. If ports 8011 or 8081 are occupied, stop the existing review processes before starting another copy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-pilot-review.ps1
```

Local databases, logs, development keys and generated review artifacts under `backend/var/` are ignored by Git. The older research demo remains separate from the pilot task flow.

## Develop and verify

```powershell
cd backend
python -m pytest -q
python -m ruff check app tests --select E9,F63,F7,F82
cd ..\frontend
npm test
npm run build
```

The [local validation record](docs/pilot/validation-2026-10-12.md) reports 127 backend tests, 25 frontend tests and a successful frontend build on 12 October 2026. GitHub Actions runs the same core checks on pushes and pull requests. The local record does not claim a successful Docker deployment or real-camera acceptance.

## Configure a real pilot

Read the [pilot runbook](docs/pilot/README.md) for recorder and Frigate setup, camera/zone IDs, shifts, contacts, provider configuration, production environment values, retention, failure drills, diagnostics and the staged acceptance procedure. The production Compose overlay is [docker-compose.production.yml](docker-compose.production.yml); it still requires site-specific configuration, secrets, TLS, a pinned tested Frigate image and validation against the actual DVR/NVR and network.

The operations lead must set measurable targets before testing. The [acceptance template](docs/pilot/acceptance.template.json) intentionally contains no invented targets. Use the [trial template](docs/pilot/trials.template.csv), [monitoring template](docs/pilot/monitoring.template.csv) and `scripts/pilot_acceptance.py` to evaluate staged detection, alert latency and false alerts. Collect approved misses and false alerts, verify labels, establish a pretrained baseline, and fine-tune only when measured results justify it.

DARSON supports human security decisions. A detection or correlation signal is not proof of identity, intent or wrongdoing.
