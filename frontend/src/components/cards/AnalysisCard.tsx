import type { Entry } from "../../types";
import CardShell from "./CardShell";

export default function AnalysisCard({ entry }: { entry: Entry }) {
  const d = entry.details;
  const plots = entry.artifacts.filter((a) => a.kind === "plot");
  const attempts = d.attempts?.length ?? 1;
  return (
    <CardShell entry={entry}>
      <p className="text-xs text-slate-500">{d.prompt}</p>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {d.ok ? (
          <span className="rounded bg-emerald-600 px-2 py-0.5 font-semibold text-white">✓ Executed · exit 0</span>
        ) : (
          <span className="rounded bg-red-600 px-2 py-0.5 font-semibold text-white">✗ Failed · exit {d.exit_code}</span>
        )}
        <span className="text-slate-500">
          {attempts} attempt{attempts > 1 ? "s" : ""} · code by {d.coder_node} · ran on {d.sandbox_node}
        </span>
      </div>
      {plots.map((p) => (
        <img key={p.path} src={p.path} alt="plot" className="w-full rounded-lg border border-slate-200 bg-white" />
      ))}
      {d.stdout && <pre className="max-h-48 overflow-auto rounded bg-slate-900 p-2 text-xs text-emerald-200">{d.stdout}</pre>}
      {!d.ok && d.stderr && (
        <pre className="max-h-40 overflow-auto rounded bg-red-50 p-2 text-xs text-red-800">{d.stderr.slice(-1500)}</pre>
      )}
      <details>
        <summary className="cursor-pointer text-xs text-slate-500">Code ({d.model})</summary>
        <pre className="mt-1 max-h-80 overflow-auto rounded bg-slate-50 p-2 text-xs">{d.code}</pre>
      </details>
    </CardShell>
  );
}
