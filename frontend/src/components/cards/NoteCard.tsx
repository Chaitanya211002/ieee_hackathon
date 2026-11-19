import type { Entry } from "../../types";
import CardShell from "./CardShell";

export default function NoteCard({ entry }: { entry: Entry }) {
  const d = entry.details;
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
