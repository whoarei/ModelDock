import { chromium } from "playwright";
import { spawn, execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import { createReadStream } from "node:fs";
import http from "node:http";
import path from "node:path";
import assert from "node:assert/strict";

const root = path.resolve(import.meta.dirname, "../../..");
const source = path.join(root, ".cache/signed-release");
const output = path.join(root, "test-results/upgrade-ui");
await fs.mkdir(output, { recursive: true });
const manifest = JSON.parse(
  await fs.readFile(path.join(source, "latest.json"), "utf8"),
);
const filename = path.basename(
  new URL(manifest.platforms["windows-x86_64"].url).pathname,
);
const payload = path.join(source, filename);
manifest.platforms["windows-x86_64"].url = `http://127.0.0.1:9411/${filename}`;
const server = http.createServer((request, response) => {
  if (request.url === "/latest.json") {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(manifest));
  } else if (request.url === "/" + filename) {
    fs.stat(payload).then((stat) => {
      response.setHeader("Content-Length", stat.size);
      createReadStream(payload).pipe(response);
    });
  } else {
    response.writeHead(404);
    response.end();
  }
});
await new Promise((resolve) => server.listen(9411, "127.0.0.1", resolve));
const environment = {
  ...process.env,
  MODELDOCK_WEBVIEW_DEBUG_PORT: "9222",
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: "--remote-debugging-port=9222",
};
const start = (binary) =>
  spawn(binary, ["--inspect-webview=9222"], { env: environment, stdio: "ignore" });
let app = start(
  path.join(root, "apps/desktop/src-tauri/target/release/modeldock.exe"),
);
let browser, page;
async function connect(timeout = 90000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      browser = await chromium.connectOverCDP("http://127.0.0.1:9222");
      page = browser
        .contexts()
        .flatMap((context) => context.pages())
        .find((p) => p.url().includes("tauri"));
      if (page) {
        await page.waitForFunction(() => window.__TAURI_INTERNALS__?.invoke);
        return;
      }
      await browser.close();
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("Native update client did not become available");
}
try {
  await connect();
  const marker = "升级保留数据 " + Date.now();
  const created = await page.evaluate(
    async (marker) =>
      window.__TAURI_INTERNALS__.invoke("api", {
        command: "add_node",
        args: {
          name: marker,
          host: "example.invalid",
          user: "tester",
          port: 22,
        },
      }),
    marker,
  );
  assert(created.ok);
  const update = await page.evaluate(() =>
    window.__TAURI_INTERNALS__.invoke("plugin:updater|check", {
      timeout: 30000,
    }),
  );
  assert.equal(update.currentVersion, "0.0.0");
  assert.equal(update.version, manifest.version);
  const download = await page.evaluate(async (update) => {
    const progress = [];
    const callback = window.__TAURI_INTERNALS__.transformCallback((raw) => {
      if (raw.message) progress.push(raw.message);
    }, false);
    const bytesRid = await window.__TAURI_INTERNALS__.invoke(
      "plugin:updater|download",
      { rid: update.rid, onEvent: "__CHANNEL__:" + callback, timeout: 120000 },
    );
    window.__upgradeDownload = { updateRid: update.rid, bytesRid };
    return progress;
  }, update);
  assert(
    download.some((event) => event.event === "Finished"),
    "Signed payload must verify before install",
  );
  assert(
    download
      .filter((event) => event.event === "Progress")
      .reduce((sum, event) => sum + event.data.chunkLength, 0) > 1000000,
  );
  await fs.writeFile(
    path.join(output, "download.json"),
    JSON.stringify(
      {
        version: update.version,
        signatureVerified: true,
        events: download.length,
      },
      null,
      2,
    ),
  );
  const stopped = new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("Old client did not exit for installation")),
      60000,
    );
    app.once("exit", (code) => {
      clearTimeout(timer);
      resolve(code);
    });
  });
  await page
    .evaluate(() =>
      window.__TAURI_INTERNALS__.invoke("plugin:updater|install", {
        ...window.__upgradeDownload,
        restartAfterInstall: true,
      }),
    )
    .catch(() => {});
  assert.equal(await stopped, 0);
  await browser.close().catch(() => {});
  browser = null;
  // NSIS should restart the installed app. Reconnect to its inherited debug port.
  await connect(120000);
  const version = await page.evaluate(() =>
    window.__TAURI_INTERNALS__.invoke("plugin:app|version"),
  );
  assert.equal(version, manifest.version);
  const state = await page.evaluate(() =>
    window.__TAURI_INTERNALS__.invoke("api", { command: "state", args: {} }),
  );
  assert(state.ok);
  assert(
    state.data.nodes.some((node) => node.name === marker),
    "User data must survive installation",
  );
  await page.getByRole("button", { name: "应用更新", exact: true }).click();
  await page.screenshot({
    path: path.join(output, "installed.png"),
    fullPage: true,
  });
  await fs.writeFile(
    path.join(output, "report.json"),
    JSON.stringify(
      {
        passed: true,
        from: "0.0.0",
        to: version,
        signatureVerified: true,
        installation: true,
        automaticRestart: true,
        userDataPreserved: true,
      },
      null,
      2,
    ),
  );
  console.log(
    "Signed application download, installation, restart and data preservation passed.",
  );
} catch (error) {
  await fs.writeFile(path.join(output, "failure.txt"), String(error));
  await page
    ?.screenshot({ path: path.join(output, "failure.png"), fullPage: true })
    .catch(() => {});
  throw error;
} finally {
  await browser?.close().catch(() => {});
  app.kill();
  server.close();
  try {
    execFileSync("taskkill", ["/IM", "modeldock.exe", "/T", "/F"], {
      stdio: "ignore",
    });
  } catch {}
}
