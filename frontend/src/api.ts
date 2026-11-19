import type { Entry, Experiment, Protocol, Status, VerifyReport } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  entries: (experimentId?: string) =>
    fetch(`${BASE}/entries${experimentId ? `?experiment_id=${encodeURIComponent(experimentId)}` : ""}`).then(
      (r) => json<Entry[]>(r),
    ),
  createEntry: (form: FormData) => fetch(`${BASE}/entry`, { method: "POST", body: form }).then((r) => json<Entry>(r)),
  verify: () => fetch(`${BASE}/verify`).then((r) => json<VerifyReport>(r)),
  status: () => fetch(`${BASE}/status`).then((r) => json<Status>(r)),
  experiments: () => fetch(`${BASE}/experiments`).then((r) => json<Experiment[]>(r)),
  createExperiment: (name: string) => {
    const f = new FormData();
    f.append("name", name);
    return fetch(`${BASE}/experiments`, { method: "POST", body: f }).then((r) => json<Experiment>(r));
  },
  protocols: () => fetch(`${BASE}/protocols`).then((r) => json<Protocol[]>(r)),
  uploadProtocol: (file: File) => {
    const f = new FormData();
    f.append("file", file);
    return fetch(`${BASE}/protocols`, { method: "POST", body: f }).then((r) => json<unknown>(r));
  },
  exportUrl: (date: string, experimentId?: string) =>
    `${BASE}/export?date=${date}${experimentId ? `&experiment_id=${encodeURIComponent(experimentId)}` : ""}`,
};

/** Artifact/media paths come back as "/media/..."; both Vite and FastAPI serve that path. */
export const mediaUrl = (path: string) => path;

export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
