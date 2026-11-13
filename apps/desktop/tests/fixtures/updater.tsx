import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import AppUpdates from "../../src/AppUpdates";
import "../../src/styles.css";
const scenario = new URLSearchParams(location.search).get("scenario");
const state = ((window as any).updates = {
  checks: 0,
  downloads: 0,
  installs: 0,
  restarts: 0,
  blocked: false,
  afterDownloadBlock: false,
  downloadError: false,
  checkError: scenario === "offline",
  available: scenario !== "offline",
  finishDownload: () => {},
});
function Harness() {
  const [busy, setBusy] = useState("");
  return (
    <AppUpdates
      appBusy={!!busy}
      onBusyChange={setBusy}
      startupDelay={20}
      service={{
        supported: true,
        check: async () => {
          state.checks++;
          if (state.checkError) throw new Error("网络连接失败");
          return state.available
            ? {
                version: "0.3.0",
                body: "修复推理问题\n<b>更新说明按文本显示</b>",
                date: "2026-11-14T00:00:00Z",
                download: async (event) => {
                  state.downloads++;
                  event({ event: "Started", data: { contentLength: 100 } });
                  event({ event: "Progress", data: { chunkLength: 50 } });
                  await new Promise<void>((resolve) => {
                    state.finishDownload = resolve;
                  });
                  if (state.downloadError)
                    throw new Error("安装包签名校验失败");
                  event({ event: "Progress", data: { chunkLength: 50 } });
                  event({ event: "Finished" });
                  if (state.afterDownloadBlock) state.blocked = true;
                },
                install: async () => {
                  state.installs++;
                },
                close: async () => {},
              }
            : null;
        },
        assertReady: async () => {
          if (state.blocked) throw new Error("请先完成本机测试任务");
        },
        restart: async () => {
          state.restarts++;
        },
      }}
    />
  );
}
createRoot(document.getElementById("root")!).render(<Harness />);
