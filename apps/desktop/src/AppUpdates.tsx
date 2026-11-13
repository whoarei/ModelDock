import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  CheckCircle2,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import {
  APP_VERSION,
  updateService,
  type AppUpdate,
  type UpdateService,
} from "./updater";

type Status =
  | "idle"
  | "checking"
  | "current"
  | "available"
  | "downloading"
  | "installing"
  | "error";
export default function AppUpdates({
  appBusy,
  onBusyChange,
  service = updateService,
  startupDelay = 4000,
}: {
  appBusy: boolean;
  onBusyChange: (message: string) => void;
  service?: UpdateService;
  startupDelay?: number;
}) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [candidate, setCandidate] = useState<AppUpdate | null>(null);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState({ received: 0, total: 0 });
  const operation = useRef(false),
    downloaded = useRef(false),
    resource = useRef<AppUpdate | null>(null);
  const working = status === "downloading" || status === "installing";

  async function checkForUpdates() {
    if (operation.current || !service.supported) return;
    operation.current = true;
    setStatus("checking");
    setError("");
    try {
      await resource.current?.close();
      resource.current = null;
      setCandidate(null);
      downloaded.current = false;
      const result = await service.check();
      resource.current = result;
      setCandidate(result);
      setStatus(result ? "available" : "current");
    } catch (value) {
      setError(String(value instanceof Error ? value.message : value));
      setStatus("error");
    } finally {
      operation.current = false;
    }
  }
  async function install() {
    if (!candidate || operation.current || appBusy) return;
    operation.current = true;
    setError("");
    onBusyChange("准备应用更新");
    try {
      await service.assertReady();
      if (!downloaded.current) {
        setStatus("downloading");
        onBusyChange("下载应用更新");
        setProgress({ received: 0, total: 0 });
        await candidate.download((event) => {
          if (event.event === "Started")
            setProgress({ received: 0, total: event.data.contentLength || 0 });
          if (event.event === "Progress")
            setProgress((p) => ({
              ...p,
              received: p.received + event.data.chunkLength,
            }));
        });
        downloaded.current = true;
      }
      // Jobs may have been queued by another controller during the download.
      await service.assertReady();
      setStatus("installing");
      onBusyChange("安装应用更新");
      await candidate.install();
      await service.restart();
    } catch (value) {
      setError(String(value instanceof Error ? value.message : value));
      setStatus("error");
    } finally {
      operation.current = false;
      onBusyChange("");
    }
  }
  useEffect(() => {
    const timer = setTimeout(() => {
      void checkForUpdates();
    }, startupDelay);
    return () => {
      clearTimeout(timer);
      void resource.current?.close().catch(() => {});
    };
  }, []);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !working) setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [working]);
  const percent = progress.total
    ? Math.min(100, Math.floor((progress.received / progress.total) * 100))
    : null;
  return (
    <>
      <button
        className="sidebar-help update-entry"
        onClick={() => setOpen(true)}
      >
        <ArrowDownToLine size={17} />
        {candidate ? `发现新版本 ${candidate.version}` : "应用更新"}
        {candidate && <i className="update-dot" />}
      </button>
      {open && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !working) setOpen(false);
          }}
        >
          <section
            className="modal update-modal"
            role="dialog"
            aria-modal="true"
            aria-label="应用更新"
          >
            <div className="modal-heading">
              <h2>应用更新</h2>
              <button
                className="icon-button"
                disabled={working}
                aria-label="关闭更新"
                onClick={() => setOpen(false)}
              >
                <X size={19} />
              </button>
            </div>
            <p className="muted">
              当前版本 {APP_VERSION} · Windows x64 · 稳定版
            </p>
            {!service.supported ? (
              <p className="help-note">
                在线更新仅在桌面安装版中提供，浏览器预览不支持安装更新。
              </p>
            ) : (
              <>
                <div className="update-state" role="status">
                  {status === "checking" ? (
                    <>
                      <Loader2 className="spin" size={20} />
                      正在检查更新…
                    </>
                  ) : status === "current" ? (
                    <>
                      <CheckCircle2 size={20} />
                      当前已是最新版本
                    </>
                  ) : status === "installing" ? (
                    <>
                      <Loader2 className="spin" size={20} />
                      正在安装，应用即将退出并重新启动…
                    </>
                  ) : status === "downloading" ? (
                    <>
                      <Loader2 className="spin" size={20} />
                      正在下载并校验更新{percent !== null ? ` ${percent}%` : ""}
                    </>
                  ) : candidate ? (
                    `可更新到 ${candidate.version}`
                  ) : (
                    "检查是否有新的稳定版本"
                  )}
                </div>
                {candidate && (
                  <>
                    <h3>
                      更新说明{" "}
                      {candidate.date ? `· ${candidate.date.slice(0, 10)}` : ""}
                    </h3>
                    <pre className="update-notes">
                      {candidate.body || "此版本未提供更新说明。"}
                    </pre>
                  </>
                )}
                {status === "downloading" && (
                  <>
                    <progress
                      aria-label="更新下载进度"
                      max={progress.total || undefined}
                      value={progress.total ? progress.received : undefined}
                    />
                    <p className="small-text muted">
                      已下载 {(progress.received / 1024 / 1024).toFixed(1)} MB
                    </p>
                  </>
                )}
                {error && (
                  <div className="alert error" role="alert">
                    <span>
                      更新未完成：{error}
                      。可检查网络后重试；校验失败的安装包不会安装。
                    </span>
                  </div>
                )}
                <p className="help-note">
                  安装时应用会关闭并重新启动，请先完成本机任务与插件环境准备。已保存的模型、插件环境和测试记录保留在用户数据目录中。
                </p>
                <div className="modal-footer">
                  <button
                    className="button"
                    disabled={operation.current || working}
                    onClick={() => void checkForUpdates()}
                  >
                    <RefreshCw size={15} />
                    {status === "error" && !candidate ? "重新检查" : "检查更新"}
                  </button>
                  {candidate && (
                    <button
                      className="button primary"
                      disabled={appBusy || operation.current || working}
                      onClick={() => void install()}
                    >
                      <ArrowDownToLine size={15} />
                      {downloaded.current ? "重试安装" : "下载并安装"}
                    </button>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
