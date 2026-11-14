export type Params = Record<string, string | number | boolean | object>;
export interface ModelSpec {
  weight_formats?: string[];
  id: string;
  name: string;
  task: string;
  parameter_schema: string;
  parameter_schema_data?: { properties: Record<string, any> };
  config_data?: { input_size: number[] };
  capabilities?: { timing_mode: string };
  extensions?: {
    modeldock?: {
      family?: string;
      pretrained?: {
        parameters?: Params;
        label_set?: string;
        license?: string;
        homepage?: string;
      };
    };
  };
}
export interface Plugin {
  id: string;
  digest: string;
  path: string;
  manifest: {
    name: string;
    version: string;
    models: ModelSpec[];
    runtime_profiles: { id: string; providers: string[] }[];
  };
}
export interface Installation {
  plugin_digest: string;
  id: string;
  state: string;
  profile_id: string;
  python_version?: string;
  fingerprint?: string;
  error?: string;
  last_error?: string;
  logs?: string;
}
export interface Model {
  id: string;
  name: string;
  plugin_id: string;
  model_id: string;
  task: string;
  state: string;
  parameters: Params;
  labels?: string[];
  weight: { sha256: string; size: number; path: string };
  error?: string;
  validation?: { parameters: Params; providers?: string[] | null };
}
export interface Node {
  id: string;
  name: string;
  kind: string;
  host?: string;
  user?: string;
  port?: number;
  trusted?: boolean;
  status?: string;
  last_error?: string;
  scanned_keys?: { type: string; fingerprint: string }[];
}
export interface Stage {
  mean: number;
  p50: number;
  p95: number;
}
export interface Metrics {
  count: number;
  failed: number;
  throughput: number;
  load_ms: number;
  processing_wall_ms: number;
  stages: Record<string, Stage | null>;
}
export interface PredictionItem {
  class_id: number;
  label: string;
  score: number;
  bbox_xyxy?: number[];
}
export interface Prediction {
  artifacts?: { artifact_id: string; title: string; media_type: string }[];
  task: string;
  image_size: { width: number; height: number };
  top_k?: PredictionItem[];
  detections?: PredictionItem[];
}
export interface Result {
  sample_id: string;
  filename: string;
  status: string;
  prediction: Prediction | null;
  error?: { message: string };
  timings_ms: Record<string, number | null>;
}
export interface Task {
  id: string;
  state: string;
  mode: string;
  model_id: string;
  model_name: string;
  task: string;
  total: number;
  completed: number;
  failed: number;
  created_at: number;
  started_at?: number;
  finished_at?: number;
  phase?: string;
  error?: string;
  metrics?: Metrics;
  results?: Result[];
  logs?: string;
  report?: Record<string, any>;
  resources?: { rss_mb: number; elapsed: number }[];
}
export interface Snapshot {
  version: string;
  node: {
    id: string;
    name: string;
    platform: string;
    cpu: string;
    data_dir: string;
  };
  nodes: Node[];
  plugins: Plugin[];
  installations: Installation[];
  models: Model[];
  tasks: Task[];
}
export const terminal = new Set([
  "SUCCEEDED",
  "FAILED",
  "PARTIAL_FAILED",
  "CANCELLED",
]);
export const stateLabel: Record<string, string> = {
  unavailable: "环境或模型未就绪",
  outdated: "需要更新",
  uninstalling: "卸载中",
  QUEUED: "排队中",
  PREPARING: "准备中",
  RUNNING: "运行中",
  CANCEL_REQUESTED: "正在停止",
  SUCCEEDED: "已完成",
  FAILED: "失败",
  PARTIAL_FAILED: "部分失败",
  CANCELLED: "已取消",
  ready: "已就绪",
  preparing: "准备环境",
  failed: "准备失败",
  invalid: "加载失败",
  validating: "检查中",
  online: "在线",
  unconfigured: "未配置",
  trusted: "指纹已信任",
  unreachable: "不可达",
};
