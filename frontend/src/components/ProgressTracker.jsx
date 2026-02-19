import { useAgentStore } from "../store/useAgentStore";

const STAGE_LIST = ["Cloning", "Testing", "Fixing", "Pushing", "Verifying", "Done"];

// Map elapsed seconds → active stage index while a run is in progress
const ELAPSED_STAGE_MAP = [
  { after: 0,   index: 0 }, // Cloning
  { after: 20,  index: 1 }, // Testing
  { after: 80,  index: 2 }, // Fixing
  { after: 180, index: 3 }, // Pushing
  { after: 260, index: 4 }, // Verifying
  { after: 480, index: 5 }, // Done
];

const stageFromElapsed = (elapsed) => {
  let idx = 0;
  for (const s of ELAPSED_STAGE_MAP) {
    if (elapsed >= s.after) idx = s.index;
  }
  return idx;
};

const ProgressTracker = ({ results }) => {
  const loading = useAgentStore((s) => s.loading);
  const elapsedSeconds = useAgentStore((s) => s.elapsedSeconds);

  // While loading, derive stage from elapsed time
  if (loading) {
    const activeIdx = stageFromElapsed(elapsedSeconds);
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
