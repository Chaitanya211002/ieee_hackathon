import { useState, type ReactNode } from "react";
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
    <article id={`entry-${entry.id}`} className="rounded-xl border border-slate-200 bg-white shadow-sm">
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

export interface ThreadProps {
  /** Follow-up entries about this capture, oldest first. */
  followUps?: Entry[];
  /** Set while a follow-up to this capture is being answered. */
  pending?: boolean;
  /** Ask another question about this capture. Absent: the card is read-only. */
  onAsk?: (question: string) => void;
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/**
 * Follow-up questions about a photo or video, shown inside the capture's own card.
 * Each one is still a separate hash-chained entry, so its hash and node are shown per turn.
 */
export function FollowUpThread({ entry, followUps = [], pending = false, onAsk }: ThreadProps & { entry: Entry }) {
  const [text, setText] = useState("");
  const what = entry.type === "video" ? "video" : "photo";
  const ask = () => {
    const q = text.trim();
    if (!q || pending || !onAsk) return;
    onAsk(q);
    setText("");
  };
  return (
    <div className="space-y-2 border-t border-slate-100 pt-2">
      {followUps.map((f) => (
        <div key={f.id} className="rounded-lg bg-slate-50 px-2.5 py-2">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span className="font-medium text-slate-600">↩ Q: {f.details.question}</span>
            <span className="ml-auto flex items-center gap-2">
              {clock(f.created_at)}
              {f.details?.routing?.total_latency_s != null && <span>{f.details.routing.total_latency_s}s</span>}
              <NodeBadge node={f.node} />
              <code className="text-[10px] text-slate-400" title={`hash ${f.hash}\nprev ${f.prev_hash}`}>
                #{f.hash.slice(0, 8)}
              </code>
            </span>
          </div>
          <p className="mt-1 whitespace-pre-wrap">{f.details.answer}</p>
          <ZoomCrop path={f.details.zoom?.crop_path} />
          {f.details.opencv && <p className="mt-1 text-xs text-emerald-800">{f.summary}</p>}
          {!f.details.opencv && f.details.vlm_count_estimate != null && (
            <p className="mt-1 text-xs text-amber-700">Count is a VLM estimate, not an exact count.</p>
          )}
        </div>
      ))}
      {pending && (
        <div className="flex items-center gap-2 rounded-lg bg-sky-50 px-2.5 py-2 text-xs text-sky-800">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
          Thinking…
        </div>
      )}
      {onAsk && (
        <div className="flex items-center gap-1.5">
          <input
            aria-label={`Ask a follow-up about this ${what}`}
            className="h-8 min-w-0 flex-1 rounded-md border border-slate-300 px-2 text-xs outline-none focus:border-sky-500"
            placeholder={`Ask a follow-up about this ${what}…`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
          />
          <button
            className="h-8 rounded-md border border-sky-300 px-2.5 text-xs font-medium text-sky-800 hover:bg-sky-50 disabled:opacity-40"
            disabled={pending || !text.trim()}
            onClick={ask}
          >
            Ask
          </button>
        </div>
      )}
    </div>
  );
}

/** The region the vision model enlarged before answering (details.zoom), when there is one. */
export function ZoomCrop({ path }: { path?: string }) {
  if (!path) return null;
  return (
    <figure className="flex items-center gap-2">
      <a href={path} target="_blank" rel="noreferrer">
        <img src={path} alt="part of the photo the model looked at closely" className="h-16 rounded border border-slate-200" />
      </a>
      <figcaption className="text-[11px] text-slate-500">Looked closer at this part of the photo</figcaption>
    </figure>
  );
}

export function Question({ q }: { q?: string | null }) {
  if (!q) return null;
  return <p className="text-xs text-slate-500">Q: {q}</p>;
}
