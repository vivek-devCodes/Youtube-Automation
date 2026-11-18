// Full browser E2E against a running stack (backend + frontend) with mock/sandbox providers:
//   E2E_BASE_URL=http://localhost:3000 npx playwright test
// Requires a FRESH database (the test creates the first admin account). Covers onboarding → sandbox channel → topic → script review → render → QA → approval → (sandbox) upload.
import { expect, test } from "@playwright/test";

test("first-time user produces and approves a video", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(`e2e-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("e2e-password-123");
  await page.getByRole("button", { name: /Create account|Sign in/ }).click();
  await expect(page).toHaveURL(/onboarding/);

  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByText("No, help me create one").click();
  await page.getByRole("button", { name: /sandbox practice channel/ }).click();
  await expect(page.getByText("My Practice Channel")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click(); // -> channel setup
  await page.getByRole("button", { name: "Continue" }).click(); // -> niche
  await page.getByRole("button", { name: "Science and technology" }).click();
  for (let i = 0; i < 6; i++) await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect(page).toHaveURL(/dashboard/);

  await page.goto("/trends");
  await page.getByRole("button", { name: "Own topic" }).click();
  await page.getByRole("textbox", { name: "Topic", exact: true }).fill("Why the Moon drifts away from Earth");
  await page.getByRole("button", { name: "Start production" }).click();
  await expect(page).toHaveURL(/studio\?run=/);

  await page.getByRole("button", { name: "Approve script & produce" }).click({ timeout: 120_000 });
  await page.getByRole("button", { name: "Approve & publish…" }).click({ timeout: 240_000 });
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText(/Sandbox upload id/)).toBeVisible({ timeout: 120_000 });
});
