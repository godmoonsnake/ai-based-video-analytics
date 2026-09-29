import { test, expect, request } from "@playwright/test";

// True browser -> reverse proxy -> frontend/backend -> PostgreSQL flow.
// The backend is NOT mocked. We seed the deterministic demo incident through the
// same proxy origin, then drive the dashboard UI and verify persistence.
const ORIGIN = process.env.DARSON_ORIGIN ?? "http://localhost:8080";

test.beforeAll(async () => {
  // Seed the deterministic demo pipeline via the proxy (idempotent enough for a
  // demo: ingest mock scenario -> correlate -> build incident, persisted in PG).
  const ctx = await request.newContext({ baseURL: ORIGIN });
  await ctx.post("/events/ingest/mock");
  await ctx.post("/tracks/correlate");
  const built = await ctx.post("/incidents/build");
  expect(built.ok()).toBeTruthy();
  await ctx.dispose();
});

test("operator investigation workflow persists to PostgreSQL", async ({ page }) => {
  // 1. Open incident list.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Incident Investigation/i })).toBeVisible();

  // 2. Wait for the demo incident row to appear.
  const firstRow = page.locator('[data-testid^="incident-row-"]').first();
  await expect(firstRow).toBeVisible();

  // 3. Open incident detail.
  await firstRow.click();
  await expect(page.getByTestId("incident-detail")).toBeVisible();

  // 4. Verify incident state is shown (open initially, unless already advanced).
  const lifecycle = page.getByTestId("lifecycle-controls");
  await expect(lifecycle).toBeVisible();

  // 5. Verify timeline has steps.
  await expect(page.getByTestId("timeline-step").first()).toBeVisible();

  // 6. Verify graph renders (expand the Graph section, then the SVG).
  await page.getByRole("button", { name: /^.*Graph/ }).click();
  await expect(page.getByTestId("incident-graph-svg")).toBeVisible();

  // 7. Verify correlation explanation.
  await expect(page.getByTestId("correlation-card").first()).toBeVisible();

  // 8. Verify evidence section exists (expand it; snapshot img or graceful note).
  await page.getByRole("button", { name: /^.*Evidence/ }).click();
  const evidence = page.locator('[data-testid="evidence-card"], [data-testid="evidence-unavailable"]');
  await expect(evidence.first()).toBeVisible();

  // 9 & 10. Start triage, then confirm (only if the incident is fresh/open).
  const triageBtn = page.getByTestId("action-start_triage");
  if (await triageBtn.count()) {
    await triageBtn.click();
    await expect(page.getByTestId("action-confirm")).toBeVisible();
    await page.getByTestId("action-confirm").click();
  }
  // State badge should read confirmed after the transitions.
  await expect(page.locator(".state-badge.state-confirmed").first()).toBeVisible();

  // 11. Verify transition history recorded.
  await expect(page.getByTestId("history-item").first()).toBeVisible();

  // 12. Reload the page.
  await page.reload();
  await page.locator('[data-testid^="incident-row-"]').first().click();
  await expect(page.getByTestId("incident-detail")).toBeVisible();

  // 13. Verify persisted state remains confirmed after reload (from PostgreSQL).
  await expect(page.locator(".state-badge.state-confirmed").first()).toBeVisible();
});

test("invalid lifecycle transition is rejected by the backend", async () => {
  // A confirmed incident cannot 'start_triage' again -> backend returns 409.
  const ctx = await request.newContext({ baseURL: ORIGIN });
  const list = await ctx.get("/api/v1/incidents?status=confirmed");
  const confirmed = await list.json();
  test.skip(confirmed.length === 0, "no confirmed incident to test invalid transition");
  const id = confirmed[0].id;
  const res = await ctx.post(`/api/v1/incidents/${id}/state`, {
    data: { action: "start_triage" },
  });
  expect(res.status()).toBe(409);
  await ctx.dispose();
});
