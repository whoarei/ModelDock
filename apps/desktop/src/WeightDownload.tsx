import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Download, Loader2, Square } from "lucide-react";
import { api } from "./api";

interface DownloadState {
  id: string;
  state:
    | "queued"
    | "downloading"
    | "cancelling"
    | "succeeded"
    | "failed"
    | "cancelled";
  received: number;
  total: number | null;
  filename: string;
  path?: string;
  sha256?: string;
  verified?: boolean;
  error?: string;
  labels_path?: string;
}
const terminal = new Set(["succeeded", "failed", "cancelled"]);
const mb = (bytes: number) => (bytes / 1024 / 1024).toFixed(1) + " MB";

export default function WeightDownload({
  nodeId,
  pluginId,
  modelId,
  onFile,
  onBusy,
  pretrained = false,
}: {
  nodeId: string;
  pluginId: string;
  modelId: string;
  onFile: (path: string, labelsPath?: string) => void;
  onBusy: (message: string) => void;
  pretrained?: boolean;
}) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [checksum, setChecksum] = useState("");
  const [download, setDownload] = useState<DownloadState | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const mounted = useRef(true),
    pending = useRef(false),
    startingRef = useRef(false),
    current = useRef<DownloadState | null>(null);
  const busy = starting || (!!download && !terminal.has(download.state));

  function receive(value: DownloadState) {
    current.current = value;
    setDownload(value);
    if (terminal.has(value.state)) {
      onBusy("");
      if (value.state === "succeeded" && value.path)
        onFile(value.path, value.labels_path);
      if (value.state === "failed") setError(value.error || "下载失败，请重试");
    }
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (current.current && !terminal.has(current.current.state)) {
        void api("cancel_download", {
          node_id: nodeId,
          id: current.current.id,
        }).catch(() => {});
      }
      if (
        startingRef.current ||
        (current.current && !terminal.has(current.current.state))
      )
        onBusy("");
    };
  }, [nodeId]);
  useEffect(() => {
    if (!download || terminal.has(download.state)) return;
    let live = true;
    async function poll() {
      if (pending.current) return;
      pending.current = true;
      try {
        const value = await api<DownloadState>("download_status", {
          node_id: nodeId,
          id: download!.id,
        });
        if (live) {
          setError("");
          receive(value);
        }
      } catch (value) {
        if (live)
          setError(
            "暂时无法查询进度，正在重试：" +
              String(value instanceof Error ? value.message : value),
          );
      } finally {
        pending.current = false;
      }
    }
    void poll();
    const timer = setInterval(poll, nodeId === "local" ? 750 : 1500);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [download?.id, download?.state, nodeId]);

  async function start() {
    if (busy) return;
    startingRef.current = true;
    setStarting(true);
    setError("");
    current.current = null;
    setDownload(null);
    onFile("");
    onBusy("下载权重");
    try {
      const value = await api<DownloadState>("start_download", {
        node_id: nodeId,
        plugin_id: pluginId,
        model_id: modelId,
        url,
        filename: name,
        sha256: checksum,
        pretrained,
      });
      if (mounted.current) receive(value);
      else
        void api("cancel_download", { node_id: nodeId, id: value.id }).catch(
          () => {},
        );
    } catch (value) {
      if (mounted.current) {
        setError(String(value instanceof Error ? value.message : value));
        onBusy("");
      }
    } finally {
      startingRef.current = false;
      if (mounted.current) setStarting(false);
    }
  }
  async function cancel() {
    if (!download) return;
    onBusy("取消权重下载");
    try {
      const value = await api<DownloadState>("cancel_download", {
        node_id: nodeId,
        id: download.id,
      });
      if (mounted.current) receive(value);
    } catch {
      if (mounted.current) setError("取消请求未送达，请检查节点连接后重试");
    }
  }
  function reset() {
    current.current = null;
    setDownload(null);
    setError("");
    onFile("");
  }
  const percent = download?.total
    ? Math.min(100, Math.floor((download.received / download.total) * 100))
    : null;
  return (
    <div className="weight-download">
      {!pretrained && (
        <label className="field">
          <span>权重下载 URL</span>
          <input
            aria-label="权重下载 URL"
            type="url"
            value={url}
            disabled={busy}
            placeholder="https://example.com/model.onnx"
            onChange={(e) => {
              reset();
              setUrl(e.target.value);
            }}
          />
        </label>
      )}
      <p className="muted small-text">
        {pretrained
          ? "从模型发布方下载预训练权重及使用内置 ImageNet 类别；文件会缓存到当前节点。"
          : "使用 HTTP/HTTPS 文件直链。"}
        {nodeId === "local"
          ? "文件下载到本机。"
          : "文件由当前 SSH 节点直接下载，类别文件也需填写远端路径。"}
      </p>
      {!pretrained && (
        <details className="download-options">
          <summary>文件名与完整性校验（可选）</summary>
          <label className="field">
            <span>保存文件名</span>
            <input
              aria-label="保存文件名"
              value={name}
              disabled={busy}
              placeholder="自动读取文件名"
              onChange={(e) => {
                reset();
                setName(e.target.value);
              }}
            />
          </label>
          <label className="field">
            <span>SHA-256 校验值</span>
            <input
              aria-label="SHA-256 校验值"
              value={checksum}
              disabled={busy}
              placeholder="发布方提供的 64 位十六进制校验值"
              onChange={(e) => {
                reset();
                setChecksum(e.target.value);
              }}
            />
          </label>
        </details>
      )}
      <div className="download-actions">
        <button
          className="button"
          type="button"
          disabled={busy || (!pretrained && !url.trim())}
          onClick={() => void start()}
        >
          {starting ? (
            <Loader2 size={15} className="spin" />
          ) : (
            <Download size={15} />
          )}
          {download?.state === "failed" || download?.state === "cancelled"
            ? "重新下载"
            : "下载权重"}
        </button>
        {download && !terminal.has(download.state) && (
          <button
            className="button subtle"
            type="button"
            onClick={() => void cancel()}
            disabled={download.state === "cancelling"}
          >
            <Square size={14} />
            {download.state === "cancelling" ? "正在取消…" : "取消下载"}
          </button>
        )}
      </div>
      {download && (
        <div className="download-status" role="status">
          {!terminal.has(download.state) && (
            <>
              <progress
                aria-label="权重下载进度"
                max={download.total || undefined}
                value={download.total ? download.received : undefined}
              />
              <span>
                {download.state === "cancelling" ? "正在取消" : "正在下载"}
                {percent !== null ? ` ${percent}%` : ""} ·{" "}
                {mb(download.received)}
                {download.total ? ` / ${mb(download.total)}` : ""}
              </span>
            </>
          )}
          {download.state === "cancelled" && (
            <span>下载已取消，可重新下载</span>
          )}
          {download.state === "succeeded" && (
            <>
              <span className="download-success">
                <CheckCircle2 size={15} />
                已下载：{download.filename} · {mb(download.received)}
                {download.verified ? " · SHA-256 校验通过" : ""}
              </span>
              <small className="mono">SHA-256：{download.sha256}</small>
              <span>请继续点击“验证并导入”检查模型兼容性。</span>
            </>
          )}
        </div>
      )}
      {error && (
        <div className="alert error" role="alert">
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
