import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../components/AppContext";
import Chart from "../components/Chart";
import { columnChart, monthsChart, type Metric } from "../components/charts";
import RankingCard, { MetricSwitch } from "../components/Ranking";
import { number } from "../format";
import type { ReferenceStatus, Stats } from "../types";
import { Caveats, Kpis } from "./StatsPage";

export default function Dashboard() {
  const { dataVersion, notify, bump } = useApp();
  const navigate = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [ref, setRef] = useState<ReferenceStatus | null>(null);
  const [sys, setSys] = useState<any>(null);
  const [metric, setMetric] = useState<Metric>("count");

  useEffect(() => {
    api.get<Stats>("/api/stats").then(setStats).catch(() => setStats(null));
    api.get<ReferenceStatus>("/api/reference/status").then(setRef).catch(() => undefined);
    api.get<any>("/api/system").then(setSys).catch(() => undefined);
  }, [dataVersion]);

  const official = (ref?.counts.line_sources ?? []).some((l) => l.active && l.source !== "naturalearth_rail");
  const empty = !stats || stats.empty;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Tableau de bord</h1>
          <p>Vue d'ensemble de vos amendes ferroviaires en France et en Belgique.</p>
        </div>
        <div className="row">
          <Link className="btn" to="/importer">Importer des documents</Link>
          <Link className="btn primary" to="/carte">Ouvrir la carte</Link>
        </div>
      </div>

      <div className="stack" style={{ gap: 14 }}>
        {(stats?.summary.demo ?? 0) > 0 && (
          <div className="notice demo">
            {stats!.summary.demo} amende(s) d'EXEMPLE FICTIVES sont incluses. Elles servent à tester l'application et se suppriment dans <Link to="/parametres">Paramètres</Link>.
          </div>
        )}
        {ref && ref.counts.stations === 0 && (
          <div className="notice warn">Le référentiel ferroviaire n'est pas encore importé. Lancez la mise à jour dans <Link to="/parametres">Paramètres</Link> (ou <code>railfine data update</code>).</div>
        )}
        {ref && ref.counts.stations > 0 && !official && (
          <div className="notice warn">
            Réseau de secours affiché (Natural Earth, généralisé et sans noms de lignes). Les sources officielles (SNCF Réseau, Infrabel, GTFS) n'ont pas encore été importées :
            voir <Link to="/parametres">Paramètres</Link>.
          </div>
        )}
        {sys && !sys.tesseract?.available && (
          <div className="notice warn">Tesseract (OCR local) n'est pas détecté : les PDF natifs restent lisibles, mais pas les scans ni les photos. Voir le README pour l'installer.</div>
        )}
        {empty ? (
          <div className="card">
            <h2>Aucune amende pour l'instant</h2>
            <p className="secondary" style={{ marginTop: 6 }}>Importez vos documents (PDF, scans, photos), saisissez une amende ou chargez des exemples fictifs pour découvrir l'application.</p>
            <div className="row" style={{ marginTop: 10 }}>
              <Link className="btn primary" to="/importer">Importer</Link>
              <button className="btn" onClick={async () => { await api.post("/api/demo"); notify("Exemples fictifs chargés", "ok"); bump(); }}>Charger des exemples fictifs</button>
            </div>
          </div>
        ) : (
          <>
            <Kpis s={stats!.summary} />
            <div className="grid grid-2">
              <div className="card">
                <div className="card-head">
                  <div><h2>Évolution mensuelle</h2></div>
                  <MetricSwitch value={metric} onChange={setMetric} withMean={false} />
                </div>
                <Chart option={monthsChart(stats!.time.months ?? [], metric)} ariaLabel="Évolution mensuelle" />
              </div>
              <div className="card">
                <div className="card-head"><div><h2>Heures des contrôles</h2><p>Nombre d'amendes par heure</p></div></div>
                <Chart option={columnChart((stats!.time.hours ?? []).map((h) => `${h.hour}h`), stats!.time.hours ?? [], "count")} ariaLabel="Amendes par heure" />
              </div>
            </div>
            <div className="grid grid-3">
              <RankingCard title="Lignes physiques" ranking={stats!.rankings.lines} limit={5} onPick={(i) => navigate(`/carte?line=${encodeURIComponent(i.key)}`)} />
              <RankingCard title="Relations O → D" ranking={stats!.rankings.od} limit={5} />
              <RankingCard title="Gares" ranking={stats!.rankings.stations} limit={5} onPick={(i) => navigate(`/carte?station=${encodeURIComponent(i.key)}`)} />
            </div>
            <div className="grid grid-2">
              <RankingCard title="Catégories de trains" ranking={stats!.rankings.train_types} limit={6} />
              <div className="card">
                <div className="card-head"><h2>À faire</h2></div>
                <ul style={{ margin: 0, paddingLeft: 18 }} className="secondary">
                  <li>{number(sys?.user?.pending_drafts ?? 0)} amende(s) extraite(s) en attente de validation — <Link to="/importer">valider</Link></li>
                  <li>{number(stats!.summary.not_geolocated ?? 0)} amende(s) non géolocalisée(s) — <Link to="/amendes">compléter</Link></li>
                  <li>{number((stats!.summary.by_geo_status?.path_inferred ?? 0))} trajet(s) présumé(s) à confirmer</li>
                </ul>
              </div>
            </div>
            <Caveats items={stats!.caveats.slice(0, 2)} />
          </>
        )}
      </div>
    </div>
  );
}
