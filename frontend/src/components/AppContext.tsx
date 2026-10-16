import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import type { Options, Settings } from "../types";

interface Toast {
  id: number;
  text: string;
  kind: "ok" | "err" | "info";
}

interface Ctx {
  options: Options | null;
  settings: Settings | null;
  reloadSettings: () => Promise<void>;
  notify: (text: string, kind?: Toast["kind"]) => void;
  dataVersion: number;
  bump: () => void;
}

const AppCtx = createContext<Ctx | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<Options | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [dataVersion, setDataVersion] = useState(0);
  const seq = useRef(0);

  const reloadSettings = useCallback(async () => {
    setSettings(await api.get<Settings>("/api/settings"));
  }, []);

  useEffect(() => {
    api.get<Options>("/api/options").then(setOptions).catch(() => undefined);
    reloadSettings().catch(() => undefined);
  }, [reloadSettings]);

  const notify = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = ++seq.current;
    setToasts((t) => [...t, { id, text, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 7000 : 4000);
  }, []);

  const bump = useCallback(() => setDataVersion((v) => v + 1), []);

  const value = useMemo(() => ({ options, settings, reloadSettings, notify, dataVersion, bump }), [options, settings, reloadSettings, notify, dataVersion, bump]);
  return (
    <AppCtx.Provider value={value}>
      {children}
      <div className="toast-host" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>
        ))}
      </div>
    </AppCtx.Provider>
  );
}

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error("AppProvider manquant");
  return c;
}

export function label(dict: Record<string, string> | undefined, key: string | null | undefined): string {
  if (!key) return "—";
  return dict?.[key] ?? key;
}
