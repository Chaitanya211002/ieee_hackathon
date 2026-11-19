import type { ReactNode } from "react";
import type { Entry } from "../../types";

const TYPE_STYLE: Record<string, { label: string; icon: string; tint: string }> = {
  voice: { label: "Voice", icon: "🎙️", tint: "bg-violet-100 text-violet-800" },
  photo: { label: "Photo", icon: "📷", tint: "bg-sky-100 text-sky-800" },
  video: { label: "Video", icon: "🎬", tint: "bg-rose-100 text-rose-800" },
  protocol_qa: { label: "Protocol Q&A", icon: "📘", tint: "bg-amber-100 text-amber-800" },
  analysis: { label: "Analysis", icon: "📈", tint: "bg-emerald-100 text-emerald-800" },
  note: { label: "Note", icon: "📝", tint: "bg-slate-200 text-slate-700" },
};

export function NodeBadge({ node }: { node: string }) {
  const color = node === "WIN" ? "bg-indigo-600" : "bg-slate-700";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${color}`}>{node}</span>;
}

export default function CardShell({ entry, children }: { entry: Entry; children: ReactNode }) {
  const t = TYPE_STYLE[entry.type] ?? TYPE_STYLE.note;
  const time = new Date(entry.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const latency = entry.details?.routing?.total_latency_s;
  return (
    <article className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2 text-xs">
        <span className={`rounded-full px-2 py-0.5 font-medium ${t.tint}`}>
          {t.icon} {t.label}
        </span>
        <span className="text-slate-500">{time}</span>
        {latency != null && <span className="text-slate-400">{latency}s</span>}
        <span className="ml-auto flex items-center gap-2">
          <NodeBadge node={entry.node} />
          <code className="text-[10px] text-slate-400" title={`hash ${entry.hash}\nprev ${entry.prev_hash}`}>
            #{entry.hash.slice(0, 8)}
          </code>
        </span>
      </header>
      <div className="space-y-2 px-3 py-3 text-sm text-slate-800">{children}</div>
    </article>
  );
}

export function Question({ q }: { q?: string | null }) {
  if (!q) return null;
  return <p className="text-xs text-slate-500">Q: {q}</p>;
}
