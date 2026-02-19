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
const RUN_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes hard cap

// ── Dynamic timing helpers ────────────────────────────────────────────────────
// Estimate total run seconds based on retry_limit.
// Base: ~60s (connect + clone + first Docker pull + first test)
// Per retry cycle: ~90s (test run + parse + fix + commit + push)
export const estimateRunSeconds = (retryLimit) =>
  Math.max(90, 60 + Math.round(safeNumber(retryLimit, 5)) * 90);

// Build stage-label thresholds scaled to the estimated total time.
export const buildLoadingStages = (retryLimit) => {
  const est = estimateRunSeconds(retryLimit);
  return [
    { after: 0,                       label: "Connecting to backend…" },
    { after: 5,                       label: "Cloning repository into workspace…" },
    { after: 20,                      label: "Detecting test framework…" },
    { after: 30,                      label: "Spinning up Docker sandbox…" },
    { after: 50,                      label: "Running test suite inside container…" },
    { after: Math.round(est * 0.35),  label: "Parsing errors and generating fixes…" },
    { after: Math.round(est * 0.60),  label: "Applying fixes and committing changes…" },
    { after: Math.round(est * 0.78),  label: "Pushing branch to GitHub…" },
    { after: Math.round(est * 0.88),  label: "Running sandbox verification…" },
    { after: Math.round(est * 0.96),  label: "Scoring and cleaning up…" },
  ];
};

const getLabelForElapsed = (stages, elapsed) => {
  let label = stages[0].label;
  for (const s of stages) {
    if (elapsed >= s.after) label = s.label;
  }
  return label;
};

// Build a log entry object.
let _logSeq = 0;
const mkLog = (level, message, source = "frontend") => ({
  id: ++_logSeq,
  ts: new Date().toISOString(),
  level,   // "info" | "success" | "warn" | "error"
  source,
  message,
});

// Convert a backend cicd-timeline event into a log entry.
const timelineEventToLog = (ev, idx) => {
  const stage = ev?.stage ?? "";
  const status = ev?.status ?? "";
  const details = ev?.details ?? {};
  const ts = ev?.timestamp ?? new Date().toISOString();

  const SUCCESS_STATUSES = new Set([
    "started", "repo_ready", "tests_passed", "branch_pushed",
    "sandbox_verification", "finished", "fixes_applied", "patches_generated",
    "commit_attempted", "interim_push",
  ]);
  const WARN_STATUSES = new Set([
    "no_fixes_applied", "no_parseable_errors", "retry_scheduled",
    "skipped", "timeout",
  ]);
  const ERROR_STATUSES = new Set([
    "clone_failed", "tests_failed", "sandbox_verification_failed",
  ]);

  let level = "info";
  if (SUCCESS_STATUSES.has(status)) level = "success";
  else if (WARN_STATUSES.has(status)) level = "warn";
  else if (ERROR_STATUSES.has(status)) level = "error";

  const detailStr = Object.keys(details).length
    ? " " + Object.entries(details)
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join(" ")
    : "";

  return {
    id: `tl-${idx}`,
    ts,
    level,
    source: stage,
    message: `[${stage}] ${status}${detailStr}`,
  };
};

export const useAgentStore = create((set, get) => ({
  form: { ...initialForm },
  loading: false,
  elapsedSeconds: 0,
  estimatedTotalSeconds: 510, // updated at run start based on retry_limit
  loadingStage: "",
  error: "",
  results: null,
  runHistory: [],
  showErrorLog: false,
  errorLog: "",
  liveLogs: [],           // [{id, ts, level, source, message}]

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
    set((s) => ({
      loading: false,
      elapsedSeconds: 0,
      loadingStage: "",
      error: "Run cancelled by user.",
      liveLogs: [
        ...s.liveLogs,
        mkLog("warn", "Run cancelled by user."),
      ],
    }));
  },

  runAgent: async () => {
    const { form } = get();
    const retryLimit = safeNumber(form.retry_limit, 5);
    const dynamicStages = buildLoadingStages(retryLimit);
    const estimatedTotal = estimateRunSeconds(retryLimit);

    // Cancel any previous in-flight request
    if (_abortController) _abortController.abort();
    _abortController = new AbortController();
    const signal = _abortController.signal;

    // Reset logs and start timer
    if (_timerInterval) clearInterval(_timerInterval);
    let elapsed = 0;
    let lastLabel = dynamicStages[0].label;

    set({
      loading: true,
      error: "",
      errorLog: "",
      elapsedSeconds: 0,
      estimatedTotalSeconds: estimatedTotal,
      loadingStage: lastLabel,
      liveLogs: [
        mkLog("info", `Run started — repo: ${form.repo_url.trim()}`),
        mkLog("info", `Team: ${form.team_name.trim()} / Leader: ${form.leader_name.trim()}`),
        mkLog("info", `Retry limit: ${retryLimit}  |  Estimated runtime: ~${estimatedTotal}s`),
        mkLog("info", lastLabel),
      ],
    });

    _timerInterval = setInterval(() => {
      elapsed += 1;
      const newLabel = getLabelForElapsed(dynamicStages, elapsed);
      const labelChanged = newLabel !== lastLabel;
      lastLabel = newLabel;
      set((s) => ({
        elapsedSeconds: elapsed,
        loadingStage: newLabel,
        // Append a log entry only when the stage label changes
        liveLogs: labelChanged
          ? [...s.liveLogs, mkLog("info", newLabel)]
          : s.liveLogs,
      }));
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
      set((s) => ({ liveLogs: [...s.liveLogs, mkLog("info", "POST /run → sending request to backend…")] }));

      const postResponse = await fetch(`${API_BASE}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({
          repo_url: form.repo_url.trim(),
          team_name: form.team_name.trim(),
          leader_name: form.leader_name.trim(),
          retry_limit: retryLimit,
        }),
      });

      if (!postResponse.ok) {
        const failure = await postResponse.json().catch(() => ({}));
        throw new Error(failure?.detail || `Server error ${postResponse.status}`);
      }

      set((s) => ({ liveLogs: [...s.liveLogs, mkLog("success", `POST /run → ${postResponse.status} OK — pipeline finished`)] }));

      const postData = await postResponse.json();

      set((s) => ({ liveLogs: [...s.liveLogs, mkLog("info", "GET /results → fetching final results…")] }));
      const getResponse = await fetch(`${API_BASE}/results`, { signal });
      const getData = getResponse.ok ? await getResponse.json() : postData;

      stopTimer();

      // Build real timeline log entries from backend cicd timeline
      const rawTimeline = Array.isArray(getData?.["cicd timeline"])
        ? getData["cicd timeline"]
        : [];
      const timelineLogs = rawTimeline.map(timelineEventToLog);
      const finalStatus = getData?.final_status ?? "FAILED";
      const score = getData?.score_breakdown?.final ?? getData?.score ?? 0;

      set((s) => ({
        results: normalizeResult(getData, retryLimit),
        loading: false,
        elapsedSeconds: elapsed,
        loadingStage: "",
        liveLogs: [
          ...s.liveLogs,
          mkLog("info", "─── Backend pipeline events ───────────────────────"),
          ...timelineLogs,
          mkLog("info", "───────────────────────────────────────────────────"),
          mkLog(
            finalStatus === "PASSED" ? "success" : finalStatus === "SANDBOX_FAILED" ? "warn" : "error",
            `Run complete — status: ${finalStatus}  |  score: ${score}  |  elapsed: ${elapsed}s`,
          ),
        ],
      }));

      get().loadRunHistory();
    } catch (err) {
      stopTimer();
      const isTimeout = elapsed >= RUN_TIMEOUT_MS / 1000;
      const msg =
        err?.name === "AbortError"
          ? isTimeout
            ? "Request timed out after 15 minutes. The backend may still be running."
            : "Run cancelled by user."
          : err instanceof Error
          ? err.message
          : "Unexpected error occurred";
      set((s) => ({
        loading: false,
        elapsedSeconds: 0,
        loadingStage: "",
        error: msg,
        liveLogs: [...s.liveLogs, mkLog("error", `Run failed: ${msg}`)],
      }));
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

