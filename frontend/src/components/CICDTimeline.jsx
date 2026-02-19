const badgeClass = (result) => {
  if (result === "PASSED") {
    return "border-emerald-300/40 bg-emerald-500/15 text-emerald-200";
  }
  if (result === "FAILED") {
    return "border-rose-300/40 bg-rose-500/15 text-rose-200";
  }
  return "border-sky-300/40 bg-sky-500/15 text-sky-200";
};

const CICDTimeline = ({ results }) => {
  if (!results) {
    return null;
  }

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <p className="section-title">CI/CD Timeline</p>
      <h2 className="mt-2 text-xl font-semibold text-slate-50">Retry and Status History</h2>

      <div className="mt-5 grid grid-cols-1 gap-3">
        {results.timelineRows.length === 0 && (
          <div className="rounded-xl border border-slate-600/40 bg-slate-900/45 px-4 py-5 text-sm text-slate-400">
            Timeline entries are not available for this run yet.
          </div>
        )}

        {results.timelineRows.map((row) => (
          <article
            key={row.id}
            className="rounded-xl border border-slate-600/40 bg-slate-900/45 px-4 py-4 transition hover:border-slate-400/40"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-wider text-slate-400">Iteration Number</p>
                <p className="font-mono text-lg text-slate-100">{row.iteration}</p>
              </div>
              <span
                className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wider ${badgeClass(
                  row.result
                )}`}
              >
                {row.result}
              </span>
            </div>

            <div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-300">
              <span>Retry Count: {row.retryCount}</span>
              <span className="font-mono">Timestamp: {new Date(row.timestamp).toLocaleString()}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
};

export default CICDTimeline;

