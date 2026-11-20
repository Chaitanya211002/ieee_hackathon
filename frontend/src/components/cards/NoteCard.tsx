import type { Entry } from "../../types";
import CardShell from "./CardShell";

export default function NoteCard({ entry }: { entry: Entry }) {
  const d = entry.details;
  if (d.kind === "deletion") {
    return (
      <CardShell entry={entry}>
        <p className="text-slate-500">
          🗑️ {d.text ?? entry.summary}. The deletion is recorded in the hash chain, so the chain still verifies.
        </p>
      </CardShell>
    );
  }
  return (
    <CardShell entry={entry}>
      <p className="whitespace-pre-wrap">{d.text ?? entry.summary}</p>
      {d.kind === "protocol_indexed" && (
        <p className="text-xs text-slate-500">
          {d.chunks} chunks · sections: {(d.sections ?? []).join(", ")}
        </p>
      )}
    </CardShell>
  );
}
