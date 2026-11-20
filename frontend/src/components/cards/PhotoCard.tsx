import { useState } from "react";
import type { Entry } from "../../types";
import CardShell, { FollowUpThread, Question, ZoomCrop, type ThreadProps } from "./CardShell";

export default function PhotoCard({ entry, ...thread }: { entry: Entry } & ThreadProps) {
  const d = entry.details;
  const cv = d.opencv;
  const [showAnnotated, setShowAnnotated] = useState(true);
  const original = entry.artifacts[0]?.path;
  const img = cv && showAnnotated ? cv.annotated_path : original;
  return (
    <CardShell entry={entry}>
      {img && <img src={img} alt="capture" className="max-h-80 w-full rounded-lg bg-slate-100 object-contain" />}
      {cv && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-emerald-50 p-2">
              <div className="text-[11px] text-emerald-700">OpenCV count</div>
              <div className="text-2xl font-semibold text-emerald-900">{cv.count}</div>
            </div>
            <div className="rounded-lg bg-slate-50 p-2">
              <div className="text-[11px] text-slate-600">VLM estimate</div>
              <div className="text-2xl font-semibold text-slate-800">{d.vlm_count_estimate ?? "–"}</div>
              <div className="text-[10px] text-slate-500">estimate, not exact</div>
            </div>
          </div>
          <button className="text-xs text-sky-700 underline" onClick={() => setShowAnnotated((v) => !v)}>
            {showAnnotated ? "Show original" : "Show OpenCV detections"}
          </button>
        </>
      )}
      <Question q={d.question} />
      <p className="whitespace-pre-wrap">{d.answer}</p>
      <ZoomCrop path={d.zoom?.crop_path} />
      {!cv && d.vlm_count_estimate != null && (
        <p className="text-xs text-amber-700">Count is a VLM estimate, not an exact count.</p>
      )}
      <FollowUpThread entry={entry} {...thread} />
    </CardShell>
  );
}
