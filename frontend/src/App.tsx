import { useCallback, useEffect, useRef, useState } from "react";
import { api, reportError, today } from "./api";
import CaptureBar from "./components/CaptureBar";
import { DeleteContext } from "./components/cards/CardShell";
import EntryCard from "./components/EntryCard";
import Sidebar from "./components/Sidebar";
import StatusPanel from "./components/StatusPanel";
import TopBar from "./components/TopBar";
import { groupThreads, threadTail } from "./threads";
import type { Entry, Experiment, Protocol, Status, VerifyReport } from "./types";

interface Pending {
  id: number;
  label: string;
  /** Set for a follow-up: the capture it is about, so the spinner shows inside that card. */
  threadRoot?: string;
}

const pendingLabel = (file: File | null, text: string) => {
  if (!file) return text.toLowerCase().startsWith("code:") ? "Writing and running code…" : "Thinking…";
  if (file.type.startsWith("image/")) return "Looking at the photo…";
  if (file.type.startsWith("audio/")) return "Transcribing and listening…";
  if (file.type.startsWith("video/")) return "Watching the video (about 30–40 s)…";
  if (/\.(csv|tsv)$/i.test(file.name)) return "Writing and running analysis code…";
  return "Indexing the document…";
};

export default function App() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [current, setCurrent] = useState("default");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [protocols, setProtocols] = useState<Protocol[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [verify, setVerify] = useState<VerifyReport | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [drawer, setDrawer] = useState<"none" | "left" | "right">("none");
  const bottom = useRef<HTMLDivElement>(null);
  const threads = groupThreads(entries);
  const newCaptures = pending.filter((p) => !p.threadRoot);

  const refresh = useCallback(async () => {
    try {
      const [ex, en, pr, v] = await Promise.all([api.experiments(), api.entries(current), api.protocols(), api.verify()]);
      setExperiments(ex);
      setEntries(en);
      setProtocols(pr);
      setVerify(v);
      setError(null);
    } catch (e) {
      setError(`Cannot reach the BenchLog server: ${(e as Error).message}`);
      reportError("refresh", e);
    }
  }, [current]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const tick = () => api.status().then(setStatus).catch(() => setStatus(null));
    tick();
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, []);

  // A new capture goes to the bottom of the feed. A follow-up answer lands inside an earlier
  // card instead, so the feed must not jump to the bottom for it (see `send`).
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [threads.length, newCaptures.length]);

  /** `followUp`: ask another question about an earlier photo or video instead of adding a capture. */
  const send = async (file: File | null, text: string, followUp?: { of: Entry; root: Entry }) => {
    const id = Date.now();
    setPending((p) => [...p, { id, label: pendingLabel(file, text), threadRoot: followUp?.root.id }]);
    const form = new FormData();
    if (file) form.append("file", file, file.name);
    if (text) form.append("text", text);
    form.append("experiment_id", current);
    if (followUp) form.append("follow_up_of", followUp.of.id);
    try {
      await api.createEntry(form);
      await refresh();
      if (followUp) {
        requestAnimationFrame(() =>
          document.getElementById(`entry-${followUp.root.id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
        );
      }
    } catch (e) {
      setError((e as Error).message);
      reportError(`send ${file ? `${file.name} (${file.type || "?"}, ${file.size} B)` : "text"}`, e);
    } finally {
      setPending((p) => p.filter((x) => x.id !== id));
    }
  };

  /** Takes an entry and its follow-ups out of the notebook; the server appends a deletion record. */
  const remove = useCallback(
    async (entry: Entry) => {
      try {
        await api.deleteEntry(entry.id);
        await refresh();
      } catch (e) {
        setError(`Could not delete the entry: ${(e as Error).message}`);
        reportError(`delete ${entry.id}`, e);
        throw e;
      }
    },
    [refresh],
  );

  const currentName = experiments.find((e) => e.id === current)?.name ?? current;
  const panel = (side: "left" | "right") =>
    drawer === side ? "fixed inset-y-0 z-30 w-72 shadow-xl " + (side === "left" ? "left-0" : "right-0") : "hidden";

  return (
    <div className="flex h-full flex-col">
      <TopBar
        experiment={currentName}
        verify={verify}
        onExport={() => window.open(api.exportUrl(today(), current), "_blank")}
        onMenu={() => setDrawer(drawer === "left" ? "none" : "left")}
        onStatus={() => setDrawer(drawer === "right" ? "none" : "right")}
      />
      <div className="relative flex min-h-0 flex-1">
        {drawer !== "none" && <div className="fixed inset-0 z-20 bg-black/30" onClick={() => setDrawer("none")} />}
        <div className={`${panel("left")} border-r border-slate-200 lg:static lg:z-auto lg:block lg:w-60 lg:shadow-none`}>
          <Sidebar
            experiments={experiments}
            current={current}
            protocols={protocols}
            uploading={uploading}
            onSelect={(id) => {
              setCurrent(id);
              setDrawer("none");
            }}
            onCreate={async (name) => {
              const e = await api.createExperiment(name);
              setCurrent(e.id);
            }}
            onUploadProtocol={async (f) => {
              setUploading(true);
              try {
                await api.uploadProtocol(f);
                await refresh();
              } catch (e) {
                setError((e as Error).message);
                reportError(`protocol upload ${f.name}`, e);
              } finally {
                setUploading(false);
              }
            }}
          />
        </div>
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 space-y-3 overflow-y-auto p-3">
            {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>}
            {entries.length === 0 && pending.length === 0 && (
              <div className="mx-auto mt-10 max-w-sm text-center text-sm text-slate-500">
                <p className="text-base font-medium text-slate-700">No entries yet</p>
                <p className="mt-1">
                  Capture a plate photo, record a voice note, film a clip, ask a protocol question, or type{" "}
                  <code>code:</code> followed by an analysis request.
                </p>
              </div>
            )}
            <DeleteContext.Provider value={remove}>
              {threads.map((t) => (
                <EntryCard
                  key={t.root.id}
                  entry={t.root}
                  followUps={t.followUps}
                  pending={pending.some((p) => p.threadRoot === t.root.id)}
                  onAsk={(q) => send(null, q, { of: threadTail(t), root: t.root })}
                />
              ))}
            </DeleteContext.Provider>
            {newCaptures.map((p) => (
              <div key={p.id} className="flex items-center gap-2 rounded-xl border border-dashed border-sky-300 bg-sky-50 px-3 py-3 text-sm text-sky-800">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
                {p.label}
              </div>
            ))}
            <div ref={bottom} />
          </div>
          <CaptureBar busy={false} onSend={(file, text) => send(file, text)} />
        </main>
        <div className={`${panel("right")} border-l border-slate-200 xl:static xl:z-auto xl:block xl:w-72 xl:shadow-none`}>
          <StatusPanel status={status} entries={entries} />
        </div>
      </div>
    </div>
  );
}
