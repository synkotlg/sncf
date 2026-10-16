import { useEffect, useState } from "react";
import { api, qs } from "../api";
import type { FieldValue, StationCandidate } from "../types";
import { useApp } from "./AppContext";
import StationPicker from "./StationPicker";

export type FineValues = Record<string, any>;

interface MatchInfo {
  station_id: string | null;
  name: string | null;
  confidence: number;
  ambiguous: boolean;
  reason: string;
  candidates: StationCandidate[];
}

function Conf({ meta }: { meta?: FieldValue }) {
  if (!meta || meta.value === null || meta.value === undefined) return null;
  const pct = Math.round((meta.confidence ?? 0) * 100);
  return <span className={`conf ${meta.uncertain ? "low" : "ok"}`} title="Indice de confiance de l'extraction automatique">{meta.uncertain ? "incertain" : "détecté"} {pct} %</span>;
}

function Hint({ meta, onPick }: { meta?: FieldValue; onPick?: (v: any) => void }) {
  if (!meta) return null;
  const alts = (meta.alternatives ?? []).filter((a) => a !== null && a !== "");
  return (
    <>
      {meta.note && <span className={`hint ${meta.uncertain ? "warn" : ""}`}>{meta.note}</span>}
      {alts.length > 0 && (
        <span className="hint">
          Autres valeurs lues :{" "}
          {alts.slice(0, 5).map((a, i) => (
            <button key={i} type="button" className="btn ghost sm" style={{ padding: "0 5px" }} onClick={() => onPick?.(a)}>{String(a)}</button>
          ))}
        </span>
      )}
      {meta.evidence && <span className="hint" title={meta.evidence}>Extrait : « {meta.evidence.slice(0, 90)}{meta.evidence.length > 90 ? "…" : ""} »</span>}
    </>
  );
}

function StationField({ name, idKey, title, values, set, meta, country }: {
  name: string; idKey: string; title: string; values: FineValues; set: (patch: FineValues) => void; meta?: FieldValue; country?: string;
}) {
  const [match, setMatch] = useState<MatchInfo | null>(null);
  const [changing, setChanging] = useState(false);
  const raw = values[name] ?? "";
  const chosen = values[idKey];
  useEffect(() => {
    if (!raw || chosen) {
      setMatch(null);
      return;
    }
    const t = window.setTimeout(() => {
      api.get<MatchInfo>(`/api/reference/stations/match${qs({ q: raw, country })}`).then(setMatch).catch(() => setMatch(null));
    }, 350);
    return () => window.clearTimeout(t);
  }, [raw, chosen, country]);
  return (
    <label className={`field ${meta?.uncertain ? "uncertain" : ""}`}>
      <span>{title} <Conf meta={meta} /></span>
      <input value={raw} onChange={(e) => set({ [name]: e.target.value, [idKey]: null })} placeholder="Nom lu sur le document" />
      <div className="match-box">
        {chosen ? (
          <span>Gare retenue (choix manuel) : <b>{values[`${idKey}__name`] ?? chosen}</b>{" "}
            <button type="button" className="btn ghost sm" onClick={() => set({ [idKey]: null, [`${idKey}__name`]: null })}>annuler</button></span>
        ) : match ? (
          match.station_id ? (
            <span>
              Correspondance : <b>{match.name}</b> <span className={`conf ${match.confidence < 0.7 ? "low" : "ok"}`}>{Math.round(match.confidence * 100)} %</span>
              {match.ambiguous && <span className="hint warn"> ({match.reason})</span>}
            </span>
          ) : (
            <span className="hint warn">{match.reason} : choisissez la gare</span>
          )
        ) : (
          <span className="muted">{raw ? "recherche..." : "aucune gare"}</span>
        )}
        {!chosen && match?.station_id && !match.ambiguous && match.confidence >= 0.9 && !changing && (
          <button type="button" className="btn ghost sm" onClick={() => setChanging(true)}>changer</button>
        )}
        {!chosen && match && match.candidates.length > 0 && (changing || !match.station_id || match.ambiguous || match.confidence < 0.9) && (
          <div className="cands">
            {match.candidates.slice(0, 6).map((c) => (
              <button key={c.id} type="button" className="btn sm" onClick={() => set({ [idKey]: c.id, [`${idKey}__name`]: c.name })}>
                {c.name}{c.country ? ` (${c.country})` : ""}
              </button>
            ))}
          </div>
        )}
        {!chosen && (changing || !match?.station_id || match.ambiguous || match.confidence < 0.9) && (
          <div style={{ marginTop: 6 }}>
            <StationPicker placeholder="ou rechercher une autre gare" onSelect={(s) => s && set({ [idKey]: s.id, [`${idKey}__name`]: s.name, [name]: raw || s.name })} />
          </div>
        )}
      </div>
      <Hint meta={meta} onPick={(v) => set({ [name]: v, [idKey]: null })} />
    </label>
  );
}

export default function FineForm({ values, onChange, meta, existing }: { values: FineValues; onChange: (v: FineValues) => void; meta?: Record<string, FieldValue>; existing?: { case_hint?: string | null; has_case_number?: boolean } }) {
  const { options } = useApp();
  const set = (patch: FineValues) => onChange({ ...values, ...patch });
  const m = (k: string) => meta?.[k] as FieldValue | undefined;
  const fieldCls = (k: string) => `field ${m(k)?.uncertain ? "uncertain" : ""}`;
  const text = (k: string, title: string, props: Record<string, any> = {}) => (
    <label className={fieldCls(k)}>
      <span>{title} <Conf meta={m(k)} /></span>
      <input value={values[k] ?? ""} onChange={(e) => set({ [k]: e.target.value })} {...props} />
      <Hint meta={m(k)} onPick={(v) => set({ [k]: v })} />
    </label>
  );
  const select = (k: string, title: string, dict: Record<string, string> | undefined, emptyLabel = "—") => (
    <label className={fieldCls(k)}>
      <span>{title} <Conf meta={m(k)} /></span>
      <select value={values[k] ?? ""} onChange={(e) => set({ [k]: e.target.value || null })}>
        <option value="">{emptyLabel}</option>
        {Object.entries(dict ?? {}).map(([kk, v]) => (
          <option key={kk} value={kk}>{v}</option>
        ))}
      </select>
      <Hint meta={m(k)} onPick={(v) => set({ [k]: v })} />
    </label>
  );
  return (
    <div className="form-grid">
      {text("amount_initial", "Montant initial (€)", { inputMode: "decimal", placeholder: "ex. 50,00" })}
      {text("amount_paid", "Montant finalement payé (€)", { inputMode: "decimal", placeholder: "si connu" })}
      {text("fine_date", "Date de l'amende", { type: "date" })}
      {text("fine_time", "Heure du contrôle", { type: "time" })}
      <StationField name="origin_name" idKey="origin_station_id" title="Gare de départ" values={values} set={set} meta={m("origin_name")} country={values.country} />
      <StationField name="dest_name" idKey="dest_station_id" title="Gare d'arrivée" values={values} set={set} meta={m("dest_name")} country={values.country} />
      {text("train_number", "Numéro de train", { inputMode: "numeric", placeholder: "ex. 847123" })}
      {text("line_label", "Ligne indiquée", { placeholder: "ex. RER B, Ligne P, K12" })}
      {select("train_type", "Type de train", options?.train_types, "Inconnu")}
      {text("carrier", "Transporteur", { placeholder: "ex. SNCF Voyageurs, SNCB" })}
      {select("country", "Pays", options?.countries, "Déduit des gares")}
      {select("status", "Statut", options?.statuses, "Inconnu")}
      {select("reason", "Motif", options?.reasons, "Non renseigné")}
      {text("reason_text", "Motif (texte du document)")}
      {text("control_station_name", "Lieu du contrôle (si différent)")}
      <label className={fieldCls("case_number")}>
        <span>N° de dossier <Conf meta={m("case_number")} /></span>
        <input
          value={values.case_number ?? ""}
          onChange={(e) => set({ case_number: e.target.value })}
          placeholder={existing?.has_case_number ? `enregistré (se termine par ${existing.case_hint}) : laisser vide pour conserver` : "sert uniquement à détecter les doublons"}
          autoComplete="off"
        />
        <span className="hint">Conservé uniquement sous forme d'empreinte chiffrée (détection des doublons).</span>
      </label>
      <label className="field full">
        Notes
        <textarea value={values.notes ?? ""} onChange={(e) => set({ notes: e.target.value })} />
      </label>
      {values.currency && values.currency !== "EUR" && <p className="full hint warn">Devise : {values.currency}</p>}
    </div>
  );
}

// Valeurs initiales d'un formulaire à partir d'un brouillon extrait.
export function valuesFromDraft(fields: Record<string, any>): FineValues {
  const v: FineValues = {};
  for (const [k, f] of Object.entries(fields)) {
    if (k.startsWith("_") || !f || typeof f !== "object") continue;
    v[k] = f.value ?? null;
  }
  return v;
}

const SENT = ["amount_initial", "amount_paid", "currency", "fine_date", "fine_time", "origin_name", "origin_station_id", "dest_name",
  "dest_station_id", "control_station_name", "train_number", "line_label", "train_type", "carrier", "country", "reason",
  "reason_text", "status", "notes", "case_number"];

export function payloadFrom(values: FineValues, keepEmptyCase = false): Record<string, any> {
  const p: Record<string, any> = {};
  for (const k of SENT) {
    if (k === "case_number" && !values[k] && !keepEmptyCase) continue;
    if (k in values) p[k] = values[k] === "" ? null : values[k];
  }
  return p;
}
