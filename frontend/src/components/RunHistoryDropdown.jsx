import { useEffect } from "react";
import { useAgentStore } from "../store/useAgentStore";

const RunHistoryDropdown = () => {
  const runHistory = useAgentStore((s) => s.runHistory);
  const loadRunHistory = useAgentStore((s) => s.loadRunHistory);
  const loadRun = useAgentStore((s) => s.loadRun);

  useEffect(() => {
    loadRunHistory();
  }, [loadRunHistory]);

  if (!runHistory.length) return null;

  return (
    <div className="flex items-center gap-3">
      <label className="text-xs font-medium uppercase tracking-wider text-slate-400">
        History
      </label>
      <select
        className="rounded-lg border border-slate-600/40 bg-slate-900/50 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-400/60"
        defaultValue=""
        onChange={(e) => {
          if (e.target.value) loadRun(e.target.value);
        }}
      >
        <option value="">Select a past run...</option>
        {runHistory.map((run) => (
          <option key={run.id} value={run.id}>
            {run.id} — {run.team_name} — {run.final_status} — score {run.score}
          </option>
        ))}
      </select>
    </div>
  );
};

export default RunHistoryDropdown;
