import { useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  Boxes,
  Puzzle,
  Server,
  History,
  Plus,
  Play,
  Square,
  Upload,
  FolderOpen,
  Image as ImageIcon,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  Download,
  RefreshCw,
  Activity,
  Cpu,
  HelpCircle,
  ArrowRight,
  Trash2,
  Fingerprint,
  KeyRound,
  ChevronRight,
  SlidersHorizontal,
  FileText,
  Network,
} from "lucide-react";
import { api, pickFiles, exportTask } from "./api";
import { Performance, number } from "./charts";
import Viewer from "./Viewer";
import AppUpdates from "./AppUpdates";
import WeightDownload from "./WeightDownload";
import ModelChooser from "./ModelChooser";
import { APP_VERSION } from "./updater";
import type {
  Params,
  Plugin,
  ModelSpec,
  Snapshot,
  Task,
  Node,
  Result,
} from "./types";
import { terminal, stateLabel } from "./types";

type Page = "workbench" | "models" | "plugins" | "nodes" | "history";
const navigation = [
  ["workbench", "测试工作台", LayoutDashboard],
  ["models", "模型管理", Boxes],
  ["plugins", "插件管理", Puzzle],
  ["nodes", "运行节点", Server],
  ["history", "测试记录", History],
] as const;
const date = (value: number) =>
  new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(value * 1000);
const basename = (value: string) => value.split(/[\\/]/).pop() || value;
function defaults(spec: ModelSpec | undefined): Params {
  return Object.fromEntries(
    Object.entries(spec?.parameter_schema_data?.properties || {})
      .filter(([, v]) => v.default !== undefined)
      .map(([key, v]) => [key, v.default]),
  );
}
function Logo() {
  return (
    <svg viewBox="0 0 36 36" className="brand-mark" aria-hidden="true">
      <rect width="36" height="36" rx="10" fill="#123e41" />
      <path d="M18 5 27 10 18 15 9 10Z" fill="#58ddcf" />
      <path d="M9 10 18 15 18 25 9 20Z" fill="#21b6a7" />
      <path d="M27 10 18 15 18 25 27 20Z" fill="#098f86" />
      <path
        d="M6 23v5c0 2 1 3 3 3h18c2 0 3-1 3-3v-5"
        stroke="#75e4d6"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}
function Badge({ state }: { state: string }) {
  return (
    <span
      className={
        "badge " +
        (state === "SUCCEEDED" || state === "ready" || state === "online"
          ? "success"
          : state === "FAILED" || state === "failed" || state === "invalid"
            ? "danger"
            : !terminal.has(state) &&
                [
                  "RUNNING",
                  "PREPARING",
                  "preparing",
                  "validating",
                  "CANCEL_REQUESTED",
                ].includes(state)
              ? "working"
              : "neutral")
      }
    >
      <i />
      {stateLabel[state] || state}
    </span>
  );
}
function Empty({
  icon: Icon = Boxes,
  title,
  description,
  action,
}: {
  icon?: any;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Icon size={29} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
function ParamsFields({
  spec,
  value,
  onChange,
  disabledKeys = [],
}: {
  spec: ModelSpec | undefined;
  value: Params;
  onChange: (p: Params) => void;
  disabledKeys?: string[];
}) {
  return (
    <>
      {Object.entries(spec?.parameter_schema_data?.properties || {}).map(
        ([key, field]) => (
          <label className="field" key={key}>
            <span>{field.title || key}</span>
            {field.enum ? (
              <select
                disabled={disabledKeys.includes(key)}
                value={String(value[key] ?? field.default ?? "")}
                onChange={(e) =>
                  onChange({
                    ...value,
                    [key]: field.enum.find(
                      (v: any) => String(v) === e.target.value,
                    ),
                  })
                }
              >
                {field.enum.map((v: any) => (
                  <option key={String(v)} value={String(v)}>
                    {String(v)}
                  </option>
                ))}
              </select>
            ) : field.type === "boolean" ? (
              <input
                disabled={disabledKeys.includes(key)}
                type="checkbox"
                checked={Boolean(value[key] ?? field.default)}
                onChange={(e) =>
                  onChange({ ...value, [key]: e.target.checked })
                }
              />
            ) : field.type === "object" ? (
              <textarea
                disabled={disabledKeys.includes(key)}
                defaultValue={JSON.stringify(value[key] ?? field.default ?? {})}
                onBlur={(e) => {
                  try {
                    onChange({ ...value, [key]: JSON.parse(e.target.value) });
                  } catch {
                    e.target.setCustomValidity("请输入有效 JSON");
                  }
                }}
              />
            ) : (
              <input
                disabled={disabledKeys.includes(key)}
                type={
                  ["number", "integer"].includes(field.type) ? "number" : "text"
                }
                min={field.minimum}
                max={field.maximum}
                step={
                  field.type === "integer"
                    ? 1
                    : field.type === "number"
                      ? 0.01
                      : undefined
                }
                value={String(value[key] ?? field.default ?? "")}
                onChange={(e) =>
                  onChange({
                    ...value,
                    [key]: ["number", "integer"].includes(field.type)
                      ? Number(e.target.value)
                      : e.target.value,
                  })
                }
              />
            )}
          </label>
        ),
      )}
    </>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("workbench"),
    [nodeId, setNodeId] = useState("local"),
    [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [nodes, setNodes] = useState<Node[]>([
      { id: "local", name: "本机", kind: "local" },
    ]);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(""),
    [modal, setModal] = useState<
      null | "model" | "node" | "help" | "fingerprint" | "compare"
    >(null);
  const [modelDownloading, setModelDownloading] = useState(false);
  function closeModal() {
    if (!busy || modelDownloading) setModal(null);
  }
  const [selectedModel, setSelectedModel] = useState(""),
    [paths, setPaths] = useState<string[]>([]),
    [remotePaths, setRemotePaths] = useState(""),
    [source, setSource] = useState("local"),
    [mode, setMode] = useState("single"),
    [iterations, setIterations] = useState(100),
    [warmup, setWarmup] = useState(10),
    [threads, setThreads] = useState(1),
    [params, setParams] = useState<Params>({});
  const [taskId, setTaskId] = useState(""),
    [detail, setDetail] = useState<Task | null>(null),
    [sampleId, setSampleId] = useState(""),
    [view, setView] = useState("preview"),
    [search, setSearch] = useState(""),
    [resultSearch, setResultSearch] = useState(""),
    [resultFilter, setResultFilter] = useState("all");
  const [modelPlugin, setModelPlugin] = useState("efficientnet"),
    [modelType, setModelType] = useState("efficientnet_b0"),
    [modelName, setModelName] = useState(""),
    [weight, setWeight] = useState(""),
    [labels, setLabels] = useState(""),
    [modelParams, setModelParams] = useState<Params>({ top_k: 5 }),
    [modelSource, setModelSource] = useState("local");
  const [nodeForm, setNodeForm] = useState({
      name: "",
      host: "",
      user: "",
      port: 22,
      key_path: "",
      work_root: "~/.local/share/modeldock",
    }),
    [fingerprintNode, setFingerprintNode] = useState<Node | null>(null),
    [fingerprints, setFingerprints] = useState<
      { type: string; fingerprint: string }[]
    >([]),
    [compareIds, setCompareIds] = useState<string[]>([]),
    [comparison, setComparison] = useState<Task[]>([]);
  const refreshing = useRef<Record<string, boolean>>({}),
    nodeRef = useRef(nodeId);
  nodeRef.current = nodeId;
  const handleError = (value: unknown) =>
    setError(value instanceof Error ? value.message : String(value));
  async function refresh() {
    const current = nodeRef.current;
    if (refreshing.current[current]) return;
    refreshing.current[current] = true;
    try {
      const value = await api<Snapshot>("state", { node_id: current });
      if (current === nodeRef.current) {
        setSnapshot(value);
        setNodes(value.nodes);
      }
    } catch (e) {
      if (current === nodeRef.current) handleError(e);
    } finally {
      delete refreshing.current[current];
    }
  }
  async function perform(name: string, action: () => Promise<unknown>) {
    setBusy(name);
    setError("");
    try {
      await action();
      await refresh();
    } catch (e) {
      handleError(e);
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    setSnapshot(null);
    setError("");
    setTaskId("");
    setDetail(null);
    setPaths([]);
    setRemotePaths("");
    setCompareIds([]);
    setComparison([]);
    refresh();
    const timer = setInterval(refresh, nodeId === "local" ? 1800 : 4000);
    return () => clearInterval(timer);
  }, [nodeId]);
  useEffect(() => {
    if (!taskId) {
      setDetail(null);
      return;
    }
    let live = true;
    let pending = false;
    async function poll() {
      if (pending) return;
      pending = true;
      try {
        const value = await api<Task>("task_detail", {
          node_id: nodeId,
          task_id: taskId,
        });
        if (live) setDetail(value);
      } catch (e) {
        if (live) handleError(e);
      } finally {
        pending = false;
      }
    }
    poll();
    const timer = setInterval(poll, nodeId === "local" ? 1200 : 4000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [taskId, nodeId]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeModal();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [busy, modelDownloading]);
  const models = snapshot?.models || [],
    plugins = snapshot?.plugins || [],
    tasks = snapshot?.tasks || [],
    installations = snapshot?.installations || [];
  const readyForPlugin = (id: string) =>
    installations.some(
      (i) =>
        i.id === id &&
        i.state === "ready" &&
        i.plugin_digest === plugins.find((p) => p.id === id)?.digest,
    );
  const canRunModel = (model: Snapshot["models"][number]) =>
    model.state === "ready" &&
    readyForPlugin(model.plugin_id) &&
    !!plugins
      .find((p) => p.id === model.plugin_id)
      ?.manifest.models.some((m) => m.id === model.model_id);
  const readyModels = models.filter(canRunModel),
    currentModel = models.find((m) => m.id === selectedModel),
    currentPlugin = plugins.find((p) => p.id === currentModel?.plugin_id),
    spec = currentPlugin?.manifest.models.find(
      (m) => m.id === currentModel?.model_id,
    );
  const formPlugin = plugins.find((p) => p.id === modelPlugin),
    formSpec = formPlugin?.manifest.models.find((m) => m.id === modelType);
  const providers =
    currentModel?.validation?.providers ||
    currentPlugin?.manifest.runtime_profiles.find(
      (p) =>
        p.id ===
        installations.find((i) => i.id === currentPlugin.id)?.profile_id,
    )?.providers ||
    [];
  const engineName = providers.some((p) => p.endsWith("ExecutionProvider"))
    ? "ONNX Runtime"
    : providers.includes("PyTorchCPU")
      ? "PyTorch"
      : currentModel
        ? "Python 插件"
        : "待选择模型";
  const deviceName = providers.includes("CUDAExecutionProvider")
    ? "CUDA"
    : providers.includes("CPUExecutionProvider") ||
        providers.includes("PyTorchCPU")
      ? "CPU"
      : currentModel
        ? "插件设备"
        : "未选择模型";
  useEffect(() => {
    if (!readyModels.some((m) => m.id === selectedModel))
      setSelectedModel(readyModels[0]?.id || "");
  }, [readyModels.map((m) => m.id).join("|"), selectedModel]);
  useEffect(() => {
    setParams({
      ...defaults(spec),
      ...(currentModel?.validation?.parameters ||
        currentModel?.parameters ||
        {}),
    });
  }, [selectedModel, spec?.id]);
  const selectedRecord =
    detail?.results?.find((r) => r.sample_id === sampleId) ||
    detail?.results?.find((r) => r.status === "succeeded") ||
    detail?.results?.[0] ||
    null;
  const completedTasks = tasks.filter((t) => terminal.has(t.state));
  const recent = completedTasks.find(
    (t) => t.metrics?.stages.sample_total_ms,
  )?.metrics;
  const activeNode = nodes.find((n) => n.id === nodeId);
  const taskRows = (detail?.results || []).filter(
    (r) =>
      (resultFilter === "all" || r.status === resultFilter) &&
      (!resultSearch ||
        (r.filename + " " + JSON.stringify(r.prediction))
          .toLowerCase()
          .includes(resultSearch.toLowerCase())),
  );

  async function chooseInputs(directory = false) {
    const files = await pickFiles({
      multiple: mode !== "single",
      directory,
      extensions: directory
        ? undefined
        : ["png", "jpg", "jpeg", "bmp", "webp", "tif", "tiff"],
    });
    if (files.length) setPaths(files);
  }
  function openModel() {
    const plugin = plugins.find((p) => readyForPlugin(p.id)) || plugins[0];
    if (plugin) {
      setModelPlugin(plugin.id);
      setModelType(plugin.manifest.models[0].id);
      setModelParams(defaults(plugin.manifest.models[0]));
    }
    setModelName("");
    setWeight("");
    setLabels("");
    setModelSource("local");
    setModal("model");
  }
  async function createModel() {
    await perform("验证并导入模型", async () => {
      const value = await api("create_model", {
        node_id: nodeId,
        plugin_id: modelPlugin,
        model_id: modelType,
        name: modelName,
        weight_path: weight,
        labels_path: labels,
        parameters: modelParams,
        source: ["url", "pretrained"].includes(modelSource)
          ? "remote"
          : modelSource,
      });
      if (value.state !== "ready")
        throw new Error(value.error || "模型验证失败");
      setSelectedModel(value.id);
      setNotice("模型加载验证通过");
      setModal(null);
    });
  }
  async function startTask() {
    await perform("提交测试", async () => {
      const value = await api<Task>("start_task", {
        node_id: nodeId,
        model_instance_id: selectedModel,
        paths:
          source === "remote"
            ? remotePaths
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean)
            : paths,
        mode,
        iterations,
        warmup,
        threads,
        parameters: params,
        source,
      });
      setTaskId(value.id);
      setSampleId("");
      setView("preview");
      setNotice("测试任务已提交");
    });
  }
  async function inspect(task: Task) {
    setTaskId(task.id);
    setSampleId("");
    setPage("workbench");
    setView("preview");
  }
  async function compare() {
    await perform("加载对比结果", async () => {
      setComparison(
        await Promise.all(
          compareIds.map((task_id) =>
            api<Task>("task_detail", { node_id: nodeId, task_id }),
          ),
        ),
      );
      setModal("compare");
    });
  }
  function setPlugin(id: string) {
    setWeight("");
    setLabels("");
    setModelSource("local");
    setModelPlugin(id);
    const p = plugins.find((p) => p.id === id);
    if (p) {
      setModelType(p.manifest.models[0].id);
      setModelParams(defaults(p.manifest.models[0]));
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            <strong>ModelDock</strong>
            <span>模型坞</span>
          </div>
        </div>
        <div className="nav-caption">工作空间</div>
        <nav>
          {navigation.map(([key, label, Icon]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              aria-label={label}
              onClick={() => setPage(key)}
            >
              <Icon size={18} />
              {label}
              {key === "models" && models.length > 0 && (
                <span>{models.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-tip">
          <div className="tip-icon">
            <Puzzle size={18} />
          </div>
          <strong>模型能力，按需接入</strong>
          <p>
            Python 插件独立运行
            <br />
            本机与远程使用同一协议
          </p>
        </div>
        <AppUpdates appBusy={!!busy} onBusyChange={setBusy} />
        <button className="sidebar-help" onClick={() => setModal("help")}>
          <HelpCircle size={17} />
          使用说明<small>v{APP_VERSION}</small>
        </button>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间
            <ChevronRight size={14} />
            <strong>{navigation.find((n) => n[0] === page)?.[1]}</strong>
          </div>
          <div className="topbar-right">
            <span className="local-indicator">
              <i />
              {nodeId === "local" ? "本机运行" : "SSH 远程"}
            </span>
            <button
              className="icon-button"
              title="刷新"
              onClick={() => refresh()}
            >
              <RefreshCw size={17} />
            </button>
            <span className="avatar">M</span>
          </div>
        </header>
        <main>
          {error && (
            <div className="alert error" role="alert">
              <AlertCircle size={18} />
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="关闭错误">
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              <CheckCircle2 size={18} />
              <span>{notice}</span>
              <button onClick={() => setNotice("")} aria-label="关闭通知">
                <X size={16} />
              </button>
            </div>
          )}
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                MODELDOCK /{" "}
                {nodeId === "local" ? "LOCAL WORKSPACE" : "REMOTE WORKSPACE"}
              </div>
              <h1>
                {page === "workbench"
                  ? "模型测试工作台"
                  : navigation.find((n) => n[0] === page)?.[1]}
              </h1>
              <p>
                {
                  {
                    workbench: "连接模型与数据，查看每一次推理的真实结果。",
                    models: "管理模型权重、类别映射与经过验证的配置。",
                    plugins:
                      "用 Python 扩展模型能力，每个插件拥有独立运行环境。",
                    nodes: "把同一套模型测试流程，带到你的远程算力上。",
                    history: "保留测试条件与结果，让每一次比较都有据可依。",
                  }[page]
                }
              </p>
            </div>
            <div className="heading-actions">
              {page === "models" ? (
                <button
                  className="button primary"
                  onClick={openModel}
                  disabled={!plugins.length}
                >
                  <Plus size={17} />
                  导入模型
                </button>
              ) : page === "plugins" ? (
                <button
                  className="button primary"
                  disabled={!!busy}
                  onClick={() =>
                    perform("导入插件", async () => {
                      const files = await pickFiles({ extensions: ["zip"] });
                      if (files[0]) {
                        await api("import_plugin", { path: files[0] });
                        setNotice("插件已导入本机目录，可安装到所选节点");
                      }
                    })
                  }
                >
                  <Plus size={17} />
                  导入插件包
                </button>
              ) : page === "nodes" ? (
                <button
                  className="button primary"
                  onClick={() => {
                    setNodeForm({
                      name: "",
                      host: "",
                      user: "",
                      port: 22,
                      key_path: "",
                      work_root: "~/.local/share/modeldock",
                    });
                    setModal("node");
                  }}
                >
                  <Plus size={17} />
                  添加 SSH 节点
                </button>
              ) : page === "history" ? (
                <button
                  className="button"
                  onClick={compare}
                  disabled={compareIds.length < 2 || !!busy}
                >
                  <Activity size={17} />
                  对比所选 ({compareIds.length})
                </button>
              ) : (
                <button
                  className="button"
                  onClick={openModel}
                  disabled={!plugins.length}
                >
                  <Plus size={17} />
                  导入模型
                </button>
              )}
            </div>
          </div>
          <div className="node-strip">
            <div>
              <Server size={16} />
              <span>运行节点</span>
              <select
                aria-label="运行节点"
                disabled={!!busy}
                value={nodeId}
                onChange={(e) => setNodeId(e.target.value)}
              >
                {nodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name}
                    {n.kind === "ssh" ? " · SSH" : " · Local"}
                  </option>
                ))}
              </select>
              <span className="strip-divider" />
              <span className="platform-tag">
                {snapshot?.node.platform || "未连接"}
              </span>
              <span className="cpu-provider">
                <Cpu size={14} />
                {deviceName}
              </span>
            </div>
            <button onClick={() => setPage("nodes")}>
              管理节点
              <ArrowRight size={14} />
            </button>
          </div>
          {!snapshot && (
            <div className="connecting">
              <Loader2 className="spin" size={19} />
              <span>正在连接运行节点…</span>
              <button className="text-button" onClick={refresh}>
                重试
              </button>
            </div>
          )}

          {page === "workbench" && (
            <>
              <div className="kpi-grid">
                <div className="kpi">
                  <div>
                    <span>可用模型</span>
                    <Boxes size={17} />
                  </div>
                  <strong>
                    {readyModels.length}
                    <small>/ {models.length} 个实例</small>
                  </strong>
                  <p>已通过加载检查</p>
                </div>
                <div className="kpi">
                  <div>
                    <span>测试记录</span>
                    <History size={17} />
                  </div>
                  <strong>
                    {tasks.length}
                    <small>次测试</small>
                  </strong>
                  <p>
                    {tasks.filter((t) => !terminal.has(t.state)).length}{" "}
                    个任务正在进行
                  </p>
                </div>
                <div className="kpi">
                  <div>
                    <span>最近平均处理耗时</span>
                    <Activity size={17} />
                  </div>
                  <strong>
                    {number(recent?.stages.sample_total_ms?.mean)}
                    <small>ms</small>
                  </strong>
                  <p>预热不计入统计</p>
                </div>
                <div className="kpi">
                  <div>
                    <span>运行后端</span>
                    <Cpu size={17} />
                  </div>
                  <strong className="backend-name">{engineName}</strong>
                  <p>
                    <i className="status-dot" />
                    {providers.join(" · ") || "运行后端由模型插件提供"}
                  </p>
                </div>
              </div>
              <div className="workbench-grid">
                <section className="panel test-config">
                  <div className="panel-title">
                    <div className="title-with-icon">
                      <SlidersHorizontal size={17} />
                      <h3>测试配置</h3>
                    </div>
                    <span>01</span>
                  </div>
                  <div className="config-content">
                    <label className="field">
                      <span>
                        模型实例
                        <button className="text-button" onClick={openModel}>
                          添加
                        </button>
                      </span>
                      <select
                        aria-label="模型实例"
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                      >
                        <option value="">选择模型实例</option>
                        {readyModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    {currentModel && (
                      <div className="model-mini">
                        <div className="model-mini-icon">
                          <Boxes size={18} />
                        </div>
                        <div>
                          <strong>{currentModel.model_id}</strong>
                          <span>
                            ONNX ·{" "}
                            {currentModel.task === "classification"
                              ? "图像分类"
                              : "目标检测"}
                          </span>
                        </div>
                        <CheckCircle2 size={15} />
                      </div>
                    )}
                    <div className="field">
                      <span>测试模式</span>
                      <div className="segmented">
                        {[
                          ["single", "单图"],
                          ["batch", "批量"],
                          ["benchmark", "性能"],
                        ].map(([id, label]) => (
                          <button
                            key={id}
                            className={mode === id ? "selected" : ""}
                            onClick={() => setMode(id)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                    {nodeId !== "local" && (
                      <label className="field">
                        <span>输入来源</span>
                        <select
                          value={source}
                          onChange={(e) => setSource(e.target.value)}
                        >
                          <option value="local">上传本机图片</option>
                          <option value="remote">远端已有路径</option>
                        </select>
                      </label>
                    )}
                    {source === "remote" ? (
                      <label className="field">
                        <span>远端图片或目录 · 每行一个</span>
                        <textarea
                          placeholder="/data/images"
                          value={remotePaths}
                          onChange={(e) => setRemotePaths(e.target.value)}
                        />
                      </label>
                    ) : (
                      <>
                        <button
                          className="upload-zone"
                          onClick={() => chooseInputs().catch(handleError)}
                        >
                          <div>
                            <Upload size={21} />
                          </div>
                          <strong>
                            {paths.length
                              ? `已选择 ${paths.length} 个输入`
                              : "选择测试图片"}
                          </strong>
                          <span>PNG、JPG、BMP、WEBP、TIFF</span>
                        </button>
                        {mode !== "single" && (
                          <button
                            className="button subtle wide"
                            onClick={() =>
                              chooseInputs(true).catch(handleError)
                            }
                          >
                            <FolderOpen size={15} />
                            选择图片目录
                          </button>
                        )}
                        {paths.length > 0 && (
                          <div className="file-chips">
                            {paths.slice(0, 3).map((p, i) => (
                              <span key={p}>
                                <ImageIcon size={12} />
                                {basename(p)}
                                <button
                                  aria-label="移除图片"
                                  onClick={() =>
                                    setPaths(
                                      paths.filter((_, index) => index !== i),
                                    )
                                  }
                                >
                                  <X size={12} />
                                </button>
                              </span>
                            ))}
                            {paths.length > 3 && (
                              <small>另有 {paths.length - 3} 个输入</small>
                            )}
                          </div>
                        )}
                      </>
                    )}
                    <div className="config-divider" />
                    <div className="mini-heading">
                      模型参数
                      <span>
                        {Array.isArray(spec?.config_data?.input_size)
                          ? spec.config_data.input_size.join(" × ")
                          : "—"}
                      </span>
                    </div>
                    <ParamsFields
                      spec={spec}
                      value={params}
                      onChange={setParams}
                    />
                    <details className="advanced">
                      <summary>高级测试设置</summary>
                      <label className="field">
                        <span>推理线程数</span>
                        <input
                          type="number"
                          min="1"
                          max="64"
                          value={threads}
                          onChange={(e) => setThreads(Number(e.target.value))}
                        />
                      </label>
                      {mode === "benchmark" && (
                        <div className="two-fields">
                          <label className="field">
                            <span>正式次数</span>
                            <input
                              type="number"
                              min="1"
                              max="10000"
                              value={iterations}
                              onChange={(e) =>
                                setIterations(Number(e.target.value))
                              }
                            />
                          </label>
                          <label className="field">
                            <span>预热次数</span>
                            <input
                              type="number"
                              min="0"
                              max="10000"
                              value={warmup}
                              onChange={(e) =>
                                setWarmup(Number(e.target.value))
                              }
                            />
                          </label>
                        </div>
                      )}
                    </details>
                    <button
                      className="button primary wide run-button"
                      disabled={
                        !!busy ||
                        !selectedModel ||
                        (source === "local"
                          ? !paths.length
                          : !remotePaths.trim())
                      }
                      onClick={startTask}
                    >
                      {busy === "提交测试" ? (
                        <Loader2 className="spin" size={17} />
                      ) : (
                        <Play size={17} />
                      )}
                      开始测试
                    </button>
                    <p className="config-note">
                      模型在所选节点运行，测试配置随结果保存。
                    </p>
                  </div>
                </section>
                <div className="workbench-results">
                  <div className="results-topline">
                    <div className="tabs">
                      <button
                        className={view === "preview" ? "active" : ""}
                        onClick={() => setView("preview")}
                      >
                        效果预览
                      </button>
                      <button
                        className={view === "performance" ? "active" : ""}
                        onClick={() => setView("performance")}
                      >
                        性能分析
                      </button>
                    </div>
                    {detail ? (
                      <div className="task-actions">
                        <Badge state={detail.state} />
                        {!terminal.has(detail.state) && (
                          <button
                            className="button small-button"
                            onClick={() =>
                              perform("停止测试", () =>
                                api("cancel_task", {
                                  node_id: nodeId,
                                  task_id: detail.id,
                                }),
                              )
                            }
                          >
                            <Square size={12} />
                            停止
                          </button>
                        )}
                      </div>
                    ) : (
                      <span className="muted">尚未开始测试</span>
                    )}
                  </div>
                  {detail && !terminal.has(detail.state) && (
                    <div className="task-progress">
                      <div>
                        <Loader2 size={15} className="spin" />
                        <span>
                          {detail.phase === "warmup"
                            ? "预热中"
                            : detail.phase === "artifacts"
                              ? "生成预览与报告"
                              : stateLabel[detail.state]}{" "}
                          · {detail.completed} / {detail.total}
                        </span>
                        <b>
                          {Math.round(
                            (detail.completed / Math.max(detail.total, 1)) *
                              100,
                          )}
                          %
                        </b>
                      </div>
                      <div className="progress-track">
                        <i
                          style={{
                            width: `${(detail.completed / Math.max(detail.total, 1)) * 100}%`,
                          }}
                        />
                      </div>
                    </div>
                  )}
                  {view === "preview" ? (
                    <Viewer
                      task={detail}
                      record={selectedRecord}
                      nodeId={nodeId}
                      onError={handleError}
                    />
                  ) : (
                    <Performance task={detail} />
                  )}
                  {detail?.error && (
                    <div className="alert error">
                      <AlertCircle size={16} />
                      {detail.error}
                    </div>
                  )}
                  <section className="panel result-table-panel">
                    <div className="panel-title">
                      <div className="title-with-icon">
                        <FileText size={17} />
                        <h3>样本结果</h3>
                        <span className="count-pill">
                          {detail?.results?.length || 0}
                        </span>
                      </div>
                      <div className="export-actions">
                        <button
                          disabled={!detail?.results?.length}
                          onClick={() =>
                            detail &&
                            exportTask(detail.id, nodeId, "csv").catch(
                              handleError,
                            )
                          }
                        >
                          <Download size={14} />
                          CSV
                        </button>
                        <button
                          disabled={!detail}
                          onClick={() =>
                            detail &&
                            exportTask(detail.id, nodeId, "json").catch(
                              handleError,
                            )
                          }
                        >
                          JSON
                        </button>
                      </div>
                    </div>
                    <div className="table-toolbar">
                      <div className="search-field">
                        <input
                          aria-label="搜索样本"
                          placeholder="搜索文件或预测类别…"
                          value={resultSearch}
                          onChange={(e) => setResultSearch(e.target.value)}
                        />
                      </div>
                      <select
                        aria-label="结果状态"
                        value={resultFilter}
                        onChange={(e) => setResultFilter(e.target.value)}
                      >
                        <option value="all">全部状态</option>
                        <option value="succeeded">成功</option>
                        <option value="failed">失败</option>
                      </select>
                    </div>
                    {taskRows.length ? (
                      <div className="table-scroll samples-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>文件名称</th>
                              <th>预测结果</th>
                              <th>处理耗时</th>
                              <th>状态</th>
                            </tr>
                          </thead>
                          <tbody>
                            {taskRows.map((row) => (
                              <tr
                                key={row.sample_id}
                                className={
                                  selectedRecord?.sample_id === row.sample_id
                                    ? "selected-row"
                                    : ""
                                }
                                onClick={() => {
                                  setSampleId(row.sample_id);
                                  setView("preview");
                                }}
                              >
                                <td>
                                  <div className="file-cell">
                                    <ImageIcon size={15} />
                                    <span>{row.filename}</span>
                                    <small>#{Number(row.sample_id) + 1}</small>
                                  </div>
                                </td>
                                <td>
                                  {row.prediction ? (
                                    row.prediction.top_k
                                      ?.slice(0, 1)
                                      .map((i) => i.label)
                                      .join("") ||
                                    `${row.prediction.detections?.length || 0} 个目标`
                                  ) : (
                                    <span
                                      className="danger-text"
                                      title={row.error?.message}
                                    >
                                      处理失败
                                    </span>
                                  )}
                                </td>
                                <td className="mono">
                                  {number(row.timings_ms.sample_total_ms)}{" "}
                                  <small>ms</small>
                                </td>
                                <td>
                                  <span
                                    className={
                                      "result-status " +
                                      (row.status === "succeeded"
                                        ? ""
                                        : "failed")
                                    }
                                  >
                                    <i />
                                    {row.status === "succeeded"
                                      ? "成功"
                                      : "失败"}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="table-empty">
                        <ImageIcon size={23} />
                        <span>
                          {detail && !terminal.has(detail.state)
                            ? "正在执行测试，完成后汇总样本结果"
                            : "运行测试后，样本结果将显示在这里"}
                        </span>
                      </div>
                    )}
                  </section>
                  {detail?.logs && (
                    <details className="panel task-logs">
                      <summary>查看运行日志</summary>
                      <pre>{detail.logs}</pre>
                    </details>
                  )}
                </div>
              </div>
            </>
          )}

          {page === "models" && (
            <>
              <div className="list-toolbar">
                <div className="search-field">
                  <input
                    aria-label="搜索模型"
                    placeholder="搜索模型名称…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <span>{models.length} 个模型实例</span>
              </div>
              {models.length ? (
                <div className="model-grid">
                  {models
                    .filter((m) =>
                      m.name.toLowerCase().includes(search.toLowerCase()),
                    )
                    .map((model) => (
                      <section className="panel model-card" key={model.id}>
                        <div className="model-card-top">
                          <div className={"model-type-icon " + model.task}>
                            <Boxes size={23} />
                          </div>
                          <Badge
                            state={
                              model.state === "ready" && !canRunModel(model)
                                ? "unavailable"
                                : model.state
                            }
                          />
                        </div>
                        <h3>{model.name}</h3>
                        <p>
                          {model.model_id} ·{" "}
                          {model.task === "classification"
                            ? "图像分类"
                            : "目标检测"}
                        </p>
                        <dl>
                          <dt>权重大小</dt>
                          <dd>
                            {(model.weight.size / 1024 / 1024).toFixed(2)} MB
                          </dd>
                          <dt>类别映射</dt>
                          <dd>
                            {model.labels
                              ? model.labels.length + " 个类别"
                              : "使用类别编号"}
                          </dd>
                          <dt>SHA-256</dt>
                          <dd className="mono">
                            {model.weight.sha256.slice(0, 12)}…
                          </dd>
                        </dl>
                        {model.error && (
                          <p className="danger-text small-text">
                            {model.error}
                          </p>
                        )}
                        <div className="card-actions">
                          <button
                            className="button primary"
                            disabled={!canRunModel(model)}
                            onClick={() => {
                              setSelectedModel(model.id);
                              setPage("workbench");
                            }}
                          >
                            开始测试
                            <ArrowRight size={15} />
                          </button>
                          <button
                            className="icon-button"
                            title="删除模型实例（保留权重缓存）"
                            disabled={!!busy}
                            onClick={() =>
                              perform("删除模型", () =>
                                api("delete_model", {
                                  node_id: nodeId,
                                  id: model.id,
                                }),
                              )
                            }
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </section>
                    ))}
                </div>
              ) : (
                <section className="panel">
                  <Empty
                    title="添加你的第一个模型"
                    description="先准备插件运行环境，再导入与支持模型匹配的权重。"
                    action={
                      <button className="button primary" onClick={openModel}>
                        <Plus size={16} />
                        导入模型
                      </button>
                    }
                  />
                </section>
              )}
            </>
          )}

          {page === "plugins" && (
            <>
              <div className="section-caption">
                <Puzzle size={16} />
                <span>
                  支持模型由插件声明。每个节点、每个插件拥有一个独立的运行环境。
                </span>
              </div>
              <div className="plugin-grid">
                {plugins.map((plugin) => {
                  const installation = installations.find(
                    (i) => i.id === plugin.id,
                  );
                  const environmentState =
                    installation?.state === "ready" &&
                    installation.plugin_digest !== plugin.digest
                      ? "outdated"
                      : installation?.state;
                  return (
                    <section className="panel plugin-card" key={plugin.id}>
                      <div className="plugin-card-heading">
                        <div className="plugin-icon">
                          <Puzzle size={23} />
                        </div>
                        <div>
                          <h3>{plugin.manifest.name}</h3>
                          <p>v{plugin.manifest.version} · Python 插件</p>
                        </div>
                        {installation ? (
                          <Badge
                            state={environmentState || installation.state}
                          />
                        ) : (
                          <span className="badge neutral">未安装</span>
                        )}
                      </div>
                      <div className="supported-label">支持的模型</div>
                      <div className="model-tags">
                        {plugin.manifest.models.slice(0, 8).map((m) => (
                          <span key={m.id}>{m.name}</span>
                        ))}
                        {plugin.manifest.models.length > 8 && (
                          <span>
                            共 {plugin.manifest.models.length} 个配置 ·
                            导入时搜索
                          </span>
                        )}
                      </div>
                      <div className="plugin-runtime">
                        <Cpu size={16} />
                        <span>运行方案</span>
                        <strong>
                          {installation?.profile_id ||
                            plugin.manifest.runtime_profiles[0].id}
                        </strong>
                        <span className="runtime-python">
                          {installation?.python_version || "Python · uv 管理"}
                        </span>
                      </div>
                      {(installation?.error || installation?.last_error) && (
                        <p className="danger-text small-text">
                          {installation.error || installation.last_error}
                        </p>
                      )}
                      <div className="card-actions">
                        <button
                          className={
                            "button " +
                            (installation?.state === "ready" ? "" : "primary")
                          }
                          disabled={
                            !!busy || installation?.state === "preparing"
                          }
                          onClick={() =>
                            perform("准备插件环境", () =>
                              api("install_plugin", {
                                node_id: nodeId,
                                plugin_id: plugin.id,
                                profile_id:
                                  plugin.manifest.runtime_profiles[0].id,
                              }),
                            )
                          }
                        >
                          {installation?.state === "preparing" ? (
                            <Loader2 size={16} className="spin" />
                          ) : (
                            <RefreshCw size={16} />
                          )}{" "}
                          {installation?.state === "ready"
                            ? "修复运行环境"
                            : installation?.state === "preparing"
                              ? "正在准备…"
                              : "准备运行环境"}
                        </button>
                        {installation?.state === "ready" && (
                          <button
                            className="button subtle"
                            onClick={() =>
                              perform("卸载插件环境", () =>
                                api("uninstall_plugin", {
                                  node_id: nodeId,
                                  plugin_id: plugin.id,
                                }),
                              )
                            }
                          >
                            卸载环境
                          </button>
                        )}
                        <span className="muted small-text">
                          {plugin.manifest.models.length} 个模型
                        </span>
                      </div>
                      {installation?.logs && (
                        <details className="install-logs">
                          <summary>
                            安装日志{" "}
                            {installation.state === "preparing"
                              ? "· 持续更新"
                              : ""}
                          </summary>
                          <pre>{installation.logs}</pre>
                        </details>
                      )}
                    </section>
                  );
                })}
              </div>
              {!plugins.length && snapshot && (
                <section className="panel">
                  <Empty
                    icon={Puzzle}
                    title="没有可用插件"
                    description="导入包含 manifest.json、代码和锁文件的插件 ZIP 包。"
                  />
                </section>
              )}
            </>
          )}

          {page === "nodes" && (
            <div className="node-grid">
              <section className="panel node-card">
                <div className="node-card-heading">
                  <div className="node-icon">
                    <Cpu size={25} />
                  </div>
                  <Badge state="online" />
                </div>
                <h3>本机</h3>
                <p>
                  Local ·{" "}
                  {nodeId === "local"
                    ? snapshot?.node.platform
                    : "Windows / Linux"}
                </p>
                <div className="node-description">
                  直接使用当前电脑的 CPU
                  运行模型。环境由应用管理，模型与结果保存在用户目录。
                </div>
                <button
                  className="button wide"
                  disabled={!!busy}
                  onClick={() => setNodeId("local")}
                >
                  {nodeId === "local" ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <ArrowRight size={15} />
                  )}{" "}
                  {nodeId === "local" ? "当前节点" : "切换到本机"}
                </button>
              </section>
              {nodes
                .filter((n) => n.kind === "ssh")
                .map((n) => (
                  <section className="panel node-card" key={n.id}>
                    <div className="node-card-heading">
                      <div className="node-icon remote">
                        <Network size={25} />
                      </div>
                      <Badge state={n.status || "unconfigured"} />
                    </div>
                    <h3>{n.name}</h3>
                    <p className="mono">
                      {n.user}@{n.host}:{n.port}
                    </p>
                    <div className="node-description">
                      Linux · SSH / SFTP
                      <br />
                      {n.trusted
                        ? "主机指纹已核对"
                        : "首次连接前，请核对主机指纹"}
                    </div>
                    {n.last_error && (
                      <p className="danger-text small-text">{n.last_error}</p>
                    )}
                    <div className="node-card-actions">
                      {!n.trusted ? (
                        <button
                          className="button"
                          disabled={!!busy}
                          onClick={() =>
                            perform("扫描主机指纹", async () => {
                              setFingerprints(
                                await api("scan_node", { id: n.id }),
                              );
                              setFingerprintNode(n);
                              setModal("fingerprint");
                            })
                          }
                        >
                          <Fingerprint size={15} />
                          核对指纹
                        </button>
                      ) : (
                        <button
                          className="button"
                          disabled={!!busy}
                          onClick={() =>
                            perform("连接并部署节点", async () => {
                              await api("connect_node", { id: n.id });
                              setNotice("远程节点已通过连接与后台任务检查");
                            })
                          }
                        >
                          <RefreshCw size={15} />
                          检查并部署
                        </button>
                      )}
                      <button
                        className="button primary"
                        disabled={!!busy || n.status !== "online"}
                        onClick={() => {
                          setNodeId(n.id);
                          setPage("workbench");
                        }}
                      >
                        使用节点
                      </button>
                      <button
                        className="icon-button"
                        title="移除连接（不删除远端数据）"
                        disabled={!!busy}
                        onClick={() =>
                          perform("移除连接", async () => {
                            await api("remove_node", { id: n.id });
                            if (nodeId === n.id) setNodeId("local");
                          })
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </section>
                ))}
            </div>
          )}

          {page === "history" && (
            <section className="panel">
              <div className="panel-title">
                <h3>测试记录</h3>
                <span>最近 100 次 · {activeNode?.name}</span>
              </div>
              {tasks.length ? (
                <div className="table-scroll">
                  <table className="history-table">
                    <thead>
                      <tr>
                        <th></th>
                        <th>模型 / 任务</th>
                        <th>模式</th>
                        <th>样本</th>
                        <th>平均耗时</th>
                        <th>状态</th>
                        <th>创建时间</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {tasks.map((task) => (
                        <tr key={task.id}>
                          <td>
                            <input
                              aria-label={
                                "对比 " +
                                task.model_name +
                                " " +
                                task.id.slice(0, 6)
                              }
                              type="checkbox"
                              disabled={!terminal.has(task.state)}
                              checked={compareIds.includes(task.id)}
                              onChange={(e) =>
                                setCompareIds(
                                  e.target.checked
                                    ? [...compareIds.slice(-2), task.id]
                                    : compareIds.filter((id) => id !== task.id),
                                )
                              }
                            />
                          </td>
                          <td>
                            <strong>{task.model_name}</strong>
                            <small className="row-subtitle mono">
                              {task.id.slice(0, 10)}
                            </small>
                          </td>
                          <td>
                            {task.mode === "benchmark"
                              ? "性能"
                              : task.mode === "single"
                                ? "单图"
                                : "批量"}
                          </td>
                          <td>
                            {task.completed} / {task.total}
                          </td>
                          <td className="mono">
                            {number(task.metrics?.stages.sample_total_ms?.mean)}{" "}
                            ms
                          </td>
                          <td>
                            <Badge state={task.state} />
                          </td>
                          <td>{date(task.created_at)}</td>
                          <td>
                            <button
                              className="text-button"
                              onClick={() => inspect(task)}
                            >
                              查看
                              <ChevronRight size={14} />
                            </button>
                            {terminal.has(task.state) && (
                              <button
                                className="text-button retry-button"
                                disabled={!!busy}
                                onClick={() =>
                                  perform("按配置重测", async () => {
                                    const value = await api<Task>(
                                      "retry_task",
                                      { node_id: nodeId, task_id: task.id },
                                    );
                                    setTaskId(value.id);
                                    setPage("workbench");
                                    setView("preview");
                                  })
                                }
                              >
                                重测
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty
                  icon={History}
                  title="还没有测试记录"
                  description="完成一次测试后，配置、样本结果和性能统计会保存在这里。"
                  action={
                    <button
                      className="button"
                      onClick={() => setPage("workbench")}
                    >
                      前往工作台
                      <ArrowRight size={15} />
                    </button>
                  }
                />
              )}
            </section>
          )}
          <footer className="app-footer">
            <span>ModelDock {APP_VERSION}</span>
            <span>
              <i className="status-dot" />
              {nodeId === "local" ? "本机执行" : "SSH 加密连接"} ·
              每个插件独立运行环境
            </span>
            <span>{snapshot?.node.platform || "等待连接"}</span>
          </footer>
        </main>
      </div>
      {busy && (
        <div className="busy-indicator" role="status">
          <Loader2 className="spin" size={17} />
          {busy}…
        </div>
      )}
      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeModal();
          }}
        >
          <section
            className={"modal " + (modal === "compare" ? "compare-modal" : "")}
            role="dialog"
            aria-modal="true"
            aria-label={
              {
                model: "导入模型",
                node: "添加 SSH 节点",
                help: "使用说明",
                fingerprint: "核对主机指纹",
                compare: "测试结果对比",
              }[modal]
            }
          >
            <div className="modal-heading">
              <h2>
                {
                  {
                    model: "导入模型",
                    node: "添加 SSH 节点",
                    help: "开始使用 ModelDock",
                    fingerprint: "核对 SSH 主机指纹",
                    compare: "测试结果对比",
                  }[modal]
                }
              </h2>
              <button
                className="icon-button"
                aria-label="关闭对话框"
                disabled={!!busy && !modelDownloading}
                onClick={closeModal}
              >
                <X size={19} />
              </button>
            </div>
            {error && (
              <div className="alert error" role="alert">
                <AlertCircle size={16} />
                <span>{error}</span>
              </div>
            )}
            {modal === "model" && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  createModel();
                }}
              >
                <p className="muted">
                  选择插件支持的模型，导入权重并执行一次加载检查。
                </p>
                <div
                  className={
                    "two-fields " +
                    ((formPlugin?.manifest.models.length || 0) > 20
                      ? "catalog-fields"
                      : "")
                  }
                >
                  <label className="field">
                    <span>模型插件</span>
                    <select
                      aria-label="模型插件"
                      disabled={!!busy}
                      value={modelPlugin}
                      onChange={(e) => setPlugin(e.target.value)}
                    >
                      {plugins.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.manifest.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <ModelChooser
                    key={modelPlugin}
                    models={formPlugin?.manifest.models || []}
                    value={modelType}
                    disabled={!!busy}
                    onChange={(id) => {
                      if (["url", "pretrained"].includes(modelSource)) {
                        setWeight("");
                        setLabels("");
                      }
                      setModelType(id);
                      const next = formPlugin?.manifest.models.find(
                        (m) => m.id === id,
                      );
                      setModelParams({
                        ...defaults(next),
                        ...(modelSource === "pretrained"
                          ? next?.extensions?.modeldock?.pretrained?.parameters
                          : {}),
                      });
                    }}
                  />
                </div>
                {!readyForPlugin(modelPlugin) && (
                  <div className="alert warning">
                    <AlertCircle size={16} />
                    <span>请先在插件管理中准备此插件的运行环境。</span>
                    <button
                      type="button"
                      disabled={!!busy}
                      onClick={() => {
                        setModal(null);
                        setPage("plugins");
                      }}
                    >
                      前往插件管理
                    </button>
                  </div>
                )}
                <label className="field">
                  <span>实例名称</span>
                  <input
                    aria-label="实例名称"
                    placeholder="例如：产品分类 · v1"
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                  />
                </label>
                <label className="field">
                  <span>权重来源</span>
                  <select
                    aria-label="权重来源"
                    disabled={!!busy}
                    value={modelSource}
                    onChange={(e) => {
                      setModelSource(e.target.value);
                      if (e.target.value === "pretrained")
                        setModelParams({
                          ...modelParams,
                          ...formSpec?.extensions?.modeldock?.pretrained
                            ?.parameters,
                        });
                      setWeight("");
                      setLabels("");
                    }}
                  >
                    <option value="local">
                      {nodeId === "local" ? "本机文件" : "上传本机文件"}
                    </option>
                    {nodeId !== "local" && (
                      <option value="remote">远端已有路径</option>
                    )}
                    <option value="url">URL 下载</option>
                    {formSpec?.extensions?.modeldock?.pretrained && (
                      <option value="pretrained">官方预训练权重</option>
                    )}
                  </select>
                </label>
                {["url", "pretrained"].includes(modelSource) ? (
                  <WeightDownload
                    key={`${nodeId}:${modelPlugin}:${modelType}:${modelSource}`}
                    nodeId={nodeId}
                    pluginId={modelPlugin}
                    modelId={modelType}
                    pretrained={modelSource === "pretrained"}
                    onFile={(path, labelPath) => {
                      setWeight(path);
                      if (labelPath) setLabels(labelPath);
                    }}
                    onBusy={(message) => {
                      setModelDownloading(!!message);
                      setBusy(message);
                    }}
                  />
                ) : (
                  <label className="field">
                    <span>
                      {(formSpec?.weight_formats || ["onnx"])
                        .join(" / ")
                        .toUpperCase()}{" "}
                      权重文件
                    </span>
                    <div className="path-input">
                      <input
                        required
                        aria-label="权重文件"
                        placeholder={
                          modelSource === "remote"
                            ? "/data/model.onnx"
                            : "选择 .onnx 文件"
                        }
                        value={weight}
                        onChange={(e) => setWeight(e.target.value)}
                      />
                      {modelSource === "local" && (
                        <button
                          type="button"
                          aria-label="选择权重文件"
                          onClick={() =>
                            pickFiles({
                              extensions: formSpec?.weight_formats || ["onnx"],
                            })
                              .then((p) => p[0] && setWeight(p[0]))
                              .catch(handleError)
                          }
                        >
                          <FolderOpen size={17} />
                        </button>
                      )}
                    </div>
                  </label>
                )}
                {formSpec?.extensions?.modeldock?.pretrained &&
                  modelSource === "pretrained" && (
                    <p className="muted small-text">
                      {formSpec.extensions.modeldock!.pretrained!.label_set ||
                        "预训练权重"}{" "}
                      · 权重许可：
                      {formSpec.extensions.modeldock!.pretrained!.license}
                      。不同权重的使用条件以发布方为准。
                    </p>
                  )}
                <label className="field">
                  <span>
                    类别文件 <small>可选 · UTF-8，每行一个类别</small>
                  </span>
                  <div className="path-input">
                    <input
                      aria-label="类别文件"
                      placeholder={
                        nodeId !== "local" && modelSource !== "local"
                          ? "/data/labels.txt（可选）"
                          : "未提供时使用类别编号"
                      }
                      value={labels}
                      onChange={(e) => setLabels(e.target.value)}
                    />
                    {(modelSource === "local" || nodeId === "local") && (
                      <button
                        type="button"
                        aria-label="选择类别文件"
                        onClick={() =>
                          pickFiles({ extensions: ["txt"] })
                            .then((p) => p[0] && setLabels(p[0]))
                            .catch(handleError)
                        }
                      >
                        <FolderOpen size={17} />
                      </button>
                    )}
                  </div>
                </label>
                <div className="two-fields">
                  <ParamsFields
                    spec={formSpec}
                    value={modelParams}
                    disabledKeys={
                      modelSource === "pretrained"
                        ? Object.keys(
                            formSpec?.extensions?.modeldock?.pretrained
                              ?.parameters || {},
                          )
                        : []
                    }
                    onChange={setModelParams}
                  />
                </div>
                <div className="modal-footer">
                  <button
                    type="button"
                    className="button"
                    disabled={!!busy && !modelDownloading}
                    onClick={closeModal}
                  >
                    取消
                  </button>
                  <button
                    className="button primary"
                    type="submit"
                    disabled={!!busy || !weight || !readyForPlugin(modelPlugin)}
                  >
                    {busy ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <CheckCircle2 size={16} />
                    )}
                    验证并导入
                  </button>
                </div>
              </form>
            )}
            {modal === "node" && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  perform("保存节点", async () => {
                    await api("add_node", nodeForm);
                    setModal(null);
                    setNotice("节点已添加，请核对主机指纹");
                  });
                }}
              >
                <p className="muted">
                  节点需要 Linux x86_64、Python
                  3.11+，并允许用户级后台进程。使用密钥文件或系统 SSH agent
                  认证。
                </p>
                <label className="field">
                  <span>节点名称</span>
                  <input
                    aria-label="节点名称"
                    placeholder="例如：实验室 GPU 主机"
                    value={nodeForm.name}
                    onChange={(e) =>
                      setNodeForm({ ...nodeForm, name: e.target.value })
                    }
                  />
                </label>
                <div className="host-fields">
                  <label className="field">
                    <span>主机地址</span>
                    <input
                      required
                      aria-label="主机地址"
                      value={nodeForm.host}
                      onChange={(e) =>
                        setNodeForm({ ...nodeForm, host: e.target.value })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>端口</span>
                    <input
                      required
                      type="number"
                      min="1"
                      max="65535"
                      value={nodeForm.port}
                      onChange={(e) =>
                        setNodeForm({
                          ...nodeForm,
                          port: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                </div>
                <label className="field">
                  <span>SSH 用户</span>
                  <input
                    required
                    aria-label="SSH 用户"
                    value={nodeForm.user}
                    onChange={(e) =>
                      setNodeForm({ ...nodeForm, user: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>
                    私钥文件 <small>可选，留空使用 SSH agent</small>
                  </span>
                  <input
                    placeholder="私钥只由系统 SSH 读取，不上传"
                    value={nodeForm.key_path}
                    onChange={(e) =>
                      setNodeForm({ ...nodeForm, key_path: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>远端工作目录</span>
                  <input
                    required
                    value={nodeForm.work_root}
                    onChange={(e) =>
                      setNodeForm({ ...nodeForm, work_root: e.target.value })
                    }
                  />
                </label>
                <div className="modal-footer">
                  <button
                    type="button"
                    className="button"
                    onClick={() => setModal(null)}
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={!!busy}
                  >
                    <Plus size={16} />
                    添加节点
                  </button>
                </div>
              </form>
            )}
            {modal === "fingerprint" && (
              <>
                <p className="muted">
                  请通过可信渠道核对 {fingerprintNode?.host}{" "}
                  的主机指纹。应用会严格验证后续连接中的主机密钥。
                </p>
                {fingerprints.map((f) => (
                  <div className="fingerprint" key={f.fingerprint}>
                    <span>{f.type}</span>
                    <code>{f.fingerprint}</code>
                  </div>
                ))}
                <div className="modal-footer">
                  <button className="button" onClick={() => setModal(null)}>
                    取消
                  </button>
                  <button
                    className="button primary"
                    disabled={!!busy}
                    onClick={() =>
                      perform("保存主机指纹", async () => {
                        await api("trust_node", {
                          id: fingerprintNode?.id,
                          fingerprints: fingerprints.map((f) => f.fingerprint),
                        });
                        setModal(null);
                        setNotice("主机指纹已保存，可检查并部署节点");
                      })
                    }
                  >
                    <Fingerprint size={16} />
                    已核对，信任这些指纹
                  </button>
                </div>
              </>
            )}
            {modal === "compare" && (
              <>
                <p className="muted">
                  不同权重、输入清单、参数或环境的结果不代表相同条件下的比较。
                </p>
                <div className="comparison-grid">
                  {comparison.map((task) => (
                    <section className="panel" key={task.id}>
                      <h3>{task.model_name}</h3>
                      <Badge state={task.state} />
                      <strong className="comparison-number">
                        {number(task.metrics?.stages.sample_total_ms?.mean)}
                        <small> ms</small>
                      </strong>
                      <dl className="conditions">
                        <dt>P95</dt>
                        <dd>
                          {number(task.metrics?.stages.sample_total_ms?.p95)} ms
                        </dd>
                        <dt>吞吐量</dt>
                        <dd>{number(task.metrics?.throughput)} 张/秒</dd>
                        <dt>成功 / 失败</dt>
                        <dd>
                          {task.metrics?.count} / {task.metrics?.failed}
                        </dd>
                        <dt>预热 / 正式</dt>
                        <dd>
                          {task.report?.warmup} / {task.report?.iterations}
                        </dd>
                        <dt>线程</dt>
                        <dd>{task.report?.threads}</dd>
                        <dt>权重摘要</dt>
                        <dd className="mono">
                          {task.report?.weight_sha256?.slice(0, 12)}
                        </dd>
                        <dt>输入摘要</dt>
                        <dd className="mono">
                          {task.report?.input_manifest_digest?.slice(0, 12)}
                        </dd>
                        <dt>环境</dt>
                        <dd className="mono">
                          {task.report?.environment_fingerprint?.slice(0, 12)}
                        </dd>
                      </dl>
                    </section>
                  ))}
                </div>
                {new Set(
                  comparison.map((t) =>
                    JSON.stringify([
                      t.report?.input_manifest_digest,
                      t.report?.threads,
                      t.report?.iterations,
                      t.report?.warmup,
                      t.report?.parameters,
                      t.report?.environment_fingerprint,
                    ]),
                  ),
                ).size > 1 && (
                  <div className="alert warning">
                    <AlertCircle size={17} />
                    检测到测试条件不同，请结合配置差异解读结果。
                  </div>
                )}
              </>
            )}
            {modal === "help" && (
              <div className="help-content">
                <div className="help-step">
                  <b>01</b>
                  <div>
                    <h3>准备插件环境</h3>
                    <p>
                      在插件管理中安装参考插件，uv 会按锁文件准备 Python
                      与依赖。
                    </p>
                  </div>
                </div>
                <div className="help-step">
                  <b>02</b>
                  <div>
                    <h3>导入你的模型</h3>
                    <p>
                      分类模型采用 RGB 中心裁剪和标准归一化。YOLO 支持 640×640
                      输入、[1,4+C,N] 输出、不含内置 NMS 的检测导出。
                    </p>
                  </div>
                </div>
                <div className="help-step">
                  <b>03</b>
                  <div>
                    <h3>运行与查看</h3>
                    <p>
                      选择图片或目录，查看分类结果、检测框、耗时与导出报告。性能模式先预热，再执行正式测量。
                    </p>
                  </div>
                </div>
                <div className="help-note">
                  当前参考插件使用
                  CPU、batch=1。GPU、视频和带标注的精度评估尚未开放。SSH
                  节点需要已启用的 OpenSSH 客户端。
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
