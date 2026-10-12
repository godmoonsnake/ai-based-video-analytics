import { test, expect, request } from "@playwright/test";

// True browser -> reverse proxy -> frontend/backend -> PostgreSQL flow.
// The backend is NOT mocked. We seed the deterministic demo incident through the
// same proxy origin, then drive the console UI and verify persistence.
const ORIGIN = process.env.DARSON_ORIGIN ?? "http://localhost:8080";

let demoIncidentId: number;

test.beforeAll(async () => {
  // Seed the deterministic demo pipeline through the proxy (ingest mock scenario
  // -> correlate -> build incident, persisted in PostgreSQL). Capture the built
  // incident id so UI assertions target that exact incident regardless of how
  // many incidents already exist (stable, ordering-independent).
  const ctx = await request.newContext({ baseURL: ORIGIN });
  await ctx.post("/events/ingest/mock");
  await ctx.post("/tracks/correlate");
  const built = await ctx.post("/incidents/build");
  expect(built.ok()).toBeTruthy();
  const list = await (await ctx.get("/api/v1/incidents")).json();
  for (const inc of list) {
    const d = await (await ctx.get(`/api/v1/incidents/${inc.id}`)).json();
    if ((d.explanation?.correlations?.length ?? 0) > 0) {
      demoIncidentId = inc.id;
      break;
    }
  }
  expect(demoIncidentId).toBeTruthy();
  await ctx.dispose();
});

test("operator investigation workflow persists to PostgreSQL", async ({ page }) => {
  // 1-3. Open the seeded incident (with correlations) from the live feed.
  await page.goto("/");
  await expect(page.getByText("Operations")).toBeVisible();
  const row = page.getByTestId(`incident-row-${demoIncidentId}`);
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByTestId("incident-detail")).toBeVisible();

  // 4. Incident state is shown; lifecycle controls render only allowed actions.
  const lifecycle = page.getByTestId("lifecycle-controls");
  await expect(lifecycle).toBeVisible();

  // 5. Case file: explainable why-created reasons + correlation sub-scores.
  await expect(page.getByTestId("why-reason").first()).toBeVisible();
  await expect(page.getByTestId("correlation-card").first()).toBeVisible();

  // 6. Timeline tab: per-camera lanes with steps.
  await page.getByRole("tab", { name: /timeline/i }).click();
  await expect(page.getByTestId("timeline-step").first()).toBeVisible();

  // 7. Graph tab: the evidence graph renders as an SVG.
  await page.getByRole("tab", { name: /graph/i }).click();
  await expect(page.getByTestId("incident-graph-svg")).toBeVisible();

  // 8. Evidence tab: viewfinder cards (snapshot img or graceful unavailable note).
  await page.getByRole("tab", { name: /evidence/i }).click();
  const evidence = page.locator('[data-testid="evidence-card"], [data-testid="evidence-unavailable"]');
  await expect(evidence.first()).toBeVisible();

  // 9 & 10. Start triage, then confirm (only if the incident is fresh/open).
  await page.getByRole("tab", { name: /case file/i }).click();
  const triageBtn = page.getByTestId("action-start_triage");
  if (await triageBtn.count()) {
    await triageBtn.click();
    await expect(page.getByTestId("action-confirm")).toBeVisible();
    await page.getByTestId("action-confirm").click();
  }
  // State badge should read confirmed after the transitions.
  await expect(page.locator(".state-badge.state-confirmed").first()).toBeVisible();

  // 11. Verify transition history recorded (audit tab).
  await page.getByRole("tab", { name: /audit/i }).click();
  await expect(page.getByTestId("history-item").first()).toBeVisible();

  // 12. Reload the page.
  await page.reload();
  await page.getByTestId(`incident-row-${demoIncidentId}`).click();
  await expect(page.getByTestId("incident-detail")).toBeVisible();

  // 13. Verify persisted state remains confirmed after reload (from PostgreSQL).
  await expect(page.locator(".state-badge.state-confirmed").first()).toBeVisible();
});

test("invalid lifecycle transition is rejected by the backend", async ({ request: ctx }) => {
  // A confirmed incident cannot 'start_triage' again -> backend returns 409.
  const list = await ctx.get("/api/v1/incidents?status=confirmed");
  const confirmed = await list.json();
  test.skip(confirmed.length === 0, "no confirmed incident to test invalid transition");
  const id = confirmed[0].id;
  const res = await ctx.post(`/api/v1/incidents/${id}/state`, {
    data: { action: "start_triage" },
  });
  expect(res.status()).toBe(409);
});
