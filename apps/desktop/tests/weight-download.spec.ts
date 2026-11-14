import { test, expect, type Page } from "@playwright/test";
import http from "node:http";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../../..");
const fixtures = path.join(root, "test-results/url-fixtures");
let server: http.Server, base: string, bytes: Buffer;
test.beforeAll(async () => {
  execFileSync("uv", [
    "run",
    "--project",
    root,
    "python",
    path.join(root, "scripts/create_fixtures.py"),
    fixtures,
  ]);
  bytes = fs.readFileSync(path.join(fixtures, "color-classifier.onnx"));
  server = http.createServer((request, response) => {
    if (request.url?.startsWith("/missing")) {
      response.writeHead(404);
      response.end();
      return;
    }
    if (request.url?.startsWith("/redirect")) {
      response.writeHead(302, { Location: "/model.onnx" });
      response.end();
      return;
    }
    response.setHeader("Content-Type", "application/octet-stream");
    if (request.url?.startsWith("/slow")) {
      response.setHeader("Content-Length", 4 * 1024 * 1024);
      const timer = setInterval(() => {
        response.write(Buffer.alloc(8192));
      }, 25);
      response.on("close", () => clearInterval(timer));
    } else {
      response.setHeader("Content-Length", bytes.length);
      response.end(bytes);
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
});
test.afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

async function openImport(page: Page) {
  await page.goto("/");
  await expect(page.locator(".connecting")).toHaveCount(0);
  await page.getByRole("button", { name: "插件管理", exact: true }).click();
  const card = page
    .locator(".plugin-card")
    .filter({ hasText: "EfficientNet 分类" });
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
  await page.getByRole("button", { name: "模型管理", exact: true }).click();
  await page
    .getByRole("button", { name: "导入模型", exact: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "导入模型" });
  await dialog.getByLabel("模型插件").selectOption("efficientnet");
  await dialog.getByLabel("权重来源").selectOption("url");
  return dialog;
}

test("download URL weights, verify SHA-256 and run actual inference", async ({
  page,
}, testInfo) => {
  const dialog = await openImport(page);
  const name = "URL 分类模型 " + Date.now();
  await dialog.getByLabel("实例名称").fill(name);
  await dialog.getByLabel("权重下载 URL").fill(base + "/redirect");
  await dialog.getByText("文件名与完整性校验（可选）", { exact: true }).click();
  await dialog.getByLabel("保存文件名").fill("网址分类.onnx");
  await dialog
    .getByLabel("SHA-256 校验值")
    .fill(createHash("sha256").update(bytes).digest("hex"));
  await expect(
    dialog.getByRole("button", { name: "验证并导入" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "下载权重", exact: true }).click();
  await expect(dialog.getByText(/已下载：网址分类.onnx/)).toBeVisible();
  await expect(dialog.getByText(/SHA-256 校验通过/)).toBeVisible();
  const chooser = page.waitForEvent("filechooser");
  await dialog.getByRole("button", { name: "选择类别文件" }).click();
  await (
    await chooser
  ).setFiles(path.join(fixtures, "classification-labels.txt"));
  await dialog.getByLabel("Top-K 类别数").fill("2");
  await page.screenshot({
    path: testInfo.outputPath("url-weight-import.png"),
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "验证并导入" }).click();
  await expect(dialog).toBeHidden({ timeout: 120000 });
  await page
    .locator(".model-card")
    .filter({ hasText: name })
    .getByRole("button", { name: "开始测试" })
    .click();
  const image = page.waitForEvent("filechooser");
  await page.locator(".upload-zone").click();
  await (await image).setFiles(path.join(fixtures, "red.png"));
  await page.getByRole("button", { name: "开始测试", exact: true }).click();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();
  await expect(
    page.locator(".prediction-items").getByText("red", { exact: true }),
  ).toBeVisible();
});

test("failed downloads can retry and editing URL clears the previously downloaded file", async ({
  page,
}) => {
  const dialog = await openImport(page);
  await dialog.getByLabel("权重下载 URL").fill(base + "/missing.onnx");
  await dialog.getByRole("button", { name: "下载权重", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("HTTP 404");
  await expect(
    dialog.getByRole("button", { name: "验证并导入" }),
  ).toBeDisabled();
  await dialog.getByLabel("权重下载 URL").fill(base + "/model.onnx");
  await dialog.getByText("文件名与完整性校验（可选）", { exact: true }).click();
  await dialog.getByLabel("SHA-256 校验值").fill("0".repeat(64));
  await dialog.getByRole("button", { name: "下载权重", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("校验失败");
  await expect(
    dialog.getByRole("button", { name: "验证并导入" }),
  ).toBeDisabled();
  await dialog
    .getByLabel("SHA-256 校验值")
    .fill(createHash("sha256").update(bytes).digest("hex"));
  await dialog.getByRole("button", { name: "下载权重", exact: true }).click();
  await expect(dialog.getByText(/已下载：model.onnx/)).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "验证并导入" }),
  ).toBeEnabled();
  await dialog.getByLabel("权重下载 URL").fill(base + "/different.onnx");
  await expect(
    dialog.getByRole("button", { name: "验证并导入" }),
  ).toBeDisabled();
});

test("progress, explicit cancellation and closing the modal cancel the download", async ({
  page,
  request,
}) => {
  const dialog = await openImport(page);
  await dialog.getByLabel("权重下载 URL").fill(base + "/slow.onnx");
  await dialog.getByRole("button", { name: "下载权重", exact: true }).click();
  await expect(
    dialog.getByRole("progressbar", { name: "权重下载进度" }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "验证并导入" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "取消下载", exact: true }).click();
  await expect(
    dialog.getByText("下载已取消，可重新下载", { exact: true }),
  ).toBeVisible();
  const started = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api") &&
      response.request().postDataJSON()?.command === "start_download",
  );
  await dialog.getByRole("button", { name: "重新下载", exact: true }).click();
  const id = (await (await started).json()).data.id;
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator(".busy-indicator")).toHaveCount(0);
  await expect
    .poll(async () => {
      const result = await (
        await request.post("/api", {
          data: { command: "download_status", args: { id } },
        })
      ).json();
      return result.data.state;
    })
    .toBe("cancelled");
});
