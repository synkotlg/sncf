import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useApp } from "../components/AppContext";
import FineForm, { payloadFrom, valuesFromDraft, type FineValues } from "../components/FineForm";
import { IconFile, IconPlus, IconUpload } from "../components/Icons";
import { bytes, date, money } from "../format";
import type { DocumentInfo, Draft, Fine } from "../types";

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  en_attente: { text: "En attente", cls: "info" },
  traitement: { text: "Analyse en cours", cls: "info" },
  a_valider: { text: "À valider", cls: "warn" },
  sans_texte: { text: "Aucun texte lu", cls: "bad" },
  erreur: { text: "Erreur", cls: "bad" },
};

export default function ImportPage() {
  const { notify, bump } = useApp();
  const [params, setParams] = useSearchParams();
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [over, setOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const selectedId = params.get("doc") ? Number(params.get("doc")) : null;
  const [manual, setManual] = useState(false);

  const load = useCallback(() => api.get<{ documents: DocumentInfo[] }>("/api/documents").then((r) => setDocs(r.documents)), []);
  useEffect(() => {
    load();
  }, [load]);
  // suivi des documents en cours d'analyse
  useEffect(() => {
    if (!docs.some((d) => d.status === "en_attente" || d.status === "traitement")) return;
    const t = window.setInterval(load, 1500);
    return () => window.clearInterval(t);
  }, [docs, load]);

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    const form = new FormData();
    list.forEach((f) => form.append("files", f, f.name));
    setUploading(true);
    try {
      const r = await api.upload<{ results: any[] }>("/api/documents", form);
      setResults(r.results);
      const ok = r.results.filter((x) => x.ok && !x.duplicate).length;
      const dup = r.results.filter((x) => x.duplicate).length;
      const ko = r.results.filter((x) => !x.ok).length;
      notify(`${ok} document(s) en analyse${dup ? `, ${dup} déjà importé(s)` : ""}${ko ? `, ${ko} refusé(s)` : ""}`, ko ? "err" : "ok");
      await load();
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Importer des documents</h1>
          <p>PDF (natifs ou scannés), JPG, JPEG, PNG. L'extraction et l'OCR sont faits sur cet ordinateur : aucun document n'est envoyé à un service externe.</p>
        </div>
        <button className="btn" onClick={() => setManual(true)}><IconPlus /> Saisie manuelle</button>
      </div>

      <div
        className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
      >
        <IconUpload style={{ width: 28, height: 28 }} />
        <div style={{ marginTop: 8, fontWeight: 600 }}>{uploading ? "Envoi..." : "Déposez vos amendes ici ou cliquez pour choisir"}</div>
        <div className="muted small">Plusieurs fichiers à la fois. Le type réel de chaque fichier est vérifié (pas seulement l'extension).</div>
        <input ref={input} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" hidden onChange={(e) => e.target.files && upload(e.target.files)} />
      </div>

      {results.some((r) => !r.ok) && (
        <div className="notice bad" style={{ marginTop: 12 }}>
          Fichiers refusés :
          <ul>{results.filter((r) => !r.ok).map((r, i) => <li key={i}>{r.file} : {r.error}</li>)}</ul>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: selectedId ? "minmax(0, 340px) minmax(0, 1fr)" : "minmax(0, 1fr)", marginTop: 18 }}>
        <div className="card" style={{ padding: 0 }}>
          <div className="card-head" style={{ padding: "14px 16px 0" }}><h2>Documents importés</h2><span className="muted small">{docs.length}</span></div>
          {docs.length === 0 ? (
            <div className="empty" style={{ margin: 16 }}>Aucun document. Vous pouvez aussi générer des documents fictifs d'essai dans Paramètres.</div>
          ) : (
            <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
              <table>
                <tbody>
                  {docs.map((d) => {
                    const st = STATUS_LABEL[d.status] ?? { text: d.status, cls: "" };
                    const done = d.status === "a_valider" && !d.pending_drafts;
                    return (
                      <tr key={d.id} className={`clickable ${selectedId === d.id ? "selected" : ""}`} onClick={() => setParams({ doc: String(d.id) })}>
                        <td style={{ width: 24 }}><IconFile style={{ width: 16, height: 16, color: "var(--text-3)" }} /></td>
                        <td>
                          <div style={{ wordBreak: "break-all" }}>{d.original_name}</div>
                          <div className="muted small">{bytes(d.size)} · {date(d.uploaded_at)}{d.method ? ` · ${d.method === "ocr" ? "OCR" : d.method === "texte" ? "texte PDF" : d.method}` : ""}{d.ocr_confidence ? ` ${Math.round(d.ocr_confidence)} %` : ""}</div>
                        </td>
                        <td className="right">
                          {done ? <span className="badge good">Traité</span> : <span className={`badge ${st.cls}`}>{st.text}{d.pending_drafts ? ` (${d.pending_drafts})` : ""}</span>}
                          {d.is_demo ? <div style={{ marginTop: 4 }}><span className="badge demo">exemple</span></div> : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {selectedId && <DocumentReview key={selectedId} id={selectedId} onChanged={() => { load(); bump(); }} onDeleted={() => { setParams({}); load(); bump(); }} />}
      </div>
      {manual && <ManualEntry onClose={() => setManual(false)} onSaved={() => { setManual(false); bump(); }} />}
    </div>
  );
}

function DocumentReview({ id, onChanged, onDeleted }: { id: number; onChanged: () => void; onDeleted: () => void }) {
  const { notify } = useApp();
  const [doc, setDoc] = useState<DocumentInfo | null>(null);
  const [showText, setShowText] = useState(false);
  const load = useCallback(() => api.get<DocumentInfo>(`/api/documents/${id}?with_text=true`).then(setDoc).catch(() => setDoc(null)), [id]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!doc || (doc.status !== "en_attente" && doc.status !== "traitement")) return;
    const t = window.setInterval(load, 1500);
    return () => window.clearInterval(t);
  }, [doc, load]);

  if (!doc) return <div className="card">Chargement...</div>;
  const pending = (doc.drafts ?? []).filter((d) => d.status === "a_valider");
  const fileUrl = `/api/documents/${doc.id}/file`;

  const remove = async () => {
    const withFines = (doc.fine_ids?.length ?? 0) > 0 && window.confirm("Supprimer aussi les amendes enregistrées à partir de ce document ? (Annuler = ne supprimer que le document)");
    if (!window.confirm("Supprimer définitivement ce document de cet ordinateur ?")) return;
    await api.del(`/api/documents/${doc.id}?delete_fines=${withFines}`);
    notify("Document supprimé", "ok");
    onDeleted();
  };

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2 style={{ wordBreak: "break-all" }}>{doc.original_name}</h2>
            <p>{doc.pages ? `${doc.pages} page(s) · ` : ""}{doc.method === "ocr" ? `OCR local, confiance moyenne ${doc.ocr_confidence ?? "?"} %` : doc.method === "texte" ? "texte extrait du PDF" : doc.method ?? ""}</p>
          </div>
          <div className="row">
            <a className="btn sm" href={fileUrl} target="_blank" rel="noreferrer">Ouvrir</a>
            <button className="btn sm" onClick={async () => { await api.post(`/api/documents/${doc.id}/reprocess`); notify("Nouvelle analyse lancée"); load(); }}>Relancer l'analyse</button>
            <button className="btn sm" onClick={async () => { await api.post(`/api/documents/${doc.id}/drafts`); load(); }}><IconPlus /> Amende supplémentaire</button>
            <button className="btn sm danger" onClick={remove}>Supprimer</button>
          </div>
        </div>
        {(doc.status === "en_attente" || doc.status === "traitement") && <div className="notice">Analyse en cours (extraction du texte, OCR si nécessaire)...</div>}
        {doc.error && <div className="notice bad">{doc.error}</div>}
        {(doc.warnings ?? []).length > 0 && <div className="notice warn"><ul>{doc.warnings!.map((w, i) => <li key={i}>{w}</li>)}</ul></div>}
        {doc.mime === "application/pdf" ? (
          <iframe className="doc-preview" src={fileUrl} title="Aperçu du document" />
        ) : (
          <div className="doc-preview" style={{ overflow: "auto", height: "auto", maxHeight: 520 }}><img src={fileUrl} alt="Document importé" /></div>
        )}
        {doc.text && (
          <div style={{ marginTop: 10 }}>
            <button className="btn ghost sm" onClick={() => setShowText((s) => !s)}>{showText ? "Masquer" : "Afficher"} le texte extrait</button>
            {showText && <div className="ocr-text" style={{ marginTop: 6 }}>{doc.text}</div>}
          </div>
        )}
      </div>
      {pending.length === 0 && doc.status !== "en_attente" && doc.status !== "traitement" && (
        <div className="notice">
          Aucune amende en attente de validation pour ce document{doc.fine_ids?.length ? ` (${doc.fine_ids.length} enregistrée(s))` : ""}.
        </div>
      )}
      {pending.map((d, i) => (
        <DraftCard key={d.id} draft={d} index={i} total={pending.length} onDone={() => { load(); onChanged(); }} />
      ))}
    </div>
  );
}

function DraftCard({ draft, index, total, onDone }: { draft: Draft; index: number; total: number; onDone: () => void }) {
  const { notify } = useApp();
  const [values, setValues] = useState<FineValues>(() => valuesFromDraft(draft.fields));
  const [dups, setDups] = useState<any[] | null>(null);
  const [errors, setErrors] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const uncertain = Object.entries(draft.fields).filter(([k, v]: any) => !k.startsWith("_") && v?.uncertain).map(([k]) => k);
  const missing: string[] = draft.fields._summary?.missing ?? [];

  const save = async (force = false) => {
    setBusy(true);
    setErrors(null);
    try {
      await api.post<Fine>(`/api/drafts/${draft.id}/validate${force ? "?force=true" : ""}`, payloadFrom(values));
      notify("Amende enregistrée", "ok");
      setDups(null);
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.body?.duplicates) setDups(e.body.duplicates);
      else if (e instanceof ApiError && e.status === 422 && e.body?.errors) setErrors(e.body.errors);
      else notify((e as Error).message, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Amende {total > 1 ? `${index + 1} / ${total}` : "détectée"} : vérification</h2>
          <p>Les champs surlignés sont incertains. Rien n'a été inventé : un champ vide n'a pas été trouvé dans le document.</p>
        </div>
      </div>
      {(uncertain.length > 0 || missing.length > 0) && (
        <div className="notice warn" style={{ marginBottom: 12 }}>
          {uncertain.length > 0 && <div>À vérifier : {uncertain.length} champ(s) incertain(s).</div>}
          {missing.length > 0 && <div>Non trouvés : {missing.map((m) => ({ amount_initial: "montant", fine_date: "date", origin_name: "gare de départ", dest_name: "gare d'arrivée" } as any)[m] ?? m).join(", ")}.</div>}
        </div>
      )}
      <FineForm values={values} onChange={setValues} meta={draft.fields as any} />
      {errors && <div className="notice bad" style={{ marginTop: 12 }}><ul>{Object.entries(errors).map(([k, v]) => <li key={k}>{k} : {v}</li>)}</ul></div>}
      {dups && (
        <div className="notice warn" style={{ marginTop: 12 }}>
          <b>Doublon potentiel</b>
          <ul>
            {dups.map((d, i) => (
              <li key={i}>{d.reason} ({d.certainty}) : amende du {date(d.fine.fine_date)} {d.fine.fine_time ?? ""}, {money(d.fine.amount_initial)}, {d.fine.origin_name ?? "?"} → {d.fine.dest_name ?? "?"}</li>
            ))}
          </ul>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn sm" onClick={() => setDups(null)}>Revoir</button>
            <button className="btn sm danger" onClick={() => save(true)}>Enregistrer quand même</button>
          </div>
        </div>
      )}
      <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}>
        <button className="btn ghost" disabled={busy} onClick={async () => { await api.post(`/api/drafts/${draft.id}/discard`); notify("Brouillon écarté"); onDone(); }}>Écarter</button>
        <button className="btn primary" disabled={busy} onClick={() => save(false)}>Valider et enregistrer</button>
      </div>
    </div>
  );
}

export function ManualEntry({ onClose, onSaved }: { onClose: () => void; onSaved: (f: Fine) => void }) {
  const { notify } = useApp();
  const [values, setValues] = useState<FineValues>({ status: "inconnue", currency: "EUR" });
  const [dups, setDups] = useState<any[] | null>(null);
  const [errors, setErrors] = useState<Record<string, string> | null>(null);
  const save = async (force = false) => {
    setErrors(null);
    try {
      const f = await api.post<Fine>(`/api/fines${force ? "?force=true" : ""}`, payloadFrom(values));
      notify("Amende enregistrée", "ok");
      onSaved(f);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setDups(e.body.duplicates);
      else if (e instanceof ApiError && e.status === 422) setErrors(e.body.errors);
      else notify((e as Error).message, "err");
    }
  };
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <div className="drawer" role="dialog" aria-label="Saisie manuelle">
        <div className="drawer-head"><h2 className="grow">Saisie manuelle d'une amende</h2><button className="btn ghost" onClick={onClose}>Fermer</button></div>
        <div className="drawer-body">
          <FineForm values={values} onChange={setValues} />
          {errors && <div className="notice bad" style={{ marginTop: 12 }}><ul>{Object.entries(errors).map(([k, v]) => <li key={k}>{k} : {v}</li>)}</ul></div>}
          {dups && (
            <div className="notice warn" style={{ marginTop: 12 }}>
              <b>Doublon potentiel</b>
              <ul>{dups.map((d, i) => <li key={i}>{d.reason} : {date(d.fine.fine_date)} {money(d.fine.amount_initial)}</li>)}</ul>
              <button className="btn sm danger" onClick={() => save(true)}>Enregistrer quand même</button>
            </div>
          )}
        </div>
        <div className="drawer-foot"><button className="btn" onClick={onClose}>Annuler</button><button className="btn primary" onClick={() => save(false)}>Enregistrer</button></div>
      </div>
    </>
  );
}
