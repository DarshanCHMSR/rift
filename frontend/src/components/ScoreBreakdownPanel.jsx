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

  const breakdown = results.scoreBreakdown;
  const chartData = [
    { name: "Base", value: breakdown.base, color: "#38bdf8" },
    { name: "Speed +", value: breakdown.speedBonus, color: "#22c55e" },
    { name: "Penalty -", value: -breakdown.efficiencyPenalty, color: "#f43f5e" },
    { name: "Final", value: breakdown.final, color: "#fbbf24" },
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
          <p className="text-3xl font-bold text-amber-200">{breakdown.final}</p>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Base score</p>
          <p className="mt-1 font-mono text-lg text-sky-300">100</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Speed bonus</p>
          <p className="mt-1 font-mono text-lg text-emerald-300">+{breakdown.speedBonus}</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Efficiency penalty</p>
          <p className="mt-1 font-mono text-lg text-rose-300">-{breakdown.efficiencyPenalty}</p>
        </div>
        <div className="metric-tile">
          <p className="text-sm text-slate-300">Formula</p>
          <p className="mt-1 font-mono text-xs text-slate-200">100 + speed bonus - commit penalty</p>
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

