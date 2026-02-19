const StatusBadge = ({ status }) => {
  const s = String(status).toUpperCase();
  const styles = {
    PASSED: "border-emerald-300/40 bg-emerald-500/15 text-emerald-200",
    FAILED: "border-rose-300/40 bg-rose-500/15 text-rose-200",
    SANDBOX_FAILED: "border-orange-300/40 bg-orange-500/15 text-orange-200",
  };
  const cls = styles[s] || styles.FAILED;
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider ${cls}`}
    >
      {s === "SANDBOX_FAILED" ? "⚠ SANDBOX FAIL" : s === "PASSED" ? "✓ PASSED" : "✗ FAILED"}
    </span>
  );
};

const RunSummaryCard = ({ results }) => {
  if (!results) {
    return null;
  }

  const sb = results.sandbox ?? {};

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

      {/* Sandbox verification panel */}
      {sb && !sb.skipped && (
        <div className="mt-4 rounded-xl border border-slate-600/40 bg-slate-900/45 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-400">Sandbox Verification</p>
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            <span className={sb.passed ? "text-emerald-300" : "text-rose-300"}>
              {sb.passed ? "✓ Passed" : "✗ Failed"}
            </span>
            <span className="text-slate-300">Exit Code: {sb.exit_code}</span>
            <span className="text-slate-300">Duration: {sb.duration}s</span>
            <span className="font-mono text-slate-400">Branch: {sb.branch}</span>
          </div>
        </div>
      )}
    </section>
  );
};

export default RunSummaryCard;

