import { useState } from "react";
import type { ModelSpec } from "./types";

export default function ModelChooser({
  models,
  value,
  disabled,
  onChange,
}: {
  models: ModelSpec[];
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState("");
  const families = [
    ...new Set(models.map((m) => m.extensions?.family).filter(Boolean)),
  ].sort();
  const filtered = models.filter(
    (m) =>
      (!family || m.extensions?.family === family) &&
      m.name.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const current = models.find((m) => m.id === value);
  return (
    <div className="model-chooser">
      {models.length > 20 && (
        <div className="two-fields model-search">
          <label className="field">
            <span>搜索模型</span>
            <input
              aria-label="搜索模型"
              placeholder="例如 mobilenet、resnet18…"
              value={query}
              disabled={disabled}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label className="field">
            <span>模型家族</span>
            <select
              aria-label="模型家族"
              value={family}
              disabled={disabled}
              onChange={(e) => setFamily(e.target.value)}
            >
              <option value="">全部家族</option>
              {families.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      <label className="field">
        <span>
          支持模型
          {models.length > 20 ? ` · ${filtered.length} / ${models.length}` : ""}
        </span>
        <select
          aria-label="支持模型"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {current && !filtered.some((m) => m.id === value) && (
            <option value={current.id}>当前所选：{current.name}</option>
          )}
          {filtered.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      {!filtered.length && (
        <p className="muted small-text">没有匹配的模型，请调整搜索条件。</p>
      )}
    </div>
  );
}
