import type { Entry } from "../../types";
import CardShell, { FollowUpThread, Question, type ThreadProps } from "./CardShell";

interface Frame {
  index: number;
  t: number;
  path: string;
}

export default function VideoCard({ entry, ...thread }: { entry: Entry } & ThreadProps) {
  const d = entry.details;
  const frames: Frame[] = d.frames ?? [];
  return (
    <CardShell entry={entry}>
      {d.media?.path && <video controls src={d.media.path} className="max-h-72 w-full rounded-lg bg-black" />}
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {frames.map((f) => (
          <figure key={f.index} className="shrink-0">
            <img src={f.path} alt={`frame ${f.index + 1}`} className="h-14 rounded border border-slate-200" />
            <figcaption className="text-center text-[10px] text-slate-500">{f.t.toFixed(1)}s</figcaption>
          </figure>
        ))}
      </div>
      <Question q={d.question} />
      <p className="whitespace-pre-wrap">{d.answer}</p>
      {d.audio && (
        <p className="text-xs text-slate-600">
          Audio track: {d.audio.transcript ? `"${d.audio.transcript}"` : "no speech"}
          {d.audio.sound_alerts?.length > 0 &&
            ` · 🔔 ${d.audio.sound_alerts.map((a: { label: string }) => a.label).join(", ")}`}
        </p>
      )}
      <p className="text-[11px] text-slate-400">
        {frames.length} frames over {d.duration_s}s, sent in order to {d.model}
      </p>
      <FollowUpThread entry={entry} {...thread} />
    </CardShell>
  );
}
