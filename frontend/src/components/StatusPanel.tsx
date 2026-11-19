import type { Entry, Status } from "../types";

const JOB_LABEL: Record<string, string> = {
  vision: "Images & video",
  docs: "Protocol Q&A",
  coder: "Code generation",
  audio: "Speech & sounds",
  sandbox: "Code execution",
};

export default function StatusPanel({ status, entries }: { status: Status | null; entries: Entry[] }) {
  const nodeUp = (n: string) =>
    status ? Object.entries(status.nodes).some(([k, v]) => k.startsWith(n + ".") && v.up) : false;
  return (
    <aside className="flex h-full flex-col gap-4 overflow-y-auto bg-white p-3 text-sm">
      <section>
        <h2 className="mb-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Laptops</h2>
        <div className="grid grid-cols-2 gap-2 text-xs">
          {[
            ["m5", "M5 · MacBook Air"],
            ["win", "WIN · RTX 3060"],
          ].map(([id, label]) => (
            <div key={id} className="rounded-md border border-slate-200 p-2">
              <div className="flex items-center gap-1.5 font-medium">
                <span className={`h-2 w-2 rounded-full ${nodeUp(id) ? "bg-emerald-500" : "bg-slate-300"}`} />
                {label}
              </div>
              <div className="text-slate-500">{nodeUp(id) ? "online" : id === "win" ? "offline → M5" : "offline"}</div>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h2 className="mb-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Models</h2>
        <ul className="space-y-1.5">
          {status &&
            Object.entries(status.jobs).map(([job, j]) => (
              <li key={job} className="rounded-md bg-slate-50 px-2 py-1.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{JOB_LABEL[job] ?? job}</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${
                      j.serving === "WIN" ? "bg-indigo-600" : "bg-slate-700"
                    }`}
                  >
                    {j.serving}
                    {j.serving !== j.configured && " (fallback)"}
                  </span>
                </div>
                <div className="truncate text-slate-500">{j.model}</div>
              </li>
            ))}
          {!status && <li className="text-xs text-slate-400">Connecting…</li>}
        </ul>
      </section>
      <section className="min-h-0">
        <h2 className="mb-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Hash chain</h2>
        <ol className="space-y-1 font-mono text-[10px]">
          {[...entries].reverse().slice(0, 12).map((e) => (
            <li key={e.id} className="rounded bg-slate-50 px-2 py-1" title={`prev ${e.prev_hash}`}>
              <span className="text-slate-800">{e.hash.slice(0, 16)}</span>
              <span className="text-slate-400"> ← {e.prev_hash.slice(0, 8)}</span>
              <span className="float-right text-slate-500">{e.type}</span>
            </li>
          ))}
        </ol>
      </section>
    </aside>
  );
}
