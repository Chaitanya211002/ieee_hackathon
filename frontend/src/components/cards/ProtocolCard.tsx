import type { Entry } from "../../types";
import CardShell, { Question } from "./CardShell";

interface Hit {
  source: string;
  section: string;
  similarity: number;
  text: string;
}

export default function ProtocolCard({ entry }: { entry: Entry }) {
  const d = entry.details;
  const hits: Hit[] = d.retrieved ?? [];
  return (
    <CardShell entry={entry}>
      <Question q={d.question} />
      {d.refused ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 font-medium text-amber-900">
          {d.message ?? "Not in your indexed protocols."}
        </div>
      ) : (
        <>
          <p className="font-medium">{d.answer}</p>
          {d.citation && (
            <span className="inline-block rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
              📄 {d.citation.source} § {d.citation.section}
              {d.citation.page ? ` · p.${d.citation.page}` : ""}
            </span>
          )}
          {d.quote && <blockquote className="border-l-2 border-amber-300 pl-2 text-xs text-slate-600">“{d.quote}”</blockquote>}
        </>
      )}
      {hits.length > 0 && (
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer text-slate-500">
            {hits.length} excerpts retrieved · best similarity {d.best_similarity}
          </summary>
          <ul className="mt-1 space-y-1">
            {hits.map((h, i) => (
              <li key={i} className="rounded bg-slate-50 p-2">
                <div className="font-medium">
                  {h.source} § {h.section} · {h.similarity}
                </div>
                <div className="line-clamp-3">{h.text.split("\n").slice(1).join(" ")}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </CardShell>
  );
}
