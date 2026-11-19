import { useCallback, useEffect, useRef, useState } from "react";
import { api, today } from "./api";
import CaptureBar from "./components/CaptureBar";
import EntryCard from "./components/EntryCard";
import Sidebar from "./components/Sidebar";
import StatusPanel from "./components/StatusPanel";
import TopBar from "./components/TopBar";
import type { Entry, Experiment, Protocol, Status, VerifyReport } from "./types";

interface Pending {
  id: number;
  label: string;
}

const pendingLabel = (file: File | null, text: string) => {
  if (!file) return text.toLowerCase().startsWith("code:") ? "Writing and running code…" : "Thinking…";
  // follow-ups have no file; "Thinking…" covers them
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
  const [followUp, setFollowUp] = useState<Entry | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length, pending.length]);

  const send = async (file: File | null, text: string) => {
    const id = Date.now();
    setPending((p) => [...p, { id, label: pendingLabel(file, text) }]);
    const form = new FormData();
    if (file) form.append("file", file, file.name);
    if (text) form.append("text", text);
    form.append("experiment_id", current);
    if (followUp && !file) form.append("follow_up_of", followUp.id);
    setFollowUp(null);
    try {
      await api.createEntry(form);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending((p) => p.filter((x) => x.id !== id));
    }
  };

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
            {entries.map((e) => (
              <EntryCard key={e.id} entry={e} onFollowUp={setFollowUp} />
            ))}
            {pending.map((p) => (
              <div key={p.id} className="flex items-center gap-2 rounded-xl border border-dashed border-sky-300 bg-sky-50 px-3 py-3 text-sm text-sky-800">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
                {p.label}
              </div>
            ))}
            <div ref={bottom} />
          </div>
          <CaptureBar
            busy={false}
            onSend={send}
            followUp={
              followUp &&
              `${followUp.type} from ${new Date(followUp.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
            }
            onClearFollowUp={() => setFollowUp(null)}
          />
        </main>
        <div className={`${panel("right")} border-l border-slate-200 xl:static xl:z-auto xl:block xl:w-72 xl:shadow-none`}>
          <StatusPanel status={status} entries={entries} />
        </div>
      </div>
    </div>
  );
}
