import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { label, useApp } from "../components/AppContext";
import FineForm, { payloadFrom, type FineValues } from "../components/FineForm";
import { IconPlus } from "../components/Icons";
import StationPicker from "../components/StationPicker";
import { date, money, number } from "../format";
import { GEO_COLORS } from "../theme";
import type { Fine, StationCandidate } from "../types";
import { ManualEntry } from "./ImportPage";

type SortKey = "date" | "amount" | "route";

export default function FinesPage() {
  const { options, dataVersion, bump } = useApp();
  const [fines, setFines] = useState<Fine[]>([]);
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [geo, setGeo] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState<SortKey>("date");
  const [manual, setManual] = useState(false);
  const openId = params.get("id") ? Number(params.get("id")) : null;

  const load = useCallback(() => api.get<{ fines: Fine[] }>("/api/fines").then((r) => setFines(r.fines)), []);
  useEffect(() => {
    load();
  }, [load, dataVersion]);

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let l = fines.filter((f) => {
      if (geo && f.geo_status !== geo) return false;
      if (status && f.status !== status) return false;
      if (type && (f.train_type ?? "") !== type) return false;
      if (needle) {
        const hay = [f.origin_name, f.dest_name, f.train_number, f.line_label, f.carrier, f.reason_text, f.notes].join(" ").toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
    l = [...l].sort((a, b) => {
      if (sort === "amount") return (b.amount_initial ?? -1) - (a.amount_initial ?? -1);
      if (sort === "route") return `${a.origin_name}${a.dest_name}`.localeCompare(`${b.origin_name}${b.dest_name}`);
      return `${b.fine_date ?? ""}${b.fine_time ?? ""}`.localeCompare(`${a.fine_date ?? ""}${a.fine_time ?? ""}`);
    });
    return l;
  }, [fines, q, geo, status, type, sort]);

  const total = list.reduce((s, f) => s + (f.amount_initial ?? 0), 0);
  const demo = fines.filter((f) => f.is_demo).length;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Mes amendes</h1>
          <p>{number(list.length)} amende(s) affichée(s) · {money(total)} au total{demo ? ` · dont ${demo} exemple(s) fictif(s)` : ""}</p>
        </div>
        <div className="row">
          <a className="btn" href="/api/export/fines.csv">Export CSV</a>
          <a className="btn" href="/api/export/fines.json">Export JSON</a>
          <button className="btn primary" onClick={() => setManual(true)}><IconPlus /> Nouvelle amende</button>
        </div>
      </div>
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="filters">
          <label className="field">Recherche<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="gare, train, transporteur..." /></label>
          <label className="field">Géolocalisation
            <select value={geo} onChange={(e) => setGeo(e.target.value)}>
              <option value="">Toutes</option>
              {Object.entries(options?.geo_statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">Statut
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Tous</option>
              {Object.entries(options?.statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">Type de train
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">Tous</option>
              {Object.entries(options?.train_types ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">Tri
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="date">Date (récentes d'abord)</option>
              <option value="amount">Montant décroissant</option>
              <option value="route">Trajet</option>
            </select>
          </label>
        </div>
      </div>
      {fines.length === 0 ? (
        <div className="empty">
          Aucune amende. <Link to="/importer">Importez vos documents</Link>, saisissez une amende ou chargez les exemples fictifs dans <Link to="/parametres">Paramètres</Link>.
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th><th>Trajet</th><th>Train</th><th className="num">Montant</th><th className="num">Payé</th><th>Statut</th><th>Motif</th><th>Localisation</th>
              </tr>
            </thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.id} className={`clickable ${openId === f.id ? "selected" : ""}`} onClick={() => setParams({ id: String(f.id) })}>
                  <td className="nowrap">{date(f.fine_date)}<div className="muted small">{f.fine_time ?? ""}</div></td>
                  <td>
                    {f.origin_name ?? <span className="muted">?</span>} → {f.dest_name ?? <span className="muted">?</span>}
                    {f.is_demo ? <span className="badge demo" style={{ marginLeft: 6 }}>exemple</span> : null}
                    {(f.uncertain_fields?.length ?? 0) > 0 && <span className="badge warn" style={{ marginLeft: 6 }} title={f.uncertain_fields!.join(", ")}>{f.uncertain_fields!.length} incertain(s)</span>}
                  </td>
                  <td className="nowrap">{f.train_type ? label(options?.train_types, f.train_type).split(" (")[0] : "—"}<div className="muted small">{f.train_number ?? f.line_label ?? ""}</div></td>
                  <td className="num">{money(f.amount_initial, f.currency)}</td>
                  <td className="num">{money(f.amount_paid, f.currency)}</td>
                  <td>{label(options?.statuses, f.status)}</td>
                  <td className="small">{label(options?.reasons, f.reason)}</td>
                  <td><span className="badge" title={label(options?.geo_statuses, f.geo_status)}><span className="dot" style={{ background: GEO_COLORS[f.geo_status] }} />{shortGeo(f.geo_status)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {openId && <FineEditor key={openId} id={openId} onClose={() => setParams({})} onChanged={() => { load(); bump(); }} />}
      {manual && <ManualEntry onClose={() => setManual(false)} onSaved={(f) => { setManual(false); load(); bump(); setParams({ id: String(f.id) }); }} />}
    </div>
  );
}

function shortGeo(s: string): string {
  return ({ train_confirmed: "confirmée", train_route: "train seul", path_inferred: "présumée", manual: "manuelle", od_only: "gares seules", station_only: "une gare", none: "non géolocalisée" } as Record<string, string>)[s] ?? s;
}

function fineToValues(f: Fine): FineValues {
  const v: FineValues = {};
  for (const k of ["amount_initial", "amount_paid", "currency", "fine_date", "fine_time", "origin_name", "origin_station_id", "dest_name", "dest_station_id",
    "control_station_name", "train_number", "line_label", "train_type", "carrier", "country", "reason", "reason_text", "status", "notes"]) {
    v[k] = (f as any)[k] ?? null;
  }
  if (f.origin_station_id) v.origin_station_id__name = f.geo_detail?.origin?.name ?? f.origin_station_id;
  if (f.dest_station_id) v.dest_station_id__name = f.geo_detail?.dest?.name ?? f.dest_station_id;
  return v;
}

function FineEditor({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const { options, notify } = useApp();
  const [fine, setFine] = useState<Fine | null>(null);
  const [values, setValues] = useState<FineValues>({});
  const [errors, setErrors] = useState<Record<string, string> | null>(null);
  const [via, setVia] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<Fine>(`/api/fines/${id}`).then((f) => {
      setFine(f);
      setValues(fineToValues(f));
      setVia((f.via_station_ids ?? []).map((v) => ({ id: v, name: v })));
    }).catch(() => setFine(null));
  }, [id]);

  if (!fine) return null;
  const geo = fine.geo_detail ?? {};

  const save = async (extra: Record<string, any> = {}, force = false) => {
    setBusy(true);
    setErrors(null);
    try {
      const f = await api.put<Fine>(`/api/fines/${id}${force ? "?force=true" : ""}`, { ...payloadFrom(values), via_station_ids: via.map((v) => v.id), ...extra });
      setFine(f);
      setValues(fineToValues(f));
      notify("Amende mise à jour", "ok");
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) setErrors(e.body.errors);
      else if (e instanceof ApiError && e.status === 409) {
        if (window.confirm("Ce numéro de dossier existe déjà sur une autre amende. Enregistrer quand même ?")) await save(extra, true);
      } else notify((e as Error).message, "err");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Supprimer définitivement cette amende ? (le document source est conservé)")) return;
    await api.del(`/api/fines/${id}`);
    notify("Amende supprimée", "ok");
    onChanged();
    onClose();
  };

  const lines = fine.links.filter((l) => l.kind === "line");
  const route = fine.links.find((l) => l.kind === "route");
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <div className="drawer" role="dialog" aria-label="Fiche amende">
        <div className="drawer-head">
          <div className="grow">
            <h2>Amende du {date(fine.fine_date)} {fine.fine_time ?? ""}</h2>
            <div className="muted small">{fine.is_demo ? "EXEMPLE FICTIF · " : ""}créée le {date(fine.created_at)}{fine.document_id ? " · issue d'un document importé" : " · saisie manuelle"}</div>
          </div>
          {fine.document_id && <a className="btn sm" href={`/api/documents/${fine.document_id}/file`} target="_blank" rel="noreferrer">Document source</a>}
          <button className="btn ghost" onClick={onClose}>Fermer</button>
        </div>
        <div className="drawer-body stack">
          {(fine.uncertain_fields?.length ?? 0) > 0 && (
            <div className="notice warn small">Champs incertains lors de l'extraction : {fine.uncertain_fields!.join(", ")}. Vérifiez-les avec le document source.</div>
          )}
          <FineForm values={values} onChange={setValues} existing={{ case_hint: fine.case_hint, has_case_number: fine.has_case_number }} />
          {errors && <div className="notice bad"><ul>{Object.entries(errors).map(([k, v]) => <li key={k}>{k} : {v}</li>)}</ul></div>}

          <div className="card">
            <div className="card-head">
              <div>
                <h2>Correspondance cartographique</h2>
                <p>{label(options?.geo_statuses, fine.geo_status)}{fine.geo_confidence !== null ? ` · confiance ${Math.round((fine.geo_confidence ?? 0) * 100)} %` : ""}{fine.geo_validated ? " · validée manuellement" : ""}</p>
              </div>
              <span className="badge"><span className="dot" style={{ background: GEO_COLORS[fine.geo_status] }} />{shortGeo(fine.geo_status)}</span>
            </div>
            <div className="stack small">
              <div>Départ : {geo.origin?.id ? <b>{geo.origin.name}</b> : <span className="muted">non identifiée</span>}{geo.origin?.reason ? <span className="muted"> ({geo.origin.reason})</span> : null}</div>
              <div>Arrivée : {geo.dest?.id ? <b>{geo.dest.name}</b> : <span className="muted">non identifiée</span>}{geo.dest?.reason ? <span className="muted"> ({geo.dest.reason})</span> : null}</div>
              {geo.train && <div>Circulation : <b>{geo.train.category} {geo.train.train_number}</b> {geo.train.route_label ? `(${geo.train.route_label})` : ""} {geo.train.date_ok ? "· circule à cette date" : "· date non vérifiée"}</div>}
              {route && <div>Itinéraire commercial : <b>{route.label ?? route.ref_id}</b></div>}
              {lines.length > 0 && (
                <div>
                  Lignes physiques {fine.geo_status === "path_inferred" ? "présumées" : ""} ({number(fine.path?.length_km)} km) :
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                    {lines.map((l) => <li key={l.ref_id}><Link to={`/carte?line=${encodeURIComponent(l.ref_id)}`}>{l.label}</Link> <span className="muted">{number(l.km)} km</span></li>)}
                  </ul>
                </div>
              )}
              {(geo.messages ?? []).length > 0 && <div className="notice small"><ul>{geo.messages!.map((m, i) => <li key={i}>{m}</li>)}</ul></div>}
              {geo.route_candidates && geo.route_candidates.length > 0 && (
                <div className="muted">Itinéraires possibles : {geo.route_candidates.map((r) => `${r.category} ${r.short_name ?? r.long_name}`).join(", ")}</div>
              )}
              <div className="sep" />
              <div>
                <div className="secondary" style={{ marginBottom: 4 }}>Corriger le tracé : imposer une ou plusieurs gares intermédiaires (via)</div>
                {via.map((v, i) => (
                  <div key={i} className="row" style={{ marginBottom: 4 }}>
                    <span className="badge">{v.name}</span>
                    <button className="btn ghost sm" onClick={() => setVia(via.filter((_, j) => j !== i))}>retirer</button>
                  </div>
                ))}
                <StationPicker placeholder="Ajouter une gare de passage" onSelect={(s: StationCandidate | null) => s && setVia([...via, { id: s.id, name: s.name }])} />
              </div>
              <div className="row" style={{ marginTop: 6 }}>
                <button className="btn sm" disabled={busy || fine.geo_status === "none"} onClick={() => save({ geo_validated: !fine.geo_validated })}>
                  {fine.geo_validated ? "Retirer la validation" : "Valider cette correspondance"}
                </button>
                <button className="btn sm" disabled={busy} onClick={() => save({ geo_disabled: !fine.geo_disabled })}>
                  {fine.geo_disabled ? "Réactiver la géolocalisation" : "Ne pas géolocaliser"}
                </button>
                {fine.geo_status !== "none" && <Link className="btn sm" to={`/carte?station=${encodeURIComponent(fine.origin_resolved_id ?? fine.dest_resolved_id ?? "")}`}>Voir sur la carte</Link>}
              </div>
            </div>
          </div>
        </div>
        <div className="drawer-foot">
          <button className="btn danger" onClick={remove}>Supprimer</button>
          <span className="grow" />
          <button className="btn" onClick={onClose}>Annuler</button>
          <button className="btn primary" disabled={busy} onClick={() => save()}>Enregistrer</button>
        </div>
      </div>
    </>
  );
}
