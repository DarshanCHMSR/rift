import { useAgentStore } from "../store/useAgentStore";

const ErrorLogModal = () => {
  const showErrorLog = useAgentStore((s) => s.showErrorLog);
  const toggleErrorLog = useAgentStore((s) => s.toggleErrorLog);
  const results = useAgentStore((s) => s.results);

  if (!showErrorLog || !results) return null;

  // Flatten raw timeline events into readable log lines
  const lines = (results.rawTimeline ?? []).map(
    (ev) =>
      `[${ev.timestamp}] ${ev.stage}.${ev.status} ${
        ev.details ? JSON.stringify(ev.details) : ""
      }`
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={toggleErrorLog}
    >
      <div
        className="mx-4 max-h-[80vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-slate-600/40 bg-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-700/60 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-100">
            Raw Event Log ({lines.length} events)
          </h3>
          <button
            onClick={toggleErrorLog}
            className="rounded-lg border border-slate-600/40 px-3 py-1 text-xs text-slate-300 transition hover:bg-slate-800"
          >
            Close
          </button>
        </div>
        <div className="max-h-[68vh] overflow-y-auto p-5">
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-300">
            {lines.join("\n") || "No events recorded."}
          </pre>
        </div>
      </div>
    </div>
  );
};

export default ErrorLogModal;
