import { useEffect, useState } from "react";
import {
  Image as ImageIcon,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Download,
  Box,
  BarChart3,
  AlertCircle,
} from "lucide-react";
import { api, saveBlob } from "./api";
import { number } from "./charts";
import type { Task, Result, PredictionItem } from "./types";
const colors = [
  "#25c6ab",
  "#72a8ff",
  "#f5b85c",
  "#db8eea",
  "#f47785",
  "#7ad4ed",
];
export default function Viewer({
  task,
  record,
  nodeId,
  onError,
}: {
  task: Task | null;
  record: Result | null;
  nodeId: string;
  onError: (e: unknown) => void;
}) {
  const [image, setImage] = useState<string | null>(null),
    [zoom, setZoom] = useState(1),
    [offset, setOffset] = useState({ x: 0, y: 0 }),
    [overlay, setOverlay] = useState(true),
    [active, setActive] = useState<number | null>(null),
    [classId, setClassId] = useState("all"),
    [confidence, setConfidence] = useState(0);
  const [drag, setDrag] = useState<{
    x: number;
    y: number;
    ox: number;
    oy: number;
  } | null>(null);
  const [attachment, setAttachment] = useState<{
    url: string;
    title: string;
  } | null>(null);
  const prediction = record?.prediction;
  const items = prediction?.detections || prediction?.top_k || [];
  const savedThreshold =
    prediction?.task === "detection"
      ? task?.report?.parameters?.confidence || 0
      : 0;
  useEffect(() => {
    let live = true;
    setImage(null);
    setAttachment(null);
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    setActive(null);
    setClassId("all");
    setConfidence(savedThreshold);
    if (task && record?.status === "succeeded")
      api("preview", {
        node_id: nodeId,
        task_id: task.id,
        sample_id: record.sample_id,
      })
        .then((r) => {
          if (live) setImage(r.url);
        })
        .catch(onError);
    return () => {
      live = false;
    };
  }, [task?.id, record?.sample_id, record?.status, nodeId, task?.state]);
  const filtered = items
    .map((item, index) => ({ item, index }))
    .filter(
      ({ item }) =>
        (classId === "all" || item.class_id === Number(classId)) &&
        item.score >= confidence,
    );
  async function exportImage() {
    if (!image || !prediction) return;
    const img = new window.Image();
    img.src = image;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, 0, 0);
    const sx = canvas.width / prediction.image_size.width,
      sy = canvas.height / prediction.image_size.height;
    for (const { item, index } of filtered) {
      const color = colors[item.class_id % colors.length];
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 3;
      ctx.font = "16px sans-serif";
      if (item.bbox_xyxy) {
        const [x1, y1, x2, y2] = item.bbox_xyxy;
        ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
        ctx.fillText(
          `${item.label} ${(item.score * 100).toFixed(1)}%`,
          x1 * sx + 4,
          Math.max(20, y1 * sy - 6),
        );
      } else {
        ctx.fillStyle = "rgba(10,18,25,.78)";
        ctx.fillRect(8, 8 + index * 28, 300, 26);
        ctx.fillStyle = color;
        ctx.fillText(
          `${item.label} ${(item.score * 100).toFixed(1)}%`,
          16,
          27 + index * 28,
        );
      }
    }
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/png"),
    );
    if (blob)
      await saveBlob(
        blob,
        "modeldock-" + (record?.filename || "result") + ".png",
      );
  }
  return (
    <section className="panel viewer-panel">
      <div className="panel-title">
        <div className="title-with-icon">
          <ImageIcon size={17} />
          <h3>效果预览</h3>
        </div>
        <div className="segmented small">
          <button
            className={!overlay ? "selected" : ""}
            onClick={() => setOverlay(false)}
          >
            原图
          </button>
          <button
            className={overlay ? "selected" : ""}
            onClick={() => setOverlay(true)}
          >
            预测结果
          </button>
        </div>
      </div>
      <div className={"viewer-body " + (record ? "has-result" : "")}>
        <div
          className="viewport"
          onPointerDown={(e) => {
            if (!image) return;
            setDrag({ x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y });
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (drag)
              setOffset({
                x: drag.ox + e.clientX - drag.x,
                y: drag.oy + e.clientY - drag.y,
              });
          }}
          onPointerUp={() => setDrag(null)}
          onPointerCancel={() => setDrag(null)}
        >
          {image && prediction ? (
            <div
              className="image-stage"
              style={{
                transform: `translate(${offset.x}px,${offset.y}px) scale(${zoom})`,
              }}
            >
              <img src={image} alt={record?.filename} />
              {overlay && prediction.task === "detection" && (
                <svg
                  viewBox={`0 0 ${prediction.image_size.width} ${prediction.image_size.height}`}
                  preserveAspectRatio="xMidYMid meet"
                  aria-label="检测框"
                >
                  {filtered.map(({ item, index }) => {
                    const [x1, y1, x2, y2] = item.bbox_xyxy!;
                    const font = Math.max(prediction.image_size.width / 45, 16);
                    const label = `${item.label} ${(item.score * 100).toFixed(0)}%`;
                    return (
                      <g
                        key={index}
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={() =>
                          setActive(active === index ? null : index)
                        }
                        className={active === index ? "box-active" : ""}
                        style={{
                          opacity:
                            active === null || active === index ? 1 : 0.35,
                        }}
                      >
                        <rect
                          x={x1}
                          y={y1}
                          width={x2 - x1}
                          height={y2 - y1}
                          fill="transparent"
                          stroke={colors[item.class_id % colors.length]}
                          strokeWidth={Math.max(
                            2,
                            prediction.image_size.width / 350,
                          )}
                        />
                        <rect
                          x={x1}
                          y={Math.max(0, y1 - font * 1.4)}
                          width={label.length * font * 0.66 + 12}
                          height={font * 1.4}
                          rx="3"
                          fill={colors[item.class_id % colors.length]}
                        />
                        <text
                          x={x1 + 6}
                          y={Math.max(font, y1 - font * 0.3)}
                          fill="#071b20"
                          fontSize={font}
                          fontWeight="600"
                        >
                          {label}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
            </div>
          ) : (
            <div className="preview-empty">
              {record?.status === "failed" ? (
                <>
                  <AlertCircle size={34} />
                  <strong>这张图片未完成测试</strong>
                  <p>{record.error?.message}</p>
                </>
              ) : (
                <>
                  <div className="empty-illustration">
                    <div />
                    <ImageIcon size={30} />
                    <i />
                  </div>
                  <strong>
                    {task ? "选择一个已完成的样本" : "等待你的第一个测试"}
                  </strong>
                  <p>
                    {task
                      ? "测试完成后，点击下方结果查看图片与预测。"
                      : "导入模型与图片，在这里查看模型的真实输出。"}
                  </p>
                  <span>分类结果 · 检测框 · 交互预览</span>
                </>
              )}
            </div>
          )}
          {image && (
            <div className="image-filename">
              {record?.filename}
              <span>
                {prediction?.image_size.width} × {prediction?.image_size.height}
              </span>
            </div>
          )}
          <div
            className="viewer-tools"
            onPointerDown={(e) => e.stopPropagation()}
          >
            <button
              aria-label="缩小"
              disabled={!image}
              onClick={() => setZoom(Math.max(0.25, zoom - 0.25))}
            >
              <ZoomOut size={17} />
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button
              aria-label="放大"
              disabled={!image}
              onClick={() => setZoom(Math.min(4, zoom + 0.25))}
            >
              <ZoomIn size={17} />
            </button>
            <i />
            <button
              aria-label="适应窗口"
              disabled={!image}
              onClick={() => {
                setZoom(1);
                setOffset({ x: 0, y: 0 });
              }}
            >
              <Maximize2 size={16} />
            </button>
            <i />
            <button
              aria-label="导出结果图片"
              disabled={!image}
              onClick={() => exportImage().catch(onError)}
            >
              <Download size={16} />
            </button>
          </div>
        </div>
        {record?.status === "succeeded" && prediction && (
          <aside className="prediction-list">
            <div className="prediction-heading">
              {prediction.task === "detection" ? (
                <Box size={16} />
              ) : (
                <BarChart3 size={16} />
              )}
              <strong>
                {prediction.task === "detection" ? "检测结果" : "Top-K 预测"}
              </strong>
              <span>{filtered.length}</span>
            </div>
            {prediction.task === "detection" && (
              <div className="filters">
                <select
                  aria-label="类别筛选"
                  value={classId}
                  onChange={(e) => {
                    setClassId(e.target.value);
                    setActive(null);
                  }}
                >
                  <option value="all">全部类别</option>
                  {Array.from(
                    new Map(items.map((i) => [i.class_id, i.label])).entries(),
                  ).map(([id, label]) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
                <label>
                  显示置信度 <b>{Math.round(confidence * 100)}%</b>
                  <input
                    aria-label="显示置信度"
                    type="range"
                    min={savedThreshold}
                    max="1"
                    step="0.01"
                    value={confidence}
                    onChange={(e) => setConfidence(Number(e.target.value))}
                  />
                </label>
              </div>
            )}
            <div className="prediction-items">
              {filtered.length ? (
                filtered.map(({ item, index }) => (
                  <button
                    key={index}
                    className={
                      "prediction-item " + (active === index ? "active" : "")
                    }
                    onClick={() => setActive(active === index ? null : index)}
                  >
                    <div>
                      <span
                        className="class-color"
                        style={{
                          background: colors[item.class_id % colors.length],
                        }}
                      />
                      <strong>{item.label}</strong>
                      <b>
                        {(item.score * 100).toFixed(1)}
                        <small>%</small>
                      </b>
                    </div>
                    <div className="score-track">
                      <i
                        style={{
                          width: `${item.score * 100}%`,
                          background: colors[item.class_id % colors.length],
                        }}
                      />
                    </div>
                    {item.bbox_xyxy && (
                      <small className="box-coordinates">
                        {item.bbox_xyxy.map((v) => Math.round(v)).join(" , ")}
                      </small>
                    )}
                  </button>
                ))
              ) : (
                <p className="muted pad">当前没有符合条件的目标</p>
              )}
            </div>
            <div className="prediction-footer">
              {prediction.task === "detection"
                ? "原图坐标 · 类别颜色固定"
                : "置信度表示模型输出概率"}
              <span>
                处理耗时 {number(record.timings_ms.sample_total_ms)} ms
              </span>
              {prediction.artifacts?.map((artifact) => (
                <button
                  key={artifact.artifact_id}
                  className="text-button"
                  onClick={() =>
                    api("preview", {
                      node_id: nodeId,
                      task_id: task?.id,
                      artifact_id: artifact.artifact_id,
                    })
                      .then((r) =>
                        setAttachment({ url: r.url, title: artifact.title }),
                      )
                      .catch(onError)
                  }
                >
                  查看 {artifact.title}
                </button>
              ))}
            </div>
          </aside>
        )}
        {attachment && (
          <div className="artifact-overlay" role="dialog" aria-label="产物预览">
            <div>
              <strong>{attachment.title}</strong>
              <button
                className="text-button"
                onClick={() => setAttachment(null)}
              >
                关闭产物预览
              </button>
            </div>
            <img src={attachment.url} alt={attachment.title} />
          </div>
        )}
      </div>
    </section>
  );
}
