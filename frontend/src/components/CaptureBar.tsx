import { useRef, useState } from "react";
import { reportError } from "../api";

interface Props {
  busy: boolean;
  onSend: (file: File | null, text: string) => void;
  followUp?: string | null; // label of the entry a follow-up question is about
  onClearFollowUp?: () => void;
}

// MediaRecorder needs a secure context (https or localhost). A phone on http://<M5-IP> is not
// one, so it falls back to the system recorder through a file input with capture.
const canRecord = typeof window !== "undefined" && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

export default function CaptureBar({ busy, onSend, followUp, onClearFollowUp }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const photoIn = useRef<HTMLInputElement>(null);
  const videoIn = useRef<HTMLInputElement>(null);
  const audioIn = useRef<HTMLInputElement>(null);
  const fileIn = useRef<HTMLInputElement>(null);

  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
    e.target.value = "";
  };

  const toggleRecord = async () => {
    setError(null);
    if (!canRecord) {
      audioIn.current?.click();
      return;
    }
    if (recording) {
      recorder.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "audio/mp4";
      const rec = new MediaRecorder(stream, { mimeType: mime });
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const ext = mime.includes("webm") ? "webm" : "m4a";
        setFile(new File(chunks, `voice-note.${ext}`, { type: mime }));
      };
      recorder.current = rec;
      rec.start();
      setRecording(true);
    } catch (e) {
      setError(`Microphone unavailable: ${(e as Error).message}`);
      reportError("microphone", e);
    }
  };

  const send = () => {
    if (busy || (!file && !text.trim())) return;
    onSend(file, text.trim());
    setFile(null);
    setText("");
  };

  const btn = "flex h-10 min-w-10 items-center justify-center rounded-lg bg-slate-100 px-2 text-lg hover:bg-slate-200";
  return (
    <div className="border-t border-slate-200 bg-white px-2 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
      {(file || error || followUp) && (
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          {followUp && !file && (
            <span className="flex items-center gap-1 rounded-full bg-violet-100 px-2 py-1 text-violet-900">
              ↩ Follow-up on {followUp}
              <button aria-label="cancel follow-up" className="ml-1 text-violet-700" onClick={onClearFollowUp}>
                ✕
              </button>
            </span>
          )}
          {file && (
            <span className="flex items-center gap-1 rounded-full bg-sky-100 px-2 py-1 text-sky-900">
              📎 {file.name} ({Math.max(1, Math.round(file.size / 1024))} KB)
              <button aria-label="remove file" className="ml-1 text-sky-700" onClick={() => setFile(null)}>
                ✕
              </button>
            </span>
          )}
          {error && <span className="text-red-600">{error}</span>}
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <button className={btn} title="Photo" onClick={() => photoIn.current?.click()}>
          📷
        </button>
        <button
          className={`${btn} ${recording ? "animate-pulse bg-red-500 text-white hover:bg-red-600" : ""}`}
          title={recording ? "Stop recording" : "Voice note"}
          onClick={toggleRecord}
        >
          {recording ? "⏹" : "🎙️"}
        </button>
        <button className={btn} title="Video" onClick={() => videoIn.current?.click()}>
          🎬
        </button>
        <button className={btn} title="File (PDF, CSV, audio, image)" onClick={() => fileIn.current?.click()}>
          📎
        </button>
        <input
          className="h-10 min-w-0 flex-1 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-sky-500"
          placeholder={
            file
              ? "Question about this file (optional)"
              : followUp
                ? `Ask another question about the ${followUp.split(" ")[0]}…`
                : "Note, protocol question, or code: …"
          }
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button
          className="h-10 rounded-lg bg-sky-600 px-4 text-sm font-semibold text-white disabled:opacity-40"
          disabled={busy || (!file && !text.trim())}
          onClick={send}
        >
          {busy ? "…" : "Send"}
        </button>
      </div>
      <input ref={photoIn} type="file" accept="image/*" capture="environment" hidden onChange={pick} />
      <input ref={videoIn} type="file" accept="video/*" capture="environment" hidden onChange={pick} />
      <input ref={audioIn} type="file" accept="audio/*" capture hidden onChange={pick} />
      <input
        ref={fileIn}
        type="file"
        accept=".pdf,.txt,.md,.csv,.tsv,image/*,audio/*,video/*"
        hidden
        onChange={pick}
      />
    </div>
  );
}
