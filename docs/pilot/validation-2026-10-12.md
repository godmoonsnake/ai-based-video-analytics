# Local validation — 12 October 2026

- Backend: **127 tests passed**, Python 3.12.10, isolated SQLite databases. Includes legacy regressions, new pilot rules/routing/outcomes, evidence permissions, public-key verification, expiry failures and migration upgrade/downgrade/column parity.
- Frontend: **25 tests passed** across four files, including acknowledgement without evidence, required outcome notes, stale-action recovery and responder restrictions.
- Production frontend build: TypeScript and Vite completed successfully.
- Fatal lint: `ruff check app tests --select E9,F63,F7,F82` passed. Python compilation and tracked-file whitespace checks passed.
- Browser: verified desktop and 390-pixel phone layouts, acknowledged a simulated task, recorded a simulated false alarm and found it in recent outcomes. Acknowledgement now precedes the evidence preview; selected task precedes the queue on phones.
- Screenshot assets and review database are synthetic. The confidence value printed on the fixture image is not an accuracy measurement. No recorder was connected, no customer footage was collected, no real message was sent, and no ML model was trained.
- Tests used the installed Python plus existing `.venv-local` packages because that venv's interpreter path is stale. Local FastAPI test clients required execution outside the sandbox: its event-loop socket creation blocked. This was observed in a captured thread stack; OneDrive was not diagnosed as the cause.
- Docker CLI is unavailable in this environment. The Compose changes were inspected against official merge/reset documentation, but the production stack, PostgreSQL/RLS, LAN firewall/TLS, external delivery, hardware load and offline sign-in/restart have **not** passed site acceptance here.
- CI workflow is added, but no remote CI run or production deployment is claimed. Signed targets and site tests remain the operations lead's deployment gates.

See [pilot runbook](README.md), [signed target template](acceptance.template.json) and the diagnostic/acceptance commands there.
