// Run against a production build: npm run build && npm start
// Requires Playwright: npm install --no-save --package-lock=false playwright
import { chromium } from "playwright";
import assert from "node:assert/strict";
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const levels = { DIESEL: 1000, PETROL: 1200, OCTANE: 500 };
  const snapshot = {
    requested_at: new Date().toISOString(),
    as_of_tick: 10,
    consistent: true,
    complete: true,
    stale: false,
    resource_status: {},
    instance: {
      tick: 10,
      tick_minutes: 15,
      status: "RUNNING",
      sim_time: new Date().toISOString(),
    },
    regions: [],
    stations: [
      {
        id: "station-a",
        name: "Station A",
        demand_profile: "urban",
        region_id: "dhaka",
        status: "OPEN",
        inventory: levels,
        capacity: levels,
      },
    ],
    depots: [],
    routes: [],
    supply_arrivals: [],
    events: [],
    allocations: [],
    demand_history: [],
    metrics: { service_level: 1, unmet_demand_liters: 0 },
  };
  let plan = {
    plan_id: "plan-test",
    status: "draft",
    as_of_tick: 10,
    approved_by: null,
    warnings: [],
    rejection_reason: "none",
    recommendations: [
      {
        action: {
          action_id: "a1",
          source_depot_id: "depot-a",
          destination_station_id: "station-a",
          route_id: "route-a",
          fuel_type: "DIESEL",
          quantity_liters: 100,
          expected_arrival_tick: 12,
        },
        reasons: [
          { code: "PROJECTED_SHORTAGE", detail: "Prevent projected shortage" },
        ],
        constraints_checked: ["route_available"],
        severity: "high",
      },
    ],
    no_action_reasons: [],
    uncovered_needs: [],
    outcomes: [],
    impact: null,
  };
  let state = "active",
    enabled = false;
  const posts = [];
  await page.route("**/api/backend/**", async (route) => {
    const req = route.request(),
      p = new URL(req.url()).pathname;
    let data;
    if (p.includes("dashboard/snapshot")) data = snapshot;
    else if (p.endsWith("/status"))
      data = {
        engine: "healthy",
        last_run_tick: 10,
        snapshot_age_seconds: 1,
        execution_enabled: enabled,
        fallback_active: false,
        training: { trained: true, samples: 100, message: "Ready" },
      };
    else if (p.endsWith("/prediction"))
      data = {
        as_of_tick: 10,
        horizon_ticks: 4,
        generated_at_epoch: Date.now() / 1000,
        notes: [],
        risk_by_station: { "station-a": "high" },
        forecasts: [
          {
            station_id: "station-a",
            fuel_type: "DIESEL",
            point: [100],
            p10: [80],
            p90: [120],
            method: "trained_ensemble",
            confidence: "high",
            reasons: [],
          },
        ],
        projections: [],
      };
    else if (p.endsWith("/alerts"))
      data = [
        {
          state,
          acknowledged_by: state === "active" ? null : "tester",
          finding: {
            finding_id: "f1",
            title: "Shortage risk",
            detail: "Review supplies",
            severity: "high",
            confidence: "high",
            category: "PREDICTED",
          },
        },
      ];
    else if (req.method() === "POST") {
      posts.push({ p, body: req.postDataJSON() });
      if (p.endsWith("/approve"))
        plan = { ...plan, status: "approved", approved_by: "tester" };
      if (p.endsWith("/execute"))
        plan = {
          ...plan,
          status: "applied",
          outcomes: [
            {
              action_id: "a1",
              status: "submitted",
              simulator_allocation_id: 42,
              detail: null,
            },
          ],
        };
      if (p.endsWith("/reject")) plan = { ...plan, status: "rejected" };
      if (p.endsWith("/acknowledge")) state = "acknowledged";
      data = p.includes("/plans/") ? plan : {};
    } else data = plan;
    await route.fulfill({ json: data });
  });
  for (const [path, title] of [
    ["/", "Overview"],
    ["/stations", "Stations"],
    ["/depots", "Depots"],
    ["/activity", "Activity"],
    ["/deliveries", "Deliveries"],
    ["/intelligence", "Predictions & actions"],
  ]) {
    await page.goto("http://localhost:3000" + path);
    await page.getByRole("heading", { name: title, exact: true }).waitFor();
  }
  await page
    .getByText("This delivery is intended to cover forecast demand.")
    .waitFor();
  assert(
    await page
      .getByRole("button", { name: "Approve plan", exact: true })
      .isDisabled(),
  );
  await page.getByLabel("Operator ID").fill("tester");
  await page.getByRole("button", { name: "Approve plan", exact: true }).click();
  assert.equal(posts.length, 0);
  await page
    .getByRole("button", { name: "Confirm approve", exact: true })
    .click();
  await page
    .getByText("Showing your reviewed plan.", { exact: false })
    .waitFor();
  assert(
    await page
      .getByRole("button", { name: "Execute approved plan", exact: true })
      .isDisabled(),
  );
  enabled = true;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.waitForFunction(() =>
    [...document.querySelectorAll("button")].some(
      (b) => b.textContent === "Execute approved plan" && !b.disabled,
    ),
  );
  await page
    .getByRole("button", { name: "Execute approved plan", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Confirm execute", exact: true })
    .click();
  await page.getByText("Shipment outcomes", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Acknowledge", exact: true }).click();
  await page.getByText("Acknowledged by tester").waitFor();
  assert.equal(posts.filter((x) => x.p.endsWith("/execute")).length, 1);
  assert.equal(posts[0].body.operator, "tester");
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("link", { name: "Stations", exact: true })
    .click();
  await page
    .getByRole("button", { name: "View Station A station details" })
    .click();
  await page
    .getByRole("dialog")
    .waitFor({ timeout: 5000 })
    .catch(async (e) => {
      console.log(errors);
      console.log((await page.locator("body").innerText()).slice(-3000));
      throw e;
    });
  assert.deepEqual(errors, []);
  console.log(
    "PASS: six routes, predictions, operator required, explicit approval/execution confirmation, disabled execution, outcomes, acknowledgement, mobile navigation, station details; no browser exceptions.",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
