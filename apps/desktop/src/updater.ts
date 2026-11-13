import { isTauri } from "@tauri-apps/api/core";
import {
  check,
  type DownloadEvent,
  type Update,
} from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { api } from "./api";
import { version } from "../package.json";

export const APP_VERSION = version;
export interface AppUpdate {
  version: string;
  body?: string;
  date?: string;
  download: (onEvent: (event: DownloadEvent) => void) => Promise<void>;
  install: () => Promise<void>;
  close: () => Promise<void>;
}
export interface UpdateService {
  supported: boolean;
  check: () => Promise<AppUpdate | null>;
  assertReady: () => Promise<void>;
  restart: () => Promise<void>;
}
export const updateService: UpdateService = {
  supported: isTauri(),
  check: async () => (await check({ timeout: 15000 })) as Update | null,
  assertReady: async () => {
    const readiness = await api<{ ready: boolean; reason: string }>(
      "update_readiness",
      { node_id: "local" },
    );
    if (!readiness.ready) throw new Error(readiness.reason);
  },
  restart: relaunch,
};
