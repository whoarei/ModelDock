import { chromium } from "playwright";
import { spawn, execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
import http from "node:http";
import { createHash } from "node:crypto";

const root = path.resolve(import.meta.dirname, "../../..");
const { version } = JSON.parse(
  await fs.readFile(path.join(root, "apps/desktop/package.json"), "utf8"),
);
const data = path.join(root, "test-results/native-runtime");
const fixtures = path.join(root, "test-results/native-fixtures");
const output = path.join(root, "test-results/native-ui");
await fs.mkdir(output, { recursive: true });
execFileSync(
  "uv",
  [
    "run",
    "--project",
    root,
    "python",
    path.join(root, "scripts/create_fixtures.py"),
    fixtures,
  ],
  { stdio: "inherit" },
);
execFileSync("uv", ["python", "install", "3.12.14"], {
  stdio: "inherit",
  env: { ...process.env, UV_PYTHON_INSTALL_DIR: path.join(data, "python") },
});
const binary =
  process.env.MODELDOCK_NATIVE_BINARY ||
  path.join(root, "apps/desktop/src-tauri/target/release/modeldock.exe");
const weightBytes = await fs.readFile(
  path.join(fixtures, "color-classifier.onnx"),
);
const weightHash = createHash("sha256").update(weightBytes).digest("hex");
const weightServer = http.createServer((_request, response) => {
  response.writeHead(200, {
    "Content-Type": "application/octet-stream",
    "Content-Length": weightBytes.length,
  });
  response.end(weightBytes);
});
await new Promise((resolve) => weightServer.listen(0, "127.0.0.1", resolve));
const weightURL = `http://127.0.0.1:${weightServer.address().port}/model.onnx`;
const app = spawn(binary, [], {
  env: {
    ...process.env,
    MODELDOCK_DATA_DIR: data,
    MODELDOCK_WEBVIEW_DEBUG_PORT: "9222",
    WEBVIEW2_USER_DATA_FOLDER: path.join(data, "webview2"),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: "--remote-debugging-port=9222",
  },
  stdio: "ignore",
});
let browser;
let page;
try {
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    if (app.exitCode !== null)
      throw new Error("Native app exited: " + app.exitCode);
    try {
      const response = await fetch("http://127.0.0.1:9222/json/version");
      if (response.ok) break;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  browser = await chromium.connectOverCDP("http://127.0.0.1:9222");
  for (let attempt = 0; attempt < 60; attempt++) {
    page = browser
      .contexts()
      .flatMap((c) => c.pages())
      .find(
        (p) =>
          p.url().includes("tauri.localhost") || p.url().includes("tauri://"),
      );
    if (page) break;
    await new Promise((r) => setTimeout(r, 500));
  }
  assert(page, "Tauri WebView page not found");
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.waitForFunction(() => window.__TAURI_INTERNALS__?.invoke, {
    timeout: 60000,
  });
  async function api(command, args = {}) {
    const response = await page.evaluate(
      ({ command, args }) =>
        window.__TAURI_INTERNALS__.invoke("api", { command, args }),
      { command, args },
    );
    assert(response.ok, JSON.stringify(response));
    return response.data;
  }
  let state = await api("state");
  assert.equal(state.version, version);
  for (const name of ["efficientnet", "yolo"]) {
    await api("install_plugin", { plugin_id: name, profile_id: "onnx-cpu" });
    const stop = Date.now() + 240000;
    while (Date.now() < stop) {
      state = await api("state");
      const installation = state.installations.find((i) => i.id === name);
      if (installation.state === "ready") break;
      assert.notEqual(
        installation.state,
        "failed",
        JSON.stringify(installation),
      );
      await new Promise((r) => setTimeout(r, 500));
    }
    assert.equal(state.installations.find((i) => i.id === name).state, "ready");
  }
  for (const [name, plugin, model, weight, labels, parameters] of [
    [
      "颜色分类 · Windows 原生",
      "efficientnet",
      "efficientnet_b0",
      "color-classifier.onnx",
      "classification-labels.txt",
      { top_k: 2 },
    ],
    [
      "检测协议 · Windows 原生",
      "yolo",
      "yolov8n",
      "detection-fixture.onnx",
      "detection-labels.txt",
      {},
    ],
  ]) {
    let weightPath = path.join(fixtures, weight);
    if (plugin === "efficientnet") {
      let download = await api("start_download", {
        plugin_id: plugin,
        model_id: model,
        url: weightURL,
        filename: "网址分类.onnx",
        sha256: weightHash,
      });
      const stop = Date.now() + 60000;
      while (
        !["succeeded", "failed", "cancelled"].includes(download.state) &&
        Date.now() < stop
      ) {
        await new Promise((r) => setTimeout(r, 300));
        download = await api("download_status", { id: download.id });
      }
      assert.equal(download.state, "succeeded", JSON.stringify(download));
      assert.equal(download.sha256, weightHash);
      assert.equal(download.verified, true);
      assert.deepEqual(await fs.readFile(download.path), weightBytes);
      weightPath = download.path;
    }
    const instance = await api("create_model", {
      plugin_id: plugin,
      model_id: model,
      name,
      weight_path: weightPath,
      labels_path: path.join(fixtures, labels),
      parameters,
    });
    assert.equal(instance.state, "ready", instance.error);
    const task = await api("start_task", {
      model_instance_id: instance.id,
      paths: [path.join(fixtures, "red.png")],
      mode: "single",
    });
    let result;
    const stop = Date.now() + 60000;
    while (Date.now() < stop) {
      result = await api("task_detail", { task_id: task.id });
      if (
        ["SUCCEEDED", "FAILED", "PARTIAL_FAILED", "CANCELLED"].includes(
          result.state,
        )
      )
        break;
      await new Promise((r) => setTimeout(r, 300));
    }
    assert.equal(result.state, "SUCCEEDED", JSON.stringify(result));
    assert(result.metrics.stages.inference_ms.mean > 0);
    if (plugin === "efficientnet")
      assert.equal(result.results[0].prediction.top_k[0].label, "red");
    else assert.equal(result.results[0].prediction.detections.length, 2);
    const preview = await api("preview", {
      task_id: task.id,
      sample_id: "000000",
    });
    assert(preview.url.startsWith("data:image/jpeg;base64,"));
    await page.getByRole("button", { name: "测试记录", exact: true }).click();
    const row = page
      .locator(".history-table tbody tr")
      .filter({ hasText: name });
    await row.getByRole("button", { name: "查看" }).click();
    await page.locator(".image-stage img").waitFor({ timeout: 30000 });
    await page.screenshot({
      path: path.join(output, plugin + ".png"),
      fullPage: true,
    });
    const exported = await api("export", { task_id: task.id, format: "json" });
    const destination = path.join(output, plugin + "-export.json");
    await page.evaluate(
      ({ destination, text }) =>
        window.__TAURI_INTERNALS__.invoke("write_file", {
          path: destination,
          bytes: Array.from(new TextEncoder().encode(text)),
        }),
      { destination, text: exported.content },
    );
    assert.equal(
      JSON.parse(await fs.readFile(destination, "utf8")).id,
      task.id,
    );
  }
  assert.deepEqual(errors, []);
  await fs.writeFile(
    path.join(output, "report.json"),
    JSON.stringify(
      {
        passed: true,
        native: true,
        version,
        checks: [
          "Windows WebView2",
          "Tauri IPC",
          "managed Python",
          "isolated uv environments",
          "URL weights and SHA-256 verification",
          "classification",
          "detection and NMS",
          "preview",
          "file export",
        ],
      },
      null,
      2,
    ),
  );
  console.log("Native Windows smoke test passed.");
} catch (error) {
  if (page)
    await page
      .screenshot({ path: path.join(output, "failure.png"), fullPage: true })
      .catch(() => {});
  await fs.writeFile(path.join(output, "failure.txt"), String(error));
  try {
    const diagnostics = execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('modeldock.exe','msedgewebview2.exe') } | Select-Object Name,ProcessId,SessionId,CommandLine | ConvertTo-Json",
      ],
      { encoding: "utf8" },
    );
    await fs.writeFile(path.join(output, "processes.json"), diagnostics);
  } catch {}
  throw error;
} finally {
  if (browser) await browser.close().catch(() => {});
  app.kill();
  await new Promise((resolve) => weightServer.close(resolve));
}
