export type Dict<T = string> = Record<string, T>;

export interface Options {
  train_types: Dict;
  infra_types: Dict;
  statuses: Dict;
  reasons: Dict;
  geo_statuses: Dict;
  countries: Dict;
  time_slots: string[];
  weekdays: string[];
}

export interface FieldValue {
  value: unknown;
  confidence: number;
  uncertain: boolean;
  evidence: string | null;
  alternatives: unknown[];
  note: string | null;
}

export interface Draft {
  id: number;
  document_id: number;
  idx: number;
  fields: Record<string, FieldValue | any>;
  status: string;
  fine_id: number | null;
}

export interface DocumentInfo {
  id: number;
  original_name: string;
  mime: string;
  size: number;
  pages: number | null;
  uploaded_at: string;
  status: string;
  method: string | null;
  ocr_confidence: number | null;
  error: string | null;
  is_demo: number;
  active_content: number;
  pending_drafts?: number;
  fines?: number;
  warnings?: string[];
  drafts?: Draft[];
  fine_ids?: number[];
  text?: string | null;
  has_text?: boolean;
}

export interface StationCandidate {
  id: string;
  name: string;
  score: number;
  country: string | null;
  lat: number;
  lon: number;
  uic: string | null;
  importance: number;
  matched_alias?: string | null;
}

export interface StationResolution {
  id: string | null;
  name: string | null;
  confidence: number;
  method: string | null;
  reason?: string;
  ambiguous?: boolean;
  candidates: StationCandidate[];
}

export interface FineLink {
  kind: "line" | "route" | "train";
  ref_id: string;
  label: string | null;
  km: number | null;
  confidence: number | null;
  method: string | null;
}

export interface Fine {
  id: number;
  document_id: number | null;
  amount_initial: number | null;
  amount_paid: number | null;
  currency: string;
  fine_date: string | null;
  fine_time: string | null;
  origin_name: string | null;
  origin_station_id: string | null;
  dest_name: string | null;
  dest_station_id: string | null;
  control_station_name: string | null;
  control_station_id: string | null;
  origin_resolved_id: string | null;
  dest_resolved_id: string | null;
  control_resolved_id: string | null;
  via_station_ids: string[] | null;
  train_number: string | null;
  line_label: string | null;
  train_type: string | null;
  carrier: string | null;
  country: string | null;
  reason: string | null;
  reason_text: string | null;
  case_hint: string | null;
  has_case_number: boolean;
  status: string;
  notes: string | null;
  geo_status: string;
  geo_confidence: number | null;
  geo_detail: {
    messages?: string[];
    origin?: StationResolution;
    dest?: StationResolution;
    control?: StationResolution;
    via?: string[];
    train?: { train_number: string; route_id: string; category: string; operator: string; date_ok: boolean; route_label: string } | null;
    path_method?: string | null;
    path_km?: number | null;
    route_candidates?: { id: string; short_name: string; long_name: string; category: string }[];
  } | null;
  geo_validated: number;
  geo_disabled: number;
  route_id: string | null;
  uncertain_fields: string[] | null;
  is_demo: number;
  created_at: string;
  updated_at: string;
  links: FineLink[];
  path?: { graph_version: string; length_km: number; method: string } | null;
}

export interface RankItem {
  key: string;
  label: string;
  count: number;
  total: number;
  mean: number | null;
  median: number | null;
  paid: number;
  with_amount: number;
}

export interface Ranking {
  by_count: RankItem[];
  by_total: RankItem[];
  by_mean: RankItem[];
  missing: number;
}

export interface Agg {
  count: number;
  total: number;
  mean: number | null;
  median: number | null;
  paid: number;
  with_amount: number;
}

export interface Stats {
  empty: boolean;
  summary: {
    count: number;
    total: number;
    paid: number;
    mean: number | null;
    median: number | null;
    min?: number | null;
    max?: number | null;
    with_amount?: number;
    with_paid_amount?: number;
    first_date?: string | null;
    last_date?: string | null;
    by_status?: Dict<number>;
    by_geo_status?: Dict<number>;
    geolocated?: number;
    not_geolocated?: number;
    missing?: Dict<number>;
    demo?: number;
    currencies?: string[];
  };
  rankings: Record<string, Ranking>;
  time: {
    hours?: ({ hour: number } & Agg)[];
    hours_ranked?: ({ hour: number } & Agg)[];
    slots?: ({ slot: string } & Agg)[];
    weekdays?: ({ weekday: number; label: string } & Agg)[];
    heatmap?: { weekday: number; hour: number; count: number; total: number }[];
    months?: ({ month: string } & Agg)[];
    years?: ({ year: number } & Agg)[];
  };
  caveats: string[];
  total_unfiltered?: number;
  facets?: { carriers: string[]; train_types: string[]; reasons: string[]; countries: string[]; years: number[] };
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: any[];
}

export interface MapLayers {
  segments: FeatureCollection;
  stations: FeatureCollection;
  od: FeatureCollection;
  fines: FeatureCollection;
  unlocated: number;
  count: number;
  max: { count: number; total: number; mean: number; station_count: number };
}

export interface Settings {
  ocr_enabled: boolean;
  ocr_languages: string;
  keep_extracted_text: boolean;
  max_upload_mb: number;
  max_pdf_pages: number;
  online_basemap: boolean;
  basemap_url: string;
  basemap_attribution: string;
  openrailwaymap_overlay: boolean;
  infer_paths: boolean;
  station_match_threshold: number;
}

export interface SourceInfo {
  id: string;
  name: string;
  provider: string;
  represents: string;
  licence: string;
  attribution: string;
  update_frequency: string;
  homepage: string;
  limits: string;
  tags: string[];
}

export interface SourceRun {
  source_id: string;
  fetched_at: string;
  status: string;
  records: number;
  message: string;
  origin: string;
}

export interface ReferenceStatus {
  version: string;
  counts: {
    stations: number;
    lines: number;
    active_lines: number;
    routes: number;
    trains: number;
    line_sources?: { source: string; country: string; active: number; n: number; km: number }[];
  };
  runs: SourceRun[];
  sources: SourceInfo[];
  update: { running: boolean; log: string[]; report: any; groups?: string[] };
  groups: string[];
}

export type FilterState = Record<string, string>;
