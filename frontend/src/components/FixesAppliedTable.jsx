const statusClass = (status) =>
  status === "fixed"
    ? "border-emerald-300/40 bg-emerald-500/15 text-emerald-200"
    : "border-rose-300/40 bg-rose-500/15 text-rose-200";

const FixesAppliedTable = ({ results }) => {
  if (!results) {
    return null;
  }

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="section-title">Fixes Applied</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-50">Patch Details</h2>
        </div>
        <p className="rounded-lg border border-slate-500/45 bg-slate-800/60 px-3 py-1 font-mono text-xs text-slate-200">
          {results.fixesRows.length} entries
        </p>
      </div>

      <div className="mt-5 overflow-hidden rounded-xl border border-slate-600/40">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-900/85 text-slate-200">
              <tr>
                <th className="px-4 py-3">File</th>
                <th className="px-4 py-3">Bug Type</th>
                <th className="px-4 py-3">Line Number</th>
                <th className="px-4 py-3">Commit Message</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/70 bg-slate-900/40 text-slate-100">
              {results.fixesRows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    No fixes were generated for this run.
                  </td>
                </tr>
              )}
              {results.fixesRows.map((row) => (
                <tr key={row.id} className="hover:bg-slate-800/50">
                  <td className="px-4 py-3 font-mono text-xs">{row.file}</td>
                  <td className="px-4 py-3">{row.bugType}</td>
                  <td className="px-4 py-3 font-mono">{row.lineNumber}</td>
                  <td className="px-4 py-3 text-xs">{row.commitMessage}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${statusClass(
                        row.status
                      )}`}
                    >
                      {row.status === "fixed" ? "✓ Fixed" : "✗ Failed"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
};

export default FixesAppliedTable;

