import { lazy, Suspense, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { useApp } from "./components/AppContext";
import { IconChart, IconDashboard, IconList, IconMap, IconSettings, IconUpload, Logo } from "./components/Icons";
import Dashboard from "./pages/Dashboard";
import FinesPage from "./pages/FinesPage";
import ImportPage from "./pages/ImportPage";
import SettingsPage from "./pages/SettingsPage";
import StatsPage from "./pages/StatsPage";

// La carte (MapLibre, WebGL) est chargée à la demande pour alléger les autres pages.
const MapPage = lazy(() => import("./pages/MapPage"));

export default function App() {
  const { dataVersion } = useApp();
  const [pending, setPending] = useState(0);
  useEffect(() => {
    api.get<any>("/api/system").then((s) => setPending(s.user?.pending_drafts ?? 0)).catch(() => undefined);
  }, [dataVersion]);
  const links = [
    { to: "/", label: "Tableau de bord", icon: <IconDashboard />, end: true },
    { to: "/carte", label: "Carte ferroviaire", icon: <IconMap /> },
    { to: "/amendes", label: "Mes amendes", icon: <IconList /> },
    { to: "/importer", label: "Importer", icon: <IconUpload />, badge: pending },
    { to: "/statistiques", label: "Statistiques", icon: <IconChart /> },
    { to: "/parametres", label: "Paramètres", icon: <IconSettings /> },
  ];
  return (
    <div className="app">
      <nav className="nav" aria-label="Navigation principale">
        <div className="brand">
          <Logo className="brand-mark" />
          <div className="brand-text">
            <div className="brand-name">RailFine</div>
            <div className="brand-sub">Analytics · FR / BE</div>
          </div>
        </div>
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => (isActive ? "active" : "")}>
            {l.icon}
            <span className="lbl">{l.label}</span>
            {l.badge ? <span className="badge warn">{l.badge}</span> : null}
          </NavLink>
        ))}
        <div className="nav-foot">Application locale · données privées</div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/carte" element={<Suspense fallback={<div className="page muted">Chargement de la carte...</div>}><MapPage /></Suspense>} />
          <Route path="/amendes" element={<FinesPage />} />
          <Route path="/importer" element={<ImportPage />} />
          <Route path="/statistiques" element={<StatsPage />} />
          <Route path="/parametres" element={<SettingsPage />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}
