// Palette sombre validée (contraste >= 3:1 sur la surface #16181b, séparation daltonisme vérifiée).
// L'ordre des teintes est fixe : une catégorie garde toujours la même couleur.
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

export const TRAIN_TYPE_COLORS: Record<string, string> = {
  TER: SERIES[0],
  TGV: SERIES[1],
  INTERCITES: SERIES[2],
  TRANSILIEN: SERIES[3],
  RER: SERIES[4],
  SNCB: SERIES[6],
  EUROSTAR: SERIES[7],
  AUTRE: "#8b9097",
  INCONNU: "#5d6168",
};

export const TRAIN_TYPE_ORDER = ["TER", "TGV", "INTERCITES", "TRANSILIEN", "RER", "SNCB", "EUROSTAR", "AUTRE"];

// Réseau physique : neutres (il ne doit pas concurrencer les couches d'amendes).
export const INFRA_COLORS: Record<string, string> = {
  lgv: "#e8e6e1",
  classique: "#8d939b",
  raccordement: "#5a6068",
  inconnu: "#7a8088",
};

// Séquentiel (magnitude) pour fond sombre : faible = proche du fond, fort = clair.
export const SEQUENTIAL = ["#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#b7d3f6", "#e3eefc"];

export const SLOT_COLORS: Record<string, string> = {
  "nuit (0h-5h)": SERIES[6],
  "pointe matin (6h-9h)": SERIES[1],
  "journée (10h-15h)": SERIES[2],
  "pointe soir (16h-19h)": SERIES[4],
  "soirée (20h-23h)": SERIES[0],
};

export const GEO_COLORS: Record<string, string> = {
  train_confirmed: "#0ca30c",
  manual: "#0ca30c",
  train_route: "#fab219",
  path_inferred: "#fab219",
  od_only: "#ec835a",
  station_only: "#ec835a",
  none: "#d03b3b",
};

export const INK = {
  primary: "#eeede9",
  secondary: "#b4b3ad",
  muted: "#83827d",
  grid: "#2a2c30",
  axis: "#3a3d42",
  surface: "#16181b",
};
