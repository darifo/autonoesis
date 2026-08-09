import { expect, test } from "@playwright/test";

test("运营控制面可以访问运行、治理和进化页面", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "智能运行总览" })).toBeVisible();
  await page.getByRole("link", { name: "目标中心" }).click();
  await expect(page.getByRole("heading", { name: "目标中心" })).toBeVisible();
  await page.getByRole("link", { name: "进化与发布" }).click();
  await expect(page.getByRole("heading", { name: "进化与发布" })).toBeVisible();
  await page.getByRole("link", { name: "审计与证据" }).click();
  await expect(page.getByText("不可解释 Action")).toBeVisible();
});
