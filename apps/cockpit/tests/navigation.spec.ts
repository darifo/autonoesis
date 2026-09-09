import { expect, test } from "@playwright/test";

test("运营控制台连接真实 API 且未连接时显示错误而非样例", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("prototype-banner")).toContainText("Prototype / Demo");
  await expect(page.getByRole("heading", { name: "智能运行总览" })).toBeVisible();
  await page.getByRole("link", { name: "目标中心" }).click();
  await expect(page.getByRole("heading", { name: "目标中心" })).toBeVisible();
  // Without a configured API identity the live pages must surface an explicit
  // error state — never silently falling back to sample rows.
  await expect(page.getByText(/未配置租户身份|API 不可用/).first()).toBeVisible();
  await page.goto("/operations");
  await expect(page.getByRole("heading", { name: "运营操作中心" })).toBeVisible();
  await page.goto("/audit");
  await expect(page.getByRole("heading", { name: "审计与证据" })).toBeVisible();
  await expect(page.getByText(/未配置租户身份|API 不可用/).first()).toBeVisible();
});
