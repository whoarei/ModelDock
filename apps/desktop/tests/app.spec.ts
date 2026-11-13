import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "../../..");
const fixtures = path.join(root, "test-results/browser-fixtures");

test("real ONNX workflow: environments, import, predictions, charts, filtering and exports", async ({
  page,
}, testInfo) => {
  const suffix = Date.now().toString(36);
  const colorName = "颜色分类 · 集成测试 " + suffix;
  const detectionName = "检测协议 · 集成测试 " + suffix;
  execFileSync("uv", [
    "run",
    "--project",
    root,
    "python",
    path.join(root, "scripts/create_fixtures.py"),
    fixtures,
  ]);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "模型测试工作台" }),
  ).toBeVisible();
  await expect(page.locator(".connecting")).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("workbench-initial.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "插件管理", exact: true }).click();
  for (const name of ["EfficientNet 分类", "YOLO 目标检测"]) {
    const card = page.locator(".plugin-card").filter({ hasText: name });
    if (
      await card
        .getByRole("button", { name: "准备运行环境", exact: true })
        .count()
    )
      await card
        .getByRole("button", { name: "准备运行环境", exact: true })
        .click();
    await expect(card.getByText("已就绪", { exact: true })).toBeVisible({
      timeout: 240000,
    });
  }
  async function addModel(
    name: string,
    plugin: string,
    weight: string,
    labels: string,
  ) {
    await page.getByRole("button", { name: "模型管理", exact: true }).click();
    await page
      .getByRole("button", { name: "导入模型", exact: true })
      .first()
      .click();
    const dialog = page.getByRole("dialog", { name: "导入模型" });
    await dialog.getByLabel("模型插件").selectOption(plugin);
    await dialog.getByLabel("实例名称").fill(name);
    for (const [button, file] of [
      ["选择权重文件", weight],
      ["选择类别文件", labels],
    ]) {
      const chooser = page.waitForEvent("filechooser");
      await dialog.getByRole("button", { name: button, exact: true }).click();
      await (await chooser).setFiles(path.join(fixtures, file));
    }
    if (plugin === "efficientnet")
      await dialog.getByLabel("Top-K 类别数").fill("2");
    await dialog
      .getByRole("button", { name: "验证并导入", exact: true })
      .click();
    await expect(dialog).toBeHidden({ timeout: 120000 });
    const card = page.locator(".model-card").filter({ hasText: name });
    await expect(card.getByText("已就绪", { exact: true })).toBeVisible();
    await card.getByRole("button", { name: "开始测试" }).click();
  }
  await addModel(
    colorName,
    "efficientnet",
    "color-classifier.onnx",
    "classification-labels.txt",
  );
  await page.getByRole("button", { name: "批量", exact: true }).click();
  let chooser = page.waitForEvent("filechooser");
  await page.locator(".upload-zone").click();
  await (
    await chooser
  ).setFiles(
    ["red.png", "blue.png", "broken.jpg"].map((n) => path.join(fixtures, n)),
  );
  await page.getByRole("button", { name: "开始测试", exact: true }).click();
  await expect(page.getByText("部分失败", { exact: true })).toBeVisible();
  await expect(page.locator(".samples-scroll tbody tr")).toHaveCount(3);
  await page
    .locator(".samples-scroll tbody tr")
    .filter({ hasText: "blue.png" })
    .click();
  await expect(
    page.locator(".prediction-items").getByText("blue", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".image-stage img")).toHaveJSProperty(
    "complete",
    true,
  );
  await page.screenshot({
    path: testInfo.outputPath("classification-results.png"),
    fullPage: true,
  });
  const csv = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV", exact: true }).click();
  expect((await csv).suggestedFilename()).toMatch(/\.csv$/);
  await page.getByRole("button", { name: "性能分析", exact: true }).click();
  await expect(page.getByText("耗时分布", { exact: true })).toBeVisible();
  await expect(page.locator(".two-charts .chart")).toHaveCount(2);
  await page.screenshot({
    path: testInfo.outputPath("performance.png"),
    fullPage: true,
  });
  await addModel(
    detectionName,
    "yolo",
    "detection-fixture.onnx",
    "detection-labels.txt",
  );
  await page.getByRole("button", { name: "单图", exact: true }).click();
  chooser = page.waitForEvent("filechooser");
  await page.locator(".upload-zone").click();
  await (await chooser).setFiles(path.join(fixtures, "red.png"));
  await page.getByRole("button", { name: "开始测试", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  await expect(page.locator('svg[aria-label="检测框"] > g')).toHaveCount(2);
  await page.getByRole("button", { name: "放大", exact: true }).click();
  await expect(page.locator(".viewer-tools")).toContainText("125%");
  await page.getByRole("button", { name: "适应窗口", exact: true }).click();
  await page.getByLabel("类别筛选").selectOption("1");
  await expect(page.locator('svg[aria-label="检测框"] > g')).toHaveCount(1);
  await page.getByLabel("类别筛选").selectOption("all");
  await page.screenshot({
    path: testInfo.outputPath("detection-results.png"),
    fullPage: true,
  });
  const image = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出结果图片", exact: true }).click();
  expect((await image).suggestedFilename()).toMatch(/\.png$/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390);
  await page.screenshot({
    path: testInfo.outputPath("mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "测试记录", exact: true }).click();
  for (const name of [colorName, detectionName]) {
    const row = page
      .locator(".history-table tbody tr")
      .filter({ hasText: name });
    await expect(row).toHaveCount(1);
    await row.locator("input[type=checkbox]").check();
  }
  await page.getByRole("button", { name: /对比所选/ }).click();
  await expect(
    page.getByRole("dialog", { name: "测试结果对比" }),
  ).toBeVisible();
  await expect(
    page.getByText("检测到测试条件不同，请结合配置差异解读结果。"),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
