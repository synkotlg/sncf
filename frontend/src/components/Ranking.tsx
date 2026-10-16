import { useState } from "react";
import { money, number } from "../format";
import type { RankItem, Ranking } from "../types";
import { METRIC_LABEL, type Metric } from "./charts";

export function MetricSwitch({ value, onChange, withMean = true }: { value: Metric; onChange: (m: Metric) => void; withMean?: boolean }) {
  const opts: Metric[] = withMean ? ["count", "total", "mean"] : ["count", "total"];
  return (
    <div className="seg" role="group" aria-label="Mesure">
      {opts.map((m) => (
        <button key={m} className={value === m ? "on" : ""} onClick={() => onChange(m)} type="button">
          {m === "count" ? "Nombre" : m === "total" ? "Montant total" : "Moyenne"}
        </button>
      ))}
    </div>
  );
}

interface Props {
  title: string;
  subtitle?: string;
  ranking?: Ranking;
  limit?: number;
  onPick?: (item: RankItem) => void;
  defaultMetric?: Metric;
  emptyText?: string;
}

// Classement : la mesure choisie trie et dimensionne la barre ; les deux autres restent affichées.
export default function RankingCard({ title, subtitle, ranking, limit = 10, onPick, defaultMetric = "count", emptyText }: Props) {
  const [metric, setMetric] = useState<Metric>(defaultMetric);
  const items = ranking ? (metric === "count" ? ranking.by_count : metric === "total" ? ranking.by_total : ranking.by_mean).slice(0, limit) : [];
  const val = (i: RankItem) => (metric === "count" ? i.count : metric === "total" ? i.total : i.mean ?? 0);
  const max = Math.max(1e-9, ...items.map(val));
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>{title}</h2>
          <p>{subtitle ?? `Classé par ${METRIC_LABEL[metric].toLowerCase()}`}</p>
        </div>
        <MetricSwitch value={metric} onChange={setMetric} />
      </div>
      {items.length === 0 ? (
        <div className="empty">{emptyText ?? "Aucune donnée pour ces filtres."}</div>
      ) : (
        <div className="rank">
          {items.map((it, i) => (
            <div
              key={it.key}
              className="rank-row"
              style={{ cursor: onPick ? "pointer" : undefined }}
              onClick={onPick ? () => onPick(it) : undefined}
              title={`${it.label}\nNombre : ${it.count} · Total : ${money(it.total)} · Moyenne : ${money(it.mean)} · Médiane : ${money(it.median)}`}
            >
              <span className="pos">{i + 1}</span>
              <div className="lab">
                <div className="name">{it.label}</div>
                <div className="bar" style={{ width: `${Math.max(1.5, (val(it) / max) * 100)}%` }} />
              </div>
              <div className="vals">
                <div className="main-v">{metric === "count" ? `${number(it.count)}` : money(val(it))}</div>
                <div className="sub-v">
                  {metric === "count" ? money(it.total) : `${number(it.count)} amende${it.count > 1 ? "s" : ""}`}
                  {metric !== "mean" && it.mean !== null ? ` · moy. ${money(it.mean)}` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {ranking && ranking.missing > 0 && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {ranking.missing} amende(s) sans cette information, non classée(s) ici.
        </p>
      )}
    </div>
  );
}
