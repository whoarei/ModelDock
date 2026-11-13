import type { Task } from "./types";
export function number(value: number | undefined | null, digits = 2) {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}
export function SparkChart({
  values,
  color = "#109b8e",
  unit = "ms",
}: {
  values: number[];
  color?: string;
  unit?: string;
}) {
  if (!values.length) return <div className="chart-empty">暂无可绘制数据</div>;
  const min = Math.min(...values),
    max = Math.max(...values),
    range = max - min || Math.max(max * 0.1, 1);
  const points = values
    .map(
      (v, i) =>
        `${38 + (i / Math.max(values.length - 1, 1)) * 522},${136 - ((v - min) / range) * 105}`,
    )
    .join(" ");
  return (
    <svg
      viewBox="0 0 580 170"
      className="chart"
      role="img"
      aria-label={"趋势图，" + values.length + " 个样本"}
    >
      {[31, 83, 136].map((y, i) => (
        <g key={y}>
          <line
            x1="38"
            x2="560"
            y1={y}
            y2={y}
            stroke="#e8edf0"
            strokeDasharray="4 4"
          />
          <text x="2" y={y + 4}>
            {number(max - (i * (max - min)) / 2, 1)}
          </text>
        </g>
      ))}
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      {values.length === 1 && <circle cx="38" cy="136" r="4" fill={color} />}
      <text x="38" y="160">
        1
      </text>
      <text x="535" y="160">
        {values.length}
      </text>
      <text x="8" y="15">
        {unit}
      </text>
    </svg>
  );
}
export function Histogram({ values }: { values: number[] }) {
  if (!values.length)
    return <div className="chart-empty">完成测试后查看耗时分布</div>;
  const min = Math.min(...values),
    max = Math.max(...values),
    step = (max - min || 1) / 10,
    bins = Array(10).fill(0);
  for (const value of values)
    bins[Math.min(9, Math.floor((value - min) / step))]++;
  const highest = Math.max(...bins);
  return (
    <svg
      viewBox="0 0 580 170"
      className="chart"
      role="img"
      aria-label="样本耗时直方图"
    >
      <line x1="35" x2="560" y1="136" y2="136" stroke="#dfe7eb" />
      {bins.map((count, i) => (
        <g key={i}>
          <rect
            x={40 + i * 51}
            y={136 - (count / highest) * 105}
            width="36"
            height={(count / highest) * 105}
            rx="4"
            fill={i < 6 ? "#65c8bd" : "#149b8e"}
          />
          {count > 0 && (
            <text
              x={58 + i * 51}
              y={130 - (count / highest) * 105}
              textAnchor="middle"
            >
              {count}
            </text>
          )}
        </g>
      ))}
      <text x="38" y="160">
        {number(min)} ms
      </text>
      <text x="495" y="160">
        {number(max)} ms
      </text>
    </svg>
  );
}
export function Performance({ task }: { task: Task | null }) {
  const metrics = task?.metrics;
  const values = (task?.results || [])
    .filter((r) => r.status === "succeeded")
    .map((r) => r.timings_ms.sample_total_ms)
    .filter((v): v is number => v != null);
  const stages = [
    ["decode_ms", "读取 / 解码"],
    ["preprocess_ms", "预处理"],
    ["inference_ms", "模型推理"],
    ["postprocess_ms", "后处理"],
  ];
  const total = stages.reduce(
    (sum, [key]) => sum + (metrics?.stages[key]?.mean || 0),
    0,
  );
  return (
    <>
      <div className="kpi-grid compact">
        {[
          ["平均处理耗时", number(metrics?.stages.sample_total_ms?.mean), "ms"],
          ["P95 处理耗时", number(metrics?.stages.sample_total_ms?.p95), "ms"],
          ["处理吞吐量", number(metrics?.throughput), "张 / 秒"],
          ["成功样本", metrics ? String(metrics.count) : "—", "次执行"],
        ].map(([title, value, unit]) => (
          <div className="kpi" key={title}>
            <span>{title}</span>
            <strong>
              {value}
              <small>{unit}</small>
            </strong>
          </div>
        ))}
      </div>
      <div className="two-charts">
        <section className="panel">
          <div className="panel-title">
            <h3>逐样本处理耗时</h3>
            <span>实际测量 · ms</span>
          </div>
          <SparkChart values={values} />
        </section>
        <section className="panel">
          <div className="panel-title">
            <h3>耗时分布</h3>
            <span>{values.length} 次成功执行</span>
          </div>
          <Histogram values={values} />
        </section>
      </div>
      <div className="two-charts">
        <section className="panel">
          <div className="panel-title">
            <h3>处理阶段</h3>
            <span>平均耗时</span>
          </div>
          <div className="stages">
            {stages.map(([key, label], index) => (
              <div className="stage" key={key}>
                <span>{label}</span>
                <div>
                  <i
                    style={{
                      width: total
                        ? `${((metrics?.stages[key]?.mean || 0) / total) * 100}%`
                        : "0%",
                      background: ["#9bc8e5", "#9daae2", "#10a391", "#b9c4cd"][
                        index
                      ],
                    }}
                  />
                </div>
                <b>
                  {metrics?.stages[key]
                    ? number(metrics.stages[key]?.mean) + " ms"
                    : "未提供"}
                </b>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">
            <h3>测试条件</h3>
            <span>随报告保存</span>
          </div>
          <dl className="conditions">
            <dt>运行方案</dt>
            <dd>{task?.report?.profile || "—"}</dd>
            <dt>批大小 / 线程</dt>
            <dd>
              {task?.report
                ? `${task.report.batch_size} / ${task.report.threads}`
                : "—"}
            </dd>
            <dt>正式 / 预热</dt>
            <dd>
              {task?.report
                ? `${task.report.iterations} / ${task.report.warmup}`
                : "—"}
            </dd>
            <dt>统计口径</dt>
            <dd>不含预热、上传下载及预览生成</dd>
            <dt>精度评估</dt>
            <dd>未评估 · 当前无标注评估流程</dd>
          </dl>
        </section>
      </div>
      {task?.resources?.length ? (
        <section className="panel">
          <div className="panel-title">
            <h3>工作进程内存</h3>
            <span>RSS 采样 · MB</span>
          </div>
          <SparkChart
            values={task.resources.map((r) => r.rss_mb)}
            unit="MB"
            color="#7183cc"
          />
        </section>
      ) : null}
    </>
  );
}
