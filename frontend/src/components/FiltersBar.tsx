import type { FilterState, Stats } from "../types";
import { useApp } from "./AppContext";
import StationPicker from "./StationPicker";

interface Props {
  value: FilterState;
  onChange: (f: FilterState) => void;
  facets?: Stats["facets"];
  lines?: { key: string; label: string }[];
  routes?: { key: string; label: string }[];
  compact?: boolean;
}

export function activeFilterCount(f: FilterState): number {
  return Object.entries(f).filter(([k, v]) => v && !["include_demo", "station_name"].includes(k)).length;
}

export default function FiltersBar({ value, onChange, facets, lines, routes, compact }: Props) {
  const { options } = useApp();
  const set = (k: string, v: string) => onChange({ ...value, [k]: v });
  return (
    <div className="stack">
      <div className="filters">
        <label className="field">
          Du
          <input type="date" value={value.date_from ?? ""} onChange={(e) => set("date_from", e.target.value)} />
        </label>
        <label className="field">
          Au
          <input type="date" value={value.date_to ?? ""} onChange={(e) => set("date_to", e.target.value)} />
        </label>
        <label className="field">
          Pays
          <select value={value.country ?? ""} onChange={(e) => set("country", e.target.value)}>
            <option value="">Tous</option>
            {Object.entries(options?.countries ?? {}).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Transporteur
          <select value={value.carrier ?? ""} onChange={(e) => set("carrier", e.target.value)}>
            <option value="">Tous</option>
            {(facets?.carriers ?? []).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Type de train
          <select value={value.train_type ?? ""} onChange={(e) => set("train_type", e.target.value)}>
            <option value="">Tous</option>
            {Object.entries(options?.train_types ?? {}).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        {!compact && (
          <>
            <label className="field">
              Motif
              <select value={value.reason ?? ""} onChange={(e) => set("reason", e.target.value)}>
                <option value="">Tous</option>
                {Object.entries(options?.reasons ?? {}).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Statut
              <select value={value.status ?? ""} onChange={(e) => set("status", e.target.value)}>
                <option value="">Tous</option>
                {Object.entries(options?.statuses ?? {}).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Ligne physique
              <select value={value.line ?? ""} onChange={(e) => set("line", e.target.value)}>
                <option value="">Toutes</option>
                {(lines ?? []).map((l) => (
                  <option key={l.key} value={l.key}>{l.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Ligne commerciale
              <select value={value.route ?? ""} onChange={(e) => set("route", e.target.value)}>
                <option value="">Toutes</option>
                {(routes ?? []).map((l) => (
                  <option key={l.key} value={l.key}>{l.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Gare
              <StationPicker
                value={value.station ? { id: value.station, name: value.station_name ?? value.station } : null}
                placeholder="Toutes"
                onSelect={(s) => onChange({ ...value, station: s?.id ?? "", station_name: s?.name ?? "" })}
              />
            </label>
          </>
        )}
      </div>
      <div className="row">
        <label className="check">
          <input type="checkbox" checked={value.include_demo !== "false"} onChange={(e) => set("include_demo", e.target.checked ? "" : "false")} />
          Inclure les exemples fictifs
        </label>
        <label className="check">
          <input type="checkbox" checked={value.confirmed_only === "true"} onChange={(e) => set("confirmed_only", e.target.checked ? "true" : "")} />
          Correspondances confirmées uniquement
        </label>
        <span className="grow" />
        {activeFilterCount(value) > 0 && (
          <button className="btn ghost sm" onClick={() => onChange({ include_demo: value.include_demo ?? "" })}>
            Réinitialiser les filtres
          </button>
        )}
      </div>
    </div>
  );
}

export function filterQuery(f: FilterState): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(f)) if (v && k !== "station_name") out[k] = v;
  return out;
}
