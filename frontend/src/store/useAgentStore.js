import { create } from "zustand";

// Empty string = relative paths, routed through the Vite dev proxy to port 8000.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

const initialForm = {
  repo_url: "",
  team_name: "",
  leader_name: "",
  retry_limit: 5,
};

const safeNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const parseFixLine = (entry, index, finalStatus) => {
  if (typeof entry === "object" && entry !== null) {
    return {
      id: `${entry.file ?? "unknown"}-${entry.line ?? index}`,
      file: entry.file ?? "unknown",
      bugType: entry.bug_type ?? "LOGIC",
      lineNumber: safeNumber(entry.line, 1),
      commitMessage: entry.commit_message ?? "[AI-AGENT] Applied automated fix",
      status: entry.status ?? (finalStatus === "PASSED" ? "fixed" : "failed"),
    };
  }

  if (typeof entry === "string") {
    const re = /^([A-Z_]+) error in (.+?) line (\d+) → Fix: (.+)$/;
    const match = entry.match(re);
    if (match) {
      return {
        id: `${match[2]}-${match[3]}-${index}`,
        file: match[2],
        bugType: match[1],
        lineNumber: safeNumber(match[3], 1),
        commitMessage: `[AI-AGENT] ${match[4]}`,
        status: finalStatus === "PASSED" ? "fixed" : "failed",
      };
    }
  }

  return {
    id: `unknown-${index}`,
    file: "unknown",
    bugType: "LOGIC",
    lineNumber: index + 1,
    commitMessage: "[AI-AGENT] Applied automated fix",
    status: finalStatus === "PASSED" ? "fixed" : "failed",
  };
};

const normalizeTimeline = (timeline = [], retryLimit = 5) => {
  const attemptMap = new Map();

  timeline.forEach((item, index) => {
    const details = item?.details ?? {};
    const attemptNum = safeNumber(details.attempt, 0);
    const statusText = String(item?.status ?? "").toLowerCase();
    const timestamp = item?.timestamp ?? new Date().toISOString();

    if (attemptNum > 0 && !attemptMap.has(attemptNum)) {
      attemptMap.set(attemptNum, {
        id: `attempt-${attemptNum}-${index}`,
        iteration: attemptNum,
        result: "RUNNING",
        retryCount: `${attemptNum}/${retryLimit}`,
        timestamp,
      });
    }

    if (attemptNum > 0 && attemptMap.has(attemptNum)) {
      const row = attemptMap.get(attemptNum);
      if (statusText === "tests_passed") row.result = "PASSED";
      if (statusText === "no_fixes_applied" || statusText === "no_parseable_errors")
        row.result = "FAILED";
      if (statusText === "retry_scheduled")
        row.result = row.result === "RUNNING" ? "FAILED" : row.result;
    }
  });

  return [...attemptMap.values()].sort((a, b) => a.iteration - b.iteration);
};

/** Derive progress stage from the latest timeline entries. */
const deriveProgress = (timeline = []) => {
  const stages = ["Cloning", "Testing", "Fixing", "Pushing", "Verifying", "Done"];
  const stageMap = {
    repo_ready: "Testing",
    tests_executed: "Fixing",
    fixes_applied: "Pushing",
    patches_generated: "Pushing",
    branch_pushed: "Verifying",
    sandbox_verification: "Done",
    finished: "Done",
    timeout: "Done",
  };
  let current = "Cloning";
  for (const ev of timeline) {
    const mapped = stageMap[ev?.status];
    if (mapped && stages.indexOf(mapped) > stages.indexOf(current)) {
      current = mapped;
    }
  }
  return { stages, current, index: stages.indexOf(current) };
};

const normalizeResult = (raw, retryLimit) => {
  const finalStatus = raw?.final_status ?? "FAILED";
  const fixes = Array.isArray(raw?.fixes) ? raw.fixes : [];
  const timeline = Array.isArray(raw?.["cicd timeline"]) ? raw["cicd timeline"] : [];

  // Use backend score_breakdown if available; fall back to local calc
  const bd = raw?.score_breakdown ?? {};
  const base = safeNumber(bd.base, 100);
  const speedBonus = safeNumber(bd.speed_bonus, raw?.time_taken < 300 ? 10 : 0);
  const commitPenalty = safeNumber(bd.commit_penalty, Math.max(0, fixes.length - 20) * 2);
  const sandboxPenalty = safeNumber(bd.sandbox_penalty, 0);
  const zeroFixBonus = safeNumber(bd.zero_fix_bonus, 0);
  const finalScore = safeNumber(bd.final ?? raw?.score, 0);

  return {
    repo_url: raw?.repo_url ?? "",
    team_name: raw?.team_name ?? "",
    leader_name: raw?.leader_name ?? "",
    branch_name: raw?.branch_name ?? "",
    total_failures: safeNumber(raw?.total_failures, 0),
    total_fixes: safeNumber(raw?.total_fixes, 0),
    final_status: finalStatus,
    time_taken: safeNumber(raw?.time_taken, 0),
    score: finalScore,
    scoreBreakdown: {
      base,
      speedBonus,
      commitPenalty,
      sandboxPenalty,
      zeroFixBonus,
      final: finalScore,
    },
    fixesRows: fixes.map((entry, index) => parseFixLine(entry, index, finalStatus)),
    timelineRows: normalizeTimeline(timeline, retryLimit),
    progress: deriveProgress(timeline),
    sandbox: raw?.sandbox_verification ?? {},
    rawTimeline: timeline,
  };
};

// Module-level refs for non-reactive artefacts
let _timerInterval = null;
let _abortController = null;
const RUN_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes

// Pipeline stage messages shown while loading
const LOADING_STAGES = [
  { after: 0,   label: "Connecting to backend…" },
  { after: 5,   label: "Cloning repository into workspace…" },
  { after: 20,  label: "Detecting test framework…" },
  { after: 30,  label: "Spinning up Docker sandbox…" },
  { after: 50,  label: "Running test suite inside container…" },
  { after: 90,  label: "Parsing errors and generating fixes…" },
  { after: 150, label: "Applying fixes and committing changes…" },
  { after: 240, label: "Pushing branch to GitHub…" },
  { after: 300, label: "Running sandbox verification…" },
  { after: 480, label: "Scoring and cleaning up…" },
];

const getLoadingStage = (elapsed) => {
  let label = LOADING_STAGES[0].label;
  for (const s of LOADING_STAGES) {
    if (elapsed >= s.after) label = s.label;
  }
  return label;
};

export const useAgentStore = create((set, get) => ({
  form: { ...initialForm },
  loading: false,
  elapsedSeconds: 0,
  loadingStage: "",
  error: "",
  results: null,
  runHistory: [],
  showErrorLog: false,
  errorLog: "",

  setFormField: (field, value) =>
    set((state) => ({ form: { ...state.form, [field]: value } })),

  toggleErrorLog: () => set((s) => ({ showErrorLog: !s.showErrorLog })),

  cancelRun: () => {
    if (_abortController) {
      _abortController.abort();
      _abortController = null;
    }
    if (_timerInterval) {
      clearInterval(_timerInterval);
      _timerInterval = null;
    }
    set({ loading: false, elapsedSeconds: 0, loadingStage: "", error: "Run cancelled by user." });
  },

  runAgent: async () => {
    const { form } = get();

    // Cancel any previous in-flight request
    if (_abortController) _abortController.abort();
    _abortController = new AbortController();
    const signal = _abortController.signal;

    // Start elapsed timer
    if (_timerInterval) clearInterval(_timerInterval);
    let elapsed = 0;
    set({ loading: true, error: "", errorLog: "", elapsedSeconds: 0, loadingStage: getLoadingStage(0) });
    _timerInterval = setInterval(() => {
      elapsed += 1;
      set({ elapsedSeconds: elapsed, loadingStage: getLoadingStage(elapsed) });
    }, 1000);

    // Hard 15-minute timeout
    const timeoutId = setTimeout(() => {
      if (_abortController) _abortController.abort();
    }, RUN_TIMEOUT_MS);

    const stopTimer = () => {
      clearInterval(_timerInterval);
      _timerInterval = null;
      clearTimeout(timeoutId);
    };

    try {
      const postResponse = await fetch(`${API_BASE}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({
          repo_url: form.repo_url.trim(),
          team_name: form.team_name.trim(),
          leader_name: form.leader_name.trim(),
          retry_limit: safeNumber(form.retry_limit, 5),
        }),
      });

      if (!postResponse.ok) {
        const failure = await postResponse.json().catch(() => ({}));
        throw new Error(failure?.detail || `Server error ${postResponse.status}`);
      }

      const postData = await postResponse.json();

      const getResponse = await fetch(`${API_BASE}/results`, { signal });
      const getData = getResponse.ok ? await getResponse.json() : postData;

      stopTimer();
      set({
        results: normalizeResult(getData, safeNumber(form.retry_limit, 5)),
        loading: false,
        elapsedSeconds: elapsed,
        loadingStage: "",
      });

      get().loadRunHistory();
    } catch (err) {
      stopTimer();
      const msg =
        err?.name === "AbortError"
          ? elapsed >= RUN_TIMEOUT_MS / 1000
            ? "Request timed out after 15 minutes. The backend may still be running."
            : "Run cancelled by user."
          : err instanceof Error
          ? err.message
          : "Unexpected error occurred";
      set({ loading: false, elapsedSeconds: 0, loadingStage: "", error: msg });
    }
  },

  loadLatestResults: async () => {
    try {
      const res = await fetch(`${API_BASE}/results`);
      if (!res.ok) return;
      const data = await res.json();
      const retryLimit = safeNumber(get().form.retry_limit, 5);
      set({ results: normalizeResult(data, retryLimit) });
    } catch {
      // Intentionally ignore cold-start errors for initial page load.
    }
  },

  loadRunHistory: async () => {
    try {
      const res = await fetch(`${API_BASE}/runs`);
      if (!res.ok) return;
      const data = await res.json();
      set({ runHistory: Array.isArray(data) ? data : [] });
    } catch {
      // ignore
    }
  },

  loadRun: async (runId) => {
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}`);
      if (!res.ok) return;
      const data = await res.json();
      const retryLimit = safeNumber(get().form.retry_limit, 5);
      set({ results: normalizeResult(data, retryLimit) });
    } catch {
      // ignore
    }
  },
}));

