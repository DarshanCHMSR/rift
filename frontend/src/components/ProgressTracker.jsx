import { useAgentStore, estimateRunSeconds } from "../store/useAgentStore";

const STAGE_LIST = ["Cloning", "Testing", "Fixing", "Pushing", "Verifying", "Done"];

// Build stage-index thresholds dynamically based on estimated total seconds.
// Each element: { after: seconds, index: stageIndex }
const buildElapsedMap = (retryLimit) => {
  const est = estimateRunSeconds(retryLimit);
  return [
    { after: 0,                       index: 0 }, // Cloning
    { after: 20,                      index: 1 }, // Testing
    { after: Math.round(est * 0.33),  index: 2 }, // Fixing
    { after: Math.round(est * 0.70),  index: 3 }, // Pushing
    { after: Math.round(est * 0.83),  index: 4 }, // Verifying
    { after: Math.round(est * 0.97),  index: 5 }, // Done
  ];
};

const stageFromElapsed = (map, elapsed) => {
  let idx = 0;
  for (const s of map) {
    if (elapsed >= s.after) idx = s.index;
  }
  return idx;
};

const ProgressTracker = ({ results }) => {
  const loading = useAgentStore((s) => s.loading);
  const elapsedSeconds = useAgentStore((s) => s.elapsedSeconds);
  const retryLimit = useAgentStore((s) => s.form.retry_limit);
  const elapsedMap = buildElapsedMap(retryLimit);

  // While loading, derive stage from elapsed time (dynamic per retry_limit)
  if (loading) {
    const activeIdx = stageFromElapsed(elapsedMap, elapsedSeconds);
    return (
      <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
        <p className="section-title">Pipeline Progress</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-50">Agent Workflow — Running</h2>
        <div className="mt-5 flex items-center gap-1 overflow-x-auto">
          {STAGE_LIST.map((stage, i) => {
            const done = i < activeIdx;
            const active = i === activeIdx;
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
                {i < STAGE_LIST.length - 1 && (
                  <span className={`text-xs ${done ? "text-emerald-400" : "text-slate-600"}`}>→</span>
                )}
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  if (!results?.progress) return null;

  const { index } = results.progress;

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <p className="section-title">Pipeline Progress</p>
      <h2 className="mt-2 text-xl font-semibold text-slate-50">Agent Workflow</h2>

      <div className="mt-5 flex items-center gap-1 overflow-x-auto">
        {STAGE_LIST.map((stage, i) => {
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
              {i < STAGE_LIST.length - 1 && (
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
