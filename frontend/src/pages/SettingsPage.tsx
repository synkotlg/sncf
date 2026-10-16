import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useApp } from "../components/AppContext";
import { date, number } from "../format";
import type { ReferenceStatus, Settings } from "../types";

const GROUP_LABEL: Record<string, string> = {
  base: "Base communautaire (gares Trainline/iRail, Natural Earth)",
  sncf: "SNCF Open Data (lignes RFN, statuts, gares)",
  infrabel: "Infrabel Open Data (lignes et gares belges)",
  osm: "OpenStreetMap / Overpass (voies + itinéraires, volumineux)",
  gtfs: "Horaires GTFS SNCF + SNCB (itinéraires, numéros de train)",
};

export default function SettingsPage() {
  const { settings, reloadSettings, notify, bump } = useApp();
  const [form, setForm] = useState<Settings | null>(settings);
  const [ref, setRef] = useState<ReferenceStatus | null>(null);
  const [sys, setSys] = useState<any>(null);
  const [groups, setGroups] = useState<string[]>(["base", "sncf", "infrabel", "gtfs"]);
  const [confirm, setConfirm] = useState("");
  const gtfsInput = useRef<HTMLInputElement>(null);
  const restoreInput = useRef<HTMLInputElement>(null);
  const [gtfsSource, setGtfsSource] = useState("sncf_gtfs");
  const [busy, setBusy] = useState("");

  useEffect(() => setForm(settings), [settings]);
  const loadRef = () => api.get<ReferenceStatus>("/api/reference/status").then(setRef).catch(() => undefined);
  useEffect(() => {
    loadRef();
    api.get<any>("/api/system").then(setSys).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!ref?.update.running) return;
    const t = window.setInterval(loadRef, 1500);
    return () => window.clearInterval(t);
  }, [ref?.update.running]);
  useEffect(() => {
    if (ref && !ref.update.running && ref.update.report) bump();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref?.update.running]);

  const saveSettings = async () => {
    if (!form) return;
    await api.put("/api/settings", form);
    await reloadSettings();
    notify("Paramètres enregistrés", "ok");
  };

  const set = (k: keyof Settings, v: any) => form && setForm({ ...form, [k]: v });
  const runs = Object.fromEntries((ref?.runs ?? []).map((r) => [r.source_id, r]));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Paramètres et données</h1>
          <p>Toutes les données restent sur cet ordinateur ({sys?.data_dir ?? "dossier data/"}).</p>
        </div>
      </div>
      <div className="stack" style={{ gap: 14 }}>
        <div className="grid grid-2">
          <div className="card">
            <div className="card-head"><h2>Extraction et OCR</h2></div>
            {form && (
              <div className="stack">
                <div className={`notice ${sys?.tesseract?.available ? "" : "warn"} small`}>
                  {sys?.tesseract?.available
                    ? <>Tesseract détecté (langues : {sys.tesseract.languages.join(", ")}). L'OCR est exécuté localement.</>
                    : <>Tesseract introuvable : installez-le (voir README) pour lire les scans et photos. Les PDF natifs restent lisibles.</>}
                </div>
                <label className="check"><input type="checkbox" checked={form.ocr_enabled} onChange={(e) => set("ocr_enabled", e.target.checked)} />OCR local des documents scannés et images</label>
                <label className="field">Langues OCR (codes Tesseract)<input value={form.ocr_languages} onChange={(e) => set("ocr_languages", e.target.value)} /></label>
                <label className="check"><input type="checkbox" checked={form.keep_extracted_text} onChange={(e) => set("keep_extracted_text", e.target.checked)} />Conserver le texte extrait après validation (désactivé = minimisation des données)</label>
                <div className="grid grid-2">
                  <label className="field">Taille maximale par fichier (Mo)<input type="number" min={1} max={200} value={form.max_upload_mb} onChange={(e) => set("max_upload_mb", Number(e.target.value))} /></label>
                  <label className="field">Pages PDF analysées au maximum<input type="number" min={1} max={200} value={form.max_pdf_pages} onChange={(e) => set("max_pdf_pages", Number(e.target.value))} /></label>
                </div>
                <label className="field">Seuil de similarité des noms de gares (60-100)<input type="number" min={60} max={100} value={form.station_match_threshold} onChange={(e) => set("station_match_threshold", Number(e.target.value))} /></label>
                <label className="check"><input type="checkbox" checked={form.infer_paths} onChange={(e) => set("infer_paths", e.target.checked)} />Proposer un trajet présumé (plus court chemin) quand seules les gares sont connues</label>
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-head"><h2>Carte</h2></div>
            {form && (
              <div className="stack">
                <label className="check"><input type="checkbox" checked={form.online_basemap} onChange={(e) => set("online_basemap", e.target.checked)} />Fond de carte en ligne (sinon fond hors ligne Natural Earth)</label>
                <label className="field">URL des tuiles du fond (gabarit XYZ)<input value={form.basemap_url} onChange={(e) => set("basemap_url", e.target.value)} /></label>
                <label className="field">Attribution du fond<input value={form.basemap_attribution} onChange={(e) => set("basemap_attribution", e.target.value)} /></label>
                <label className="check"><input type="checkbox" checked={form.openrailwaymap_overlay} onChange={(e) => set("openrailwaymap_overlay", e.target.checked)} />Calque OpenRailwayMap (voies, gares, signalisation détaillées)</label>
                <p className="muted small">Les fonds en ligne ne reçoivent que la zone affichée (aucune donnée d'amende). Respectez leurs conditions d'usage (usage personnel modéré).</p>
              </div>
            )}
            <div className="row" style={{ marginTop: 12 }}><button className="btn primary" onClick={saveSettings}>Enregistrer les paramètres</button></div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div>
              <h2>Référentiel ferroviaire</h2>
              <p>{ref ? `${number(ref.counts.stations)} gares · ${number(ref.counts.active_lines)} lignes physiques actives · ${number(ref.counts.routes)} itinéraires commerciaux · ${number(ref.counts.trains)} numéros de train` : "..."}</p>
            </div>
          </div>
          <div className="grid grid-2">
            <div className="stack">
              {Object.entries(GROUP_LABEL).map(([g, l]) => (
                <label key={g} className="check">
                  <input type="checkbox" checked={groups.includes(g)} onChange={(e) => setGroups(e.target.checked ? [...groups, g] : groups.filter((x) => x !== g))} />{l}
                </label>
              ))}
              <div className="row">
                <button className="btn primary" disabled={ref?.update.running || !groups.length} onClick={async () => {
                  try { await api.post("/api/reference/update", { groups }); notify("Mise à jour lancée"); loadRef(); } catch (e: any) { notify(e.message, "err"); }
                }}>{ref?.update.running ? "Mise à jour en cours..." : "Mettre à jour les données"}</button>
              </div>
              <div className="sep" />
              <div className="small secondary">Import manuel d'un GTFS téléchargé sur le portail officiel (si le téléchargement automatique est bloqué) :</div>
              <div className="row">
                <select value={gtfsSource} onChange={(e) => setGtfsSource(e.target.value)} style={{ width: "auto" }}>
                  <option value="sncf_gtfs">GTFS SNCF</option>
                  <option value="sncb_gtfs">GTFS SNCB</option>
                </select>
                <button className="btn" disabled={!!busy} onClick={() => gtfsInput.current?.click()}>{busy === "gtfs" ? "Import..." : "Choisir le ZIP GTFS"}</button>
                <input ref={gtfsInput} type="file" accept=".zip" hidden onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  const fd = new FormData();
                  fd.append("file", f);
                  setBusy("gtfs");
                  try { const r = await api.upload<any>(`/api/reference/gtfs?source=${gtfsSource}`, fd); notify(`GTFS importé : ${r.routes} itinéraires, ${r.trains} circulations`, "ok"); loadRef(); bump(); }
                  catch (er: any) { notify(er.message, "err"); }
                  finally { setBusy(""); e.target.value = ""; }
                }} />
              </div>
            </div>
            <div>
              {(ref?.update.log.length ?? 0) > 0 && <div className="log">{ref!.update.log.join("\n")}</div>}
            </div>
          </div>
          <div className="table-wrap" style={{ marginTop: 14 }}>
            <table>
              <thead><tr><th>Source</th><th>Représente</th><th>Licence</th><th>Mise à jour</th><th>Dernier import</th></tr></thead>
              <tbody>
                {(ref?.sources ?? []).map((s) => {
                  const run = runs[s.id];
                  return (
                    <tr key={s.id}>
                      <td><a href={s.homepage} target="_blank" rel="noreferrer">{s.name}</a><div className="muted small">{s.provider}</div></td>
                      <td className="small">{s.represents}{s.limits && <div className="muted">Limites : {s.limits}</div>}</td>
                      <td className="small">{s.licence}</td>
                      <td className="small">{s.update_frequency}</td>
                      <td className="small">
                        {run ? (
                          <>
                            <span className={`badge ${run.status === "ok" ? "good" : "bad"}`}>{run.status}</span>
                            <div className="muted">{date(run.fetched_at)} · {number(run.records)} enr.</div>
                            {run.status !== "ok" && <div className="muted" style={{ maxWidth: 260, wordBreak: "break-word" }}>{run.message.slice(0, 220)}</div>}
                          </>
                        ) : <span className="muted">jamais</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="grid grid-2">
          <div className="card">
            <div className="card-head"><h2>Sauvegarde et restauration</h2></div>
            <p className="secondary small">La sauvegarde (ZIP) contient vos amendes, vos documents et vos paramètres : conservez-la en lieu sûr.</p>
            <div className="row">
              <a className="btn" href="/api/backup">Télécharger une sauvegarde</a>
              <button className="btn" onClick={() => restoreInput.current?.click()}>Restaurer...</button>
              <input ref={restoreInput} type="file" accept=".zip" hidden onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                if (!window.confirm("La restauration REMPLACE toutes les amendes et documents actuels. Continuer ?")) return;
                const fd = new FormData();
                fd.append("file", f);
                try { const r = await api.upload<any>("/api/restore", fd); notify(`Restauration terminée (${r.documents} documents)`, "ok"); bump(); await reloadSettings(); }
                catch (er: any) { notify(er.message, "err"); }
                finally { e.target.value = ""; }
              }} />
            </div>
            <div className="sep" />
            <h3>Exports</h3>
            <div className="row" style={{ marginTop: 8 }}>
              <a className="btn sm" href="/api/export/stats.csv">Statistiques CSV</a>
              <a className="btn sm" href="/api/export/stats.json">Statistiques JSON</a>
              <a className="btn sm" href="/api/export/fines.csv">Amendes CSV</a>
              <a className="btn sm" href="/api/export/fines.json">Amendes JSON</a>
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h2>Exemples fictifs</h2></div>
            <p className="secondary small">Des amendes et des documents d'exemple, clairement marqués comme fictifs, pour tester l'application avant d'importer vos propres documents.</p>
            <div className="row">
              <button className="btn" onClick={async () => { try { const r = await api.post<any>("/api/demo"); notify(`${r.created} amendes fictives ajoutées`, "ok"); bump(); } catch (e: any) { notify(e.message, "err"); } }}>Charger des amendes fictives</button>
              <button className="btn" onClick={async () => { const r = await api.post<any>("/api/demo/documents"); notify(`${r.results.length} documents fictifs importés : à valider dans Importer`, "ok"); bump(); }}>Importer des documents fictifs</button>
              <button className="btn danger" onClick={async () => { const r = await api.del<any>("/api/demo"); notify(`Exemples supprimés (${r.fines} amendes, ${r.documents} documents)`, "ok"); bump(); }}>Supprimer les exemples</button>
            </div>
            <div className="sep" />
            <h3>Effacer toutes mes données</h3>
            <p className="secondary small">Supprime définitivement amendes, documents et exports de cet ordinateur. Tapez SUPPRIMER pour confirmer.</p>
            <div className="row">
              <input style={{ width: 160 }} value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="SUPPRIMER" aria-label="Confirmation" />
              <button className="btn danger" disabled={confirm !== "SUPPRIMER"} onClick={async () => { await api.del(`/api/user-data?confirm=SUPPRIMER`); setConfirm(""); notify("Toutes les données personnelles ont été supprimées", "ok"); bump(); }}>Tout effacer</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
