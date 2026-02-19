const stages = ["Cloning", "Testing", "Fixing", "Pushing", "Verifying", "Done"];

const ProgressTracker = ({ results }) => {
  if (!results?.progress) return null;

  const { current, index } = results.progress;

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <p className="section-title">Pipeline Progress</p>
      <h2 className="mt-2 text-xl font-semibold text-slate-50">Agent Workflow</h2>

      <div className="mt-5 flex items-center gap-1 overflow-x-auto">
        {stages.map((stage, i) => {
          const done = i < index;
          const active = i === index;
          return (
            <div key={stage} className="flex items-center gap-1">
              <div
                className={`flex h-9 items-center rounded-lg border px-3 text-xs font-semibold transition-all ${
                  done
                    ? "border-emerald-400/50 bg-emerald-500/20 text-emerald-200"
                    : active
                    ? "border-cyan-400/50 bg-cyan-500/20 text-cyan-100 animate-pulse"
                    : "border-slate-600/40 bg-slate-900/45 text-slate-500"
                }`}
              >
                {done ? "✓ " : active ? "● " : ""}
                {stage}
              </div>
              {i < stages.length - 1 && (
                <span
                  className={`text-xs ${
                    done ? "text-emerald-400" : "text-slate-600"
                  }`}
                >
                  →
                </span>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
};

export default ProgressTracker;
