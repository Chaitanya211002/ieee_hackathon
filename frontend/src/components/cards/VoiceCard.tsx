import type { Entry, SoundLabel } from "../../types";
import CardShell, { Question } from "./CardShell";

export default function VoiceCard({ entry }: { entry: Entry }) {
  const d = entry.details;
  const alerts: SoundLabel[] = d.sound_alerts ?? [];
  const labels: SoundLabel[] = d.sound_labels ?? [];
  return (
    <CardShell entry={entry}>
      {alerts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {alerts.map((a) => (
            <span key={a.label} className="rounded-md bg-amber-100 px-2 py-1 text-xs font-medium text-amber-900">
              🔔 {a.label} · {a.score.toFixed(2)}
            </span>
          ))}
        </div>
      )}
      <Question q={d.question} />
      {d.answer && d.answer !== d.transcript && <p className="font-medium">{d.answer}</p>}
      {d.media?.path && <audio controls src={d.media.path} className="h-9 w-full" />}
      {d.transcript ? (
        <blockquote className="border-l-2 border-violet-300 pl-2 text-slate-700">{d.transcript}</blockquote>
      ) : (
        <p className="text-slate-500 italic">No speech detected.</p>
      )}
      {labels.length > 0 && (
        <p className="text-xs text-slate-500">
          Sound labels: {labels.map((l) => `${l.label} ${l.score.toFixed(2)}`).join(" · ")}
        </p>
      )}
      {(d.transcribe_node !== d.classify_node || d.transcribe_fallback_from) && (
        <p className="text-[11px] text-slate-400">
          transcribe {d.transcribe_node} · sounds {d.classify_node}
          {d.transcribe_fallback_from && ` · fell back from ${d.transcribe_fallback_from}`}
        </p>
      )}
    </CardShell>
  );
}
