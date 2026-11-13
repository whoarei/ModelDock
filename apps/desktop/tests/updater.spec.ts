import { test, expect } from "@playwright/test";

test("startup checks notify without installing and release notes stay plain text", async ({
  page,
}) => {
  await page.goto("/tests/fixtures/updater.html");
  await page.getByRole("button", { name: "发现新版本 0.3.0" }).click();
  await expect(page.getByText("可更新到 0.3.0")).toBeVisible();
  await expect(page.locator(".update-notes")).toContainText(
    "<b>更新说明按文本显示</b>",
  );
  await expect(page.locator(".update-notes b")).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).updates.installs)).toBe(0);
});

test("offline update checks can retry and report current version", async ({
  page,
}) => {
  await page.goto("/tests/fixtures/updater.html?scenario=offline");
  await page.getByRole("button", { name: "应用更新", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("网络连接失败");
  await page.evaluate(() => {
    (window as any).updates.checkError = false;
  });
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(page.getByText("当前已是最新版本")).toBeVisible();
});

test("download progress is visible and signature failure never installs", async ({
  page,
}) => {
  await page.goto("/tests/fixtures/updater.html");
  await page.getByRole("button", { name: "发现新版本 0.3.0" }).click();
  await page.evaluate(() => {
    (window as any).updates.downloadError = true;
  });
  await page.getByRole("button", { name: "下载并安装" }).click();
  await expect(page.getByRole("status")).toContainText("50%");
  await expect(page.getByRole("button", { name: "关闭更新" })).toBeDisabled();
  await page.evaluate(() => (window as any).updates.finishDownload());
  await expect(page.getByRole("alert")).toContainText("签名校验失败");
  expect(await page.evaluate(() => (window as any).updates.installs)).toBe(0);
  await page.evaluate(() => {
    (window as any).updates.downloadError = false;
  });
  await page.getByRole("button", { name: "下载并安装" }).click();
  await expect
    .poll(() => page.evaluate(() => (window as any).updates.downloads))
    .toBe(2);
  await page.evaluate(() => (window as any).updates.finishDownload());
  await expect
    .poll(() => page.evaluate(() => (window as any).updates.restarts))
    .toBe(1);
});

test("busy tasks block installation before and after download and retries reuse verified bytes", async ({
  page,
}) => {
  await page.goto("/tests/fixtures/updater.html");
  await page.getByRole("button", { name: "发现新版本 0.3.0" }).click();
  await page.evaluate(() => {
    (window as any).updates.blocked = true;
  });
  await page.getByRole("button", { name: "下载并安装" }).click();
  await expect(page.getByRole("alert")).toContainText("本机测试任务");
  expect(await page.evaluate(() => (window as any).updates.downloads)).toBe(0);
  await page.evaluate(() => {
    Object.assign((window as any).updates, {
      blocked: false,
      afterDownloadBlock: true,
    });
  });
  await page.getByRole("button", { name: "下载并安装" }).click();
  await expect(page.getByRole("status")).toContainText("50%");
  await page.evaluate(() => (window as any).updates.finishDownload());
  await expect(page.getByRole("alert")).toContainText("本机测试任务");
  expect(await page.evaluate(() => (window as any).updates.installs)).toBe(0);
  await page.evaluate(() => {
    (window as any).updates.blocked = false;
  });
  await page.getByRole("button", { name: "重试安装" }).click();
  await expect
    .poll(() => page.evaluate(() => (window as any).updates.installs))
    .toBe(1);
  expect(await page.evaluate(() => (window as any).updates.downloads)).toBe(1);
});
