import { useEffect, useRef } from "react";
import { useAgentStore } from "../store/useAgentStore";

// Colour + icon per log level
const LEVEL_STYLES = {
  info:    { text: "text-slate-300",   icon: "·",  dot: "bg-slate-500"    },
  success: { text: "text-emerald-300", icon: "✓",  dot: "bg-emerald-400"  },
  warn:    { text: "text-amber-300",   icon: "⚠",  dot: "bg-amber-400"    },
  error:   { text: "text-rose-300",    icon: "✗",  dot: "bg-rose-400"     },
};

const fmt = (isoTs) => {
  try {
    const d = new Date(isoTs);
    return d.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
};

const LogRow = ({ entry }) => {
  const { text, icon, dot } = LEVEL_STYLES[entry.level] ?? LEVEL_STYLES.info;
  const isSeparator = entry.message.startsWith("─");
  if (isSeparator) {
    return (
      <li className="flex items-center gap-2 py-0.5 select-none">
        <span className="w-16 shrink-0" />
        <span className="text-slate-600 text-xs font-mono">{entry.message}</span>
      </li>
    );
  }
  return (
    <li className="flex items-start gap-2 py-0.5 group">
      {/* Timestamp */}
      <span className="w-16 shrink-0 font-mono text-[10px] text-slate-500 mt-0.5">
        {fmt(entry.ts)}
      </span>
      {/* Level dot */}
      <span
        className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`}
        title={entry.level}
      />
      {/* Source tag */}
      {entry.source && entry.source !== "frontend" && (
        <span className="shrink-0 rounded bg-slate-700/60 px-1 py-0 font-mono text-[10px] text-slate-400">
          {entry.source}
        </span>
      )}
      {/* Message */}
      <span className={`font-mono text-xs leading-relaxed break-all ${text}`}>
        <span className="mr-1 opacity-60">{icon}</span>
        {entry.message}
      </span>
    </li>
  );
};

const LiveLogPanel = () => {
  const liveLogs = useAgentStore((s) => s.liveLogs);
  const loading   = useAgentStore((s) => s.loading);
  const bottomRef = useRef(null);

  // Auto-scroll to bottom whenever new log entries arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [liveLogs.length]);

  if (!liveLogs.length) return null;

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="section-title">Execution Log</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-50">
            Live Pipeline Events
            {loading && (
              <span className="ml-2 inline-block h-2 w-2 animate-pulse rounded-full bg-cyan-400 align-middle" />
            )}
          </h2>
        </div>
        <span className="rounded-full bg-slate-700/60 px-2 py-0.5 font-mono text-xs text-slate-400">
          {liveLogs.length} events
        </span>
      </div>

      <div className="relative mt-4 overflow-hidden rounded-xl border border-slate-700/50 bg-slate-950/70">
        {/* Terminal-style header bar */}
        <div className="flex items-center gap-1.5 border-b border-slate-700/40 bg-slate-900/50 px-3 py-2">
          <span className="h-2.5 w-2.5 rounded-full bg-rose-500/70" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500/70" />
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
          <span className="ml-2 font-mono text-[11px] text-slate-500">rift &mdash; pipeline log</span>
        </div>

        {/* Log body */}
        <ul className="max-h-80 overflow-y-auto p-3 scroll-smooth">
          {liveLogs.map((entry) => (
            <LogRow key={entry.id} entry={entry} />
          ))}
          <li ref={bottomRef} aria-hidden="true" />
        </ul>
      </div>
    </section>
  );
};

export default LiveLogPanel;
