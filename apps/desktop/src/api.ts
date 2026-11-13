import { invoke, isTauri } from "@tauri-apps/api/core";
import { open, save } from "@tauri-apps/plugin-dialog";

export async function api<T = any>(
  command: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  const response = isTauri()
    ? await invoke<any>("api", { command, args })
    : await (
        await fetch("/api", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command, args }),
        })
      ).json();
  if (!response.ok) throw new Error(response.error?.message || "操作失败");
  return response.data;
}

export async function pickFiles(
  options: {
    multiple?: boolean;
    directory?: boolean;
    extensions?: string[];
  } = {},
): Promise<string[]> {
  if (isTauri()) {
    const value = await open({
      multiple: options.multiple || false,
      directory: options.directory || false,
      filters: options.extensions
        ? [{ name: "文件", extensions: options.extensions }]
        : undefined,
    });
    return value ? (Array.isArray(value) ? value : [value]) : [];
  }
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = options.multiple || options.directory || false;
    if (options.directory) input.webkitdirectory = true;
    if (options.extensions)
      input.accept = options.extensions.map((e) => "." + e).join(",");
    input.style.display = "none";
    document.body.append(input);
    input.addEventListener(
      "cancel",
      () => {
        input.remove();
        resolve([]);
      },
      { once: true },
    );
    input.onchange = async () => {
      try {
        const paths: string[] = [];
        for (const file of Array.from(input.files || [])) {
          const response = await (
            await fetch("/api/upload?name=" + encodeURIComponent(file.name), {
              method: "POST",
              body: file,
            })
          ).json();
          if (!response.ok) throw new Error(response.error.message);
          paths.push(response.data.path);
        }
        resolve(paths);
      } catch (error) {
        reject(error);
      } finally {
        input.remove();
      }
    };
    input.click();
  });
}

export async function saveBlob(blob: Blob, name: string) {
  if (isTauri()) {
    const path = await save({ defaultPath: name });
    if (!path) return;
    await invoke("write_file", {
      path,
      bytes: Array.from(new Uint8Array(await blob.arrayBuffer())),
    });
  } else {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export async function exportTask(
  taskId: string,
  nodeId: string,
  format: string,
) {
  const value = await api("export", {
    node_id: nodeId,
    task_id: taskId,
    format,
  });
  await saveBlob(
    new Blob([value.content], {
      type: format === "csv" ? "text/csv;charset=utf-8" : "application/json",
    }),
    value.filename,
  );
}
