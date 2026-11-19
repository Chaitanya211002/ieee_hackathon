import { useRef, useState } from "react";
import type { Experiment, Protocol } from "../types";

interface Props {
  experiments: Experiment[];
  current: string;
  protocols: Protocol[];
  onSelect: (id: string) => void;
  onCreate: (name: string) => void;
  onUploadProtocol: (f: File) => void;
  uploading: boolean;
}

export default function Sidebar(p: Props) {
  const [name, setName] = useState("");
  const pdfIn = useRef<HTMLInputElement>(null);
  return (
    <nav className="flex h-full flex-col gap-4 overflow-y-auto bg-white p-3 text-sm">
      <section>
        <h2 className="mb-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Experiments</h2>
        <ul className="space-y-0.5">
          {p.experiments.map((e) => (
            <li key={e.id}>
              <button
                className={`flex w-full justify-between rounded-md px-2 py-1.5 text-left ${
                  e.id === p.current ? "bg-sky-100 font-medium text-sky-900" : "hover:bg-slate-100"
                }`}
                onClick={() => p.onSelect(e.id)}
              >
                <span className="truncate">{e.name}</span>
                <span className="text-xs text-slate-400">{e.entry_count ?? ""}</span>
              </button>
            </li>
          ))}
        </ul>
        <form
          className="mt-2 flex gap-1"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (name.trim()) p.onCreate(name.trim());
            setName("");
          }}
        >
          <input
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs"
            placeholder="New experiment"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="rounded-md bg-slate-800 px-2 text-xs text-white">+</button>
        </form>
      </section>
      <section>
        <h2 className="mb-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Indexed protocols</h2>
        {p.protocols.length === 0 && <p className="text-xs text-slate-400">None yet. Add a PDF to ask questions.</p>}
        <ul className="space-y-1">
          {p.protocols.map((d) => (
            <li key={d.source} className="rounded-md bg-amber-50 px-2 py-1.5 text-xs">
              <div className="truncate font-medium text-amber-900">📄 {d.source}</div>
              <div className="truncate text-amber-800/70">
                {d.chunks} chunks · {d.sections.slice(0, 3).join(", ")}
              </div>
            </li>
          ))}
        </ul>
        <button
          className="mt-2 w-full rounded-md border border-dashed border-amber-400 py-1.5 text-xs text-amber-800 disabled:opacity-50"
          disabled={p.uploading}
          onClick={() => pdfIn.current?.click()}
        >
          {p.uploading ? "Indexing…" : "+ Add protocol PDF"}
        </button>
        <input
          ref={pdfIn}
          type="file"
          accept=".pdf,.txt,.md"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) p.onUploadProtocol(f);
            e.target.value = "";
          }}
        />
      </section>
    </nav>
  );
}
