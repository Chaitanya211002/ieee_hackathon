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
  /** Takes the entry (and its follow-ups) out of the notebook. Returns the deletion record. */
  deleteEntry: (id: string) =>
    fetch(`${BASE}/entries/${encodeURIComponent(id)}`, { method: "DELETE" }).then((r) => json<Entry>(r)),
  /** Speech to text only: used to dictate a note into the text box. Nothing is stored. */
  transcribe: (file: File) => {
    const f = new FormData();
    f.append("file", file, file.name);
    return fetch(`${BASE}/transcribe`, { method: "POST", body: f }).then((r) => json<{ text: string; node: string }>(r));
  },
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

/** Report a browser-side error to the server's event log (data/logs/events.jsonl). Never throws. */
export function reportError(where: string, err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  try {
    fetch(`${BASE}/client-log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, where, user_agent: navigator.userAgent, url: location.href }),
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* logging must never break the app */
  }
}

/** Artifact/media paths come back as "/media/..."; both Vite and FastAPI serve that path. */
export const mediaUrl = (path: string) => path;

export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
