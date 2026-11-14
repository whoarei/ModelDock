import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../../..");
const fixtures = path.join(root, "test-results/timm-browser-fixtures");
const modelName = "mobilenetv3_small_050.lamb_in1k";

async function openImport(page: Page) {
  await page.goto("/");
  await expect(page.locator(".connecting")).toHaveCount(0);
  await page.getByRole("button", { name: "插件管理", exact: true }).click();
  const card = page
    .locator(".plugin-card")
    .filter({ hasText: "timm 图像分类" });
  await expect(card).toContainText("209 个配置");
  if (
    await card
      .getByRole("button", { name: "准备运行环境", exact: true })
      .count()
  )
    await card
      .getByRole("button", { name: "准备运行环境", exact: true })
      .click();
  await expect(card.getByText("已就绪", { exact: true })).toBeVisible({
    timeout: 900000,
  });
  await page.getByRole("button", { name: "模型管理", exact: true }).click();
  await page
    .getByRole("button", { name: "导入模型", exact: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "导入模型" });
  await dialog.getByLabel("模型插件").selectOption("timm");
  await dialog.getByLabel("搜索模型").fill("mobilenetv3_small_050");
  await dialog.getByLabel("模型家族").selectOption("mobilenetv3");
  await dialog.getByLabel("支持模型").selectOption({ label: modelName });
  return dialog;
}

test("timm official weights download, ImageNet labels and actual inference", async ({
  page,
}, testInfo) => {
  test.setTimeout(900000);
  const dialog = await openImport(page);
  await dialog.getByLabel("实例名称").fill("timm 官方预训练 " + Date.now());
  await dialog.getByLabel("权重来源").selectOption("pretrained");
  await expect(dialog.getByLabel("模型类别数")).toHaveValue("1000");
  await expect(dialog.getByLabel("模型类别数")).toBeDisabled();
  await expect(dialog.getByLabel("权重下载 URL")).toHaveCount(0);
  await dialog.getByRole("button", { name: "下载权重", exact: true }).click();
  await expect(dialog.getByText(/已下载：/)).toBeVisible({ timeout: 180000 });
  await expect(dialog.getByLabel("类别文件", { exact: true })).not.toHaveValue(
    "",
  );
  await page.screenshot({
    path: testInfo.outputPath("timm-pretrained-import.png"),
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "验证并导入" }).click();
  await expect(dialog).toBeHidden({ timeout: 120000 });
  await page
    .locator(".model-card")
    .filter({ hasText: "timm 官方预训练" })
    .last()
    .getByRole("button", { name: "开始测试" })
    .click();
  const chooser = page.waitForEvent("filechooser");
  await page.locator(".upload-zone").click();
  const state = await (
    await page.request.post("/api", { data: { command: "state", args: {} } })
  ).json();
  const python = state.data.installations.find(
    (i: { id: string }) => i.id === "timm",
  ).python;
  execFileSync("uv", [
    "run",
    "--project",
    root,
    "python",
    path.join(root, "scripts/create_fixtures.py"),
    fixtures,
  ]);
  await (await chooser).setFiles(path.join(fixtures, "red.png"));
  await page.getByRole("button", { name: "开始测试", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible({
    timeout: 120000,
  });
  await expect(page.locator(".prediction-items .prediction-item")).toHaveCount(
    5,
  );
  await expect(
    page.getByText("PyTorch", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.locator(".model-mini")).toContainText(modelName);
  await expect(page.locator(".model-mini")).toContainText("PyTorch");
  await expect(page.locator(".model-mini")).not.toContainText("ONNX");
  execFileSync(python, [
    path.join(root, "scripts/create_timm_fixtures.py"),
    fixtures,
  ]);
  await page.screenshot({
    path: testInfo.outputPath("timm-pretrained-result.png"),
    fullPage: true,
  });
});

test("timm imports a custom tensor checkpoint with its class count", async ({
  page,
}) => {
  test.setTimeout(900000);
  const dialog = await openImport(page);
  const name = "timm 自定义分类 " + Date.now();
  await dialog.getByLabel("实例名称").fill(name);
  const state = await (
    await page.request.post("/api", { data: { command: "state", args: {} } })
  ).json();
  const python = state.data.installations.find(
    (i: { id: string }) => i.id === "timm",
  ).python;
  execFileSync(python, [
    path.join(root, "scripts/create_timm_fixtures.py"),
    fixtures,
  ]);
  for (const [button, file] of [
    ["选择权重文件", "timm-classifier.safetensors"],
    ["选择类别文件", "timm-labels.txt"],
  ]) {
    const chooser = page.waitForEvent("filechooser");
    await dialog.getByRole("button", { name: button }).click();
    await (await chooser).setFiles(path.join(fixtures, file));
  }
  await dialog.getByLabel("模型类别数").fill("3");
  await dialog.getByLabel("Top-K 类别数").fill("2");
  await dialog.getByRole("button", { name: "验证并导入" }).click();
  await expect(dialog).toBeHidden({ timeout: 120000 });
  await page
    .locator(".model-card")
    .filter({ hasText: name })
    .getByRole("button", { name: "开始测试" })
    .click();
  const chooser = page.waitForEvent("filechooser");
  await page.locator(".upload-zone").click();
  execFileSync("uv", [
    "run",
    "--project",
    root,
    "python",
    path.join(root, "scripts/create_fixtures.py"),
    fixtures,
  ]);
  await (await chooser).setFiles(path.join(fixtures, "red.png"));
  await page.getByRole("button", { name: "开始测试", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible({
    timeout: 120000,
  });
  await expect(
    page.locator(".prediction-items").getByText("green", { exact: true }),
  ).toBeVisible();
});
