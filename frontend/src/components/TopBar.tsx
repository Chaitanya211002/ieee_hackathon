import type { VerifyReport } from "../types";

interface Props {
  experiment: string;
  verify: VerifyReport | null;
  onExport: () => void;
  onMenu: () => void;
  onStatus: () => void;
}

export default function TopBar({ experiment, verify, onExport, onMenu, onStatus }: Props) {
  return (
    <header className="flex items-center gap-2 bg-slate-900 px-3 py-2 text-white">
      <button className="text-xl lg:hidden" aria-label="experiments" onClick={onMenu}>
        ☰
      </button>
      <div className="min-w-0">
        <div className="text-[10px] tracking-wider text-slate-400 uppercase">BenchLog</div>
        <div className="truncate text-sm font-semibold">{experiment}</div>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1.5 text-[11px] whitespace-nowrap">
        <span className="hidden rounded-full bg-emerald-700/70 px-2 py-1 sm:inline">● Offline · all models local</span>
        <span className="rounded-full bg-emerald-700/70 px-2 py-1 sm:hidden">● Local</span>
        {verify &&
          (verify.ok ? (
            <span className="rounded-full bg-sky-700/70 px-2 py-1" title={`head ${verify.head ?? ""}`}>
              🔗 <span className="hidden sm:inline">Chain verified · </span>
              <span className="sm:hidden">✓ </span>
              {verify.verified}
            </span>
          ) : (
            <span className="rounded-full bg-red-600 px-2 py-1" title={verify.reason}>
              ⚠ <span className="hidden sm:inline">Chain </span>broken
            </span>
          ))}
        <button className="rounded-md bg-white/10 px-2 py-1 hover:bg-white/20" onClick={onExport}>
          Export
        </button>
        <button className="rounded-md bg-white/10 px-2 py-1 xl:hidden" aria-label="status" onClick={onStatus}>
          ⓘ
        </button>
      </div>
    </header>
  );
}
