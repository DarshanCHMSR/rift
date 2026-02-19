import { Suspense, lazy, useEffect } from "react";
import InputSection from "./components/InputSection";
import RunSummaryCard from "./components/RunSummaryCard";
import RunHistoryDropdown from "./components/RunHistoryDropdown";
import ErrorLogModal from "./components/ErrorLogModal";
import { useAgentStore } from "./store/useAgentStore";

const ScoreBreakdownPanel = lazy(() => import("./components/ScoreBreakdownPanel"));
const CICDTimeline = lazy(() => import("./components/CICDTimeline"));
const FixesAppliedTable = lazy(() => import("./components/FixesAppliedTable"));
const ProgressTracker = lazy(() => import("./components/ProgressTracker"));
const LiveLogPanel = lazy(() => import("./components/LiveLogPanel"));

const App = () => {
  const results = useAgentStore((state) => state.results);
  const loadLatestResults = useAgentStore((state) => state.loadLatestResults);
  const toggleErrorLog = useAgentStore((state) => state.toggleErrorLog);

  useEffect(() => {
    loadLatestResults();
  }, [loadLatestResults]);

  return (
    <main className="relative min-h-screen px-4 py-8 md:px-6 lg:px-10">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-20 top-10 h-72 w-72 rounded-full bg-cyan-500/20 blur-3xl animate-pulseGlow" />
        <div className="absolute bottom-10 right-0 h-80 w-80 rounded-full bg-fuchsia-500/15 blur-3xl animate-pulseGlow" />
      </div>

      <div className="mx-auto grid w-full max-w-7xl grid-cols-1 gap-6">
        {/* Top bar: history dropdown + event log button */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <RunHistoryDropdown />
          {results && (
            <button
              onClick={toggleErrorLog}
              className="rounded-lg border border-slate-600/40 bg-slate-800/60 px-3 py-2 text-xs font-medium text-slate-300 transition hover:bg-slate-700/60"
            >
              View Event Log
            </button>
          )}
        </div>

        <InputSection />
        <RunSummaryCard results={results} />

        <Suspense
          fallback={
            <div className="glass-panel rounded-2xl border border-slate-700/60 p-6 text-sm text-slate-300">
              Loading dashboard panels...
            </div>
          }
        >
          <ProgressTracker results={results} />
          <LiveLogPanel />
          <section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <ScoreBreakdownPanel results={results} />
            <CICDTimeline results={results} />
          </section>
          <FixesAppliedTable results={results} />
        </Suspense>
      </div>

      <ErrorLogModal />
    </main>
  );
};

export default App;
