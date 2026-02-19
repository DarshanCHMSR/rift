import { create } from "zustand";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
    const re = /^([A-Z_]+) error in (.+?) line (\d+) -> Fix: (.+)$/;
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
      if (statusText === "tests_passed") {
        row.result = "PASSED";
      }
      if (statusText === "no_fixes_applied" || statusText === "no_parseable_errors") {
        row.result = "FAILED";
      }
      if (statusText === "retry_scheduled") {
        row.result = row.result === "RUNNING" ? "FAILED" : row.result;
      }
    }
  });

  return [...attemptMap.values()].sort((a, b) => a.iteration - b.iteration);
};

const normalizeResult = (raw, retryLimit) => {
  const finalStatus = raw?.final_status ?? "FAILED";
  const fixes = Array.isArray(raw?.fixes) ? raw.fixes : [];
  const timeline = Array.isArray(raw?.["cicd timeline"]) ? raw["cicd timeline"] : [];
  const commitsOver20 = Math.max(0, fixes.length - 20);
  const speedBonus = safeNumber(raw?.time_taken, 0) < 300 ? 10 : 0;
  const efficiencyPenalty = commitsOver20 * 2;
  const finalScore = safeNumber(raw?.score, 0);

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
      base: 100,
      speedBonus,
      efficiencyPenalty,
      final: finalScore,
    },
    fixesRows: fixes.map((entry, index) => parseFixLine(entry, index, finalStatus)),
    timelineRows: normalizeTimeline(timeline, retryLimit),
  };
};

export const useAgentStore = create((set, get) => ({
  form: { ...initialForm },
  loading: false,
  error: "",
  results: null,

  setFormField: (field, value) =>
    set((state) => ({ form: { ...state.form, [field]: value } })),

  runAgent: async () => {
    const { form } = get();
    set({ loading: true, error: "" });

    try {
      const postResponse = await fetch(`${API_BASE}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_url: form.repo_url.trim(),
          team_name: form.team_name.trim(),
          leader_name: form.leader_name.trim(),
          retry_limit: safeNumber(form.retry_limit, 5),
        }),
      });

      if (!postResponse.ok) {
        const failure = await postResponse.json().catch(() => ({}));
        throw new Error(failure?.detail || "Failed to run healing workflow");
      }

      const postData = await postResponse.json();

      const getResponse = await fetch(`${API_BASE}/results`);
      const getData = getResponse.ok ? await getResponse.json() : postData;

      set({
        results: normalizeResult(getData, safeNumber(form.retry_limit, 5)),
        loading: false,
      });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : "Unexpected error occurred",
      });
    }
  },

  loadLatestResults: async () => {
    try {
      const res = await fetch(`${API_BASE}/results`);
      if (!res.ok) {
        return;
      }
      const data = await res.json();
      const retryLimit = safeNumber(get().form.retry_limit, 5);
      set({ results: normalizeResult(data, retryLimit) });
    } catch {
      // Intentionally ignore cold-start errors for initial page load.
    }
  },
}));

