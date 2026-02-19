import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const ScoreBreakdownPanel = ({ results }) => {
  if (!results) {
    return null;
  }

  const b = results.scoreBreakdown;
  const chartData = [
    { name: "Base", value: b.base, color: "#38bdf8" },
    { name: "Speed +", value: b.speedBonus, color: "#22c55e" },
    { name: "0-Fix +", value: b.zeroFixBonus, color: "#a3e635" },
    { name: "Commit -", value: -b.commitPenalty, color: "#f43f5e" },
    { name: "Sandbox -", value: -b.sandboxPenalty, color: "#fb923c" },
    { name: "Final", value: b.final, color: "#fbbf24" },
  ];

  return (
    <section className="glass-panel animate-riseIn rounded-2xl p-6 shadow-glow">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="section-title">Score Breakdown</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-50">Performance Scoring</h2>
        </div>
        <div className="rounded-xl border border-amber-300/40 bg-amber-300/10 px-4 py-2">
          <p className="text-xs uppercase tracking-wide text-amber-200/80">Final Score</p>
          <p className="text-3xl font-bold text-amber-200">{b.final}</p>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3">
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Base score</p>
          <p className="mt-1 font-mono text-lg text-sky-300">{b.base}</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Speed bonus</p>
          <p className="mt-1 font-mono text-lg text-emerald-300">+{b.speedBonus}</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Zero-fix bonus</p>
          <p className="mt-1 font-mono text-lg text-lime-300">+{b.zeroFixBonus}</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Commit penalty</p>
          <p className="mt-1 font-mono text-lg text-rose-300">-{b.commitPenalty}</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Sandbox penalty</p>
          <p className="mt-1 font-mono text-lg text-orange-300">-{b.sandboxPenalty}</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Formula</p>
          <p className="mt-1 font-mono text-xs text-slate-200">base + speed + 0fix − commit − sandbox (cap 0–120)</p>
        </div>
      </div>

      <div className="mt-6 h-64 w-full rounded-xl border border-slate-600/40 bg-slate-900/45 p-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="name" stroke="#cbd5e1" />
            <YAxis stroke="#cbd5e1" />
            <Tooltip
              cursor={{ fill: "rgba(15, 23, 42, 0.65)" }}
              contentStyle={{
                background: "#0f172a",
                border: "1px solid rgba(100, 116, 139, 0.5)",
                borderRadius: "12px",
              }}
            />
            <Bar dataKey="value" radius={[8, 8, 0, 0]}>
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
};

export default ScoreBreakdownPanel;

