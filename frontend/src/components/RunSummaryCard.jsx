const StatusBadge = ({ status }) => {
  const passed = String(status).toUpperCase() === "PASSED";
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider ${
        passed
          ? "border border-emerald-300/40 bg-emerald-500/15 text-emerald-200"
          : "border border-rose-300/40 bg-rose-500/15 text-rose-200"
      }`}
    >
      {passed ? "PASSED" : "FAILED"}
    </span>
  );
};

const RunSummaryCard = ({ results }) => {
  if (!results) {
    return null;
  }

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="section-title">Run Summary</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-50">Execution Overview</h2>
        </div>
        <StatusBadge status={results.final_status} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="metric-tile">
          <p className="text-xs uppercase tracking-wide text-slate-400">Repository URL</p>
          <p className="mt-1 break-all font-mono text-sm text-slate-100">{results.repo_url}</p>
        </div>
        <div className="metric-tile">
          <p className="text-xs uppercase tracking-wide text-slate-400">Branch Name</p>
          <p className="mt-1 break-all font-mono text-sm text-slate-100">{results.branch_name}</p>
        </div>
        <div className="metric-tile">
          <p className="text-xs uppercase tracking-wide text-slate-400">Team</p>
          <p className="mt-1 text-sm text-slate-100">
            {results.team_name} / {results.leader_name}
          </p>
        </div>
        <div className="metric-tile">
          <p className="text-xs uppercase tracking-wide text-slate-400">Time Taken</p>
          <p className="mt-1 font-mono text-sm text-slate-100">{results.time_taken}s</p>
        </div>
        <div className="metric-tile">
          <p className="text-xs uppercase tracking-wide text-slate-400">Total Failures</p>
          <p className="mt-1 text-lg font-semibold text-rose-200">{results.total_failures}</p>
        </div>
        <div className="metric-tile">
          <p className="text-xs uppercase tracking-wide text-slate-400">Total Fixes</p>
          <p className="mt-1 text-lg font-semibold text-emerald-200">{results.total_fixes}</p>
        </div>
      </div>
    </section>
  );
};

export default RunSummaryCard;

