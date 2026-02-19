import { useMemo } from "react";
import { useAgentStore } from "../store/useAgentStore";

const fmtElapsed = (s) => {
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
};

const InputSection = () => {
  const form = useAgentStore((state) => state.form);
  const loading = useAgentStore((state) => state.loading);
  const elapsedSeconds = useAgentStore((state) => state.elapsedSeconds);
  const loadingStage = useAgentStore((state) => state.loadingStage);
  const setFormField = useAgentStore((state) => state.setFormField);
  const runAgent = useAgentStore((state) => state.runAgent);
  const cancelRun = useAgentStore((state) => state.cancelRun);
  const error = useAgentStore((state) => state.error);

  const canRun = useMemo(() => {
    return (
      !loading &&
      form.repo_url.trim().length > 0 &&
      form.team_name.trim().length > 0 &&
      form.leader_name.trim().length > 0
    );
  }, [form, loading]);

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!canRun) {
      return;
    }
    await runAgent();
  };

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <p className="section-title">Input Section</p>
      <h1 className="mt-2 text-2xl font-semibold text-slate-50 md:text-3xl">
        Autonomous CI/CD Healing Agent
      </h1>
      <p className="mt-2 text-sm text-slate-400">
        Launch automated repo analysis, test execution, fix generation, and CI/CD healing in one run.
      </p>

      <form onSubmit={onSubmit} className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <label className="block md:col-span-2">
          <span className="mb-2 block text-sm font-medium text-slate-200">GitHub Repository URL</span>
          <input
            className="input-base"
            type="url"
            placeholder="https://github.com/org/repo.git"
            value={form.repo_url}
            onChange={(e) => setFormField("repo_url", e.target.value)}
            required
          />
        </label>

        <label className="block">
          <span className="mb-2 block text-sm font-medium text-slate-200">Team Name</span>
          <input
            className="input-base"
            type="text"
            placeholder="Team Phoenix"
            value={form.team_name}
            onChange={(e) => setFormField("team_name", e.target.value)}
            required
          />
        </label>

        <label className="block">
          <span className="mb-2 block text-sm font-medium text-slate-200">Team Leader Name</span>
          <input
            className="input-base"
            type="text"
            placeholder="Alex Carter"
            value={form.leader_name}
            onChange={(e) => setFormField("leader_name", e.target.value)}
            required
          />
        </label>

        <label className="block">
          <span className="mb-2 block text-sm font-medium text-slate-200">Retry Limit</span>
          <input
            className="input-base font-mono"
            type="number"
            min="1"
            max="50"
            value={form.retry_limit}
            onChange={(e) => setFormField("retry_limit", e.target.value)}
            required
          />
        </label>

        <div className="flex items-end gap-2">
          <button
            type="submit"
            disabled={!canRun}
            className="relative inline-flex h-12 w-full items-center justify-center overflow-hidden rounded-xl border border-cyan-300/35 bg-cyan-400/20 px-5 font-semibold text-cyan-100 transition hover:bg-cyan-300/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <span className="inline-block h-4 w-4 animate-spinSlow rounded-full border-2 border-cyan-200 border-t-transparent" />
                Processing… {elapsedSeconds > 0 && (
                  <span className="font-mono text-xs opacity-80">{fmtElapsed(elapsedSeconds)}</span>
                )}
              </span>
            ) : (
              "Run Agent"
            )}
          </button>
          {loading && (
            <button
              type="button"
              onClick={cancelRun}
              className="inline-flex h-12 shrink-0 items-center justify-center rounded-xl border border-rose-400/40 bg-rose-500/15 px-4 text-sm font-semibold text-rose-300 transition hover:bg-rose-500/25"
            >
              Cancel
            </button>
          )}
        </div>
      </form>

      {loading && (
        <div className="mt-4 rounded-lg border border-cyan-300/20 bg-cyan-300/10 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <span className="animate-pulse text-sm text-cyan-100">{loadingStage}</span>
            <span className="shrink-0 font-mono text-xs text-cyan-300/70">{fmtElapsed(elapsedSeconds)}</span>
          </div>
          <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-cyan-900/40">
            <div
              className="h-full rounded-full bg-cyan-400/60 transition-all duration-1000"
              style={{ width: `${Math.min(100, (elapsedSeconds / 600) * 100)}%` }}
            />
          </div>
        </div>
      )}
      {error && (
        <div className="mt-4 rounded-lg border border-rose-300/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}
    </section>
  );
};

export default InputSection;

