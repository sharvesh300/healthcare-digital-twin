// Shapes of the twin API (src/twin/api, src/twin/streaming/state.py). Times are ISO strings
// with the clinic's UTC offset.

export type GlucoseBand = "very_low" | "low" | "in_range" | "high" | "very_high";
export type GlucoseTrend = "rising_fast" | "rising" | "steady" | "falling" | "falling_fast";
export type SleepStage = "awake" | "light" | "deep" | "rem";
export type ActivityLevel = "sedentary" | "light" | "moderate" | "vigorous";

export interface Signal {
  value: number | string | null;
  unit: string | null;
  time: string | null;
  source: string | null;
  /** band / level / stage, "stale", or null for signals without rules */
  status: string | null;
}

export interface GlucoseSignal extends Signal {
  trend: GlucoseTrend | null;
  rate_mg_dl_min: number | null;
}

export interface SleepSignal extends Signal {
  until: string | null;
}

export interface TwinState {
  patient_id: string;
  version: number;
  as_of: string | null;
  streaming: boolean;
  glucose: GlucoseSignal;
  heart_rate: Signal;
  activity: Signal;
  steps_today: Signal;
  sleep: SleepSignal;
  spo2: Signal;
  respiration_rate: Signal;
  hrv_rmssd: Signal;
  skin_temp: Signal;
  stress: Signal;
  eda: Signal;
  active_kcal: Signal;
}

export type SignalKey = Exclude<keyof TwinState, "patient_id" | "version" | "as_of" | "streaming">;

export interface PatientInfo {
  patient_id: string;
  display_name: string | null;
  given_name: string | null;
  family_name: string | null;
  sex: string;
  age: number;
  source: string;
  source_subject_id: string;
  tags: string[];
  /** first and last recorded sensor reading (null: no sensors) */
  window?: { start: string; end: string } | null;
}

export interface PatientTwin {
  patient: PatientInfo;
  state: TwinState;
}

export interface LiveSummary {
  streaming: boolean;
  version: number;
  glucose: { value: number | null; status: string | null; trend: GlucoseTrend | null; time: string | null };
}

export interface PatientListItem {
  patient_id: string;
  given_name: string | null;
  family_name: string | null;
  sex: string;
  age: number;
  source: string;
  source_subject_id: string;
  tags: string[];
  window_start: string | null;
  window_end: string | null;
  live: LiveSummary | null;
}

export interface Transition {
  signal: "glucose" | "glucose_trend" | "heart_rate" | "activity" | "sleep" | "spo2";
  time: string;
  from: string | null;
  to: string;
  value: number | null;
  state_version?: number;
}

export interface Readings {
  since: string;
  until: string;
  series: Record<string, [string, number][]>;
}

export interface ReplayProgress {
  status: "playing" | "paused" | "ended";
  cursor: string;
  start: string;
  end: string;
  speed: number;
}

export interface SnapshotMessage {
  type: "snapshot";
  version: number;
  state: TwinState;
  /** chart points; when present they replace the client's buffers */
  series?: Record<string, [string, number][]>;
  /** recent transitions, newest first; when present they replace the feed */
  feed?: Transition[];
  replay?: { type: "replay" } & ReplayProgress;
}

export type LiveMessage =
  | SnapshotMessage
  | {
      type: "delta";
      patient_id: string;
      version: number;
      time: string | null;
      changes: Record<string, unknown>;
      transitions: Transition[];
    }
  | { type: "heartbeat"; version: number | null }
  | ({ type: "replay" } & ReplayProgress)
  | { type: "error"; detail: string };

// /twin/{id}: the full record (only the parts the UI shows are typed).
export interface TwinRecord {
  patient: PatientInfo & { birth_date: string; race_ethnicity: string | null; address_city: string | null; address_state: string | null };
  provenance: { cohort: string; composite: boolean; synthetic_analytes: string[]; synthetic_sensor_channels: string[]; note: string };
  baseline: Record<string, number | string | boolean | string[] | null> | null;
  observations_latest: {
    analyte: string;
    loinc: string;
    category: string;
    effective_at: string;
    value_num: number | null;
    value_display: string | null;
    ucum_unit: string | null;
    source: string;
    is_synthetic: boolean;
  }[];
  conditions: { condition_group: string; first_onset: string; active: boolean; conditions: string[]; all_synthetic: boolean }[];
  medications: {
    medication: string;
    drug_class: string | null;
    glucose_lowering: boolean | null;
    started_at: string;
    ended_at: string | null;
    active: boolean;
    dose_value: number | null;
    dose_unit: string | null;
    source: string;
    is_synthetic: boolean;
  }[];
  cgm: {
    window: { glucose_source: string; period_start: string; period_end: string; n: number; mean_mg_dl: number; gmi: number } | null;
    consistency: { hba1c: number | null; gmi: number; abs_diff: number | null; status: string } | null;
    daily: {
      day: string;
      n: number;
      coverage_pct: number;
      mean_mg_dl: number;
      cv_pct: number;
      gmi: number;
      pct_very_low: number;
      pct_low: number;
      pct_target: number;
      pct_high: number;
      pct_very_high: number;
    }[];
  };
}


// ── /patients/{id}/record: the patient record (src/twin/record/assemble.py) ──

export type Flag = "high" | "low" | "normal";
export type Range = [number | null, number | null];

export interface Provenance {
  source: string;
  is_synthetic: boolean;
}

export interface VisitBrief {
  encounter_id: string;
  class: string;
  type: string | null;
  start: string;
}

export interface VisitSummary extends VisitBrief, Provenance {
  reason: string | null;
  end: string | null;
  duration_h: number | null;
  counts: { tests: number; diagnoses: number; medications: number };
  /** anything recorded at it; visits with nothing recorded have no detail worth opening */
  has_records: boolean;
}

export interface Dosage {
  dose_value: number | null;
  dose_unit: string | null;
  times_per_day: number | null;
  as_needed: boolean;
  /** "5 mg · once daily"; null when the source recorded neither dose nor frequency */
  text: string | null;
}

export interface MedicationSummary extends Provenance {
  rxcui: number;
  medication: string;
  product: string | null;
  drug_class: string | null;
  drug_class_display: string | null;
  glucose_lowering: boolean;
  active: boolean;
  dosage: Dosage;
  started_at: string;
  ended_at: string | null;
  first_started_at: string;
  episodes: number;
  /** given during one visit only (an anaesthetic, a one-off injection) */
  single_day: boolean;
  encounter_id: string | null;
}

export interface ConditionSummary extends Provenance {
  concept_id: number;
  system: string;
  code: string;
  display: string;
  kind: "diagnosis" | "finding";
  group: string | null;
  group_display: string | null;
  active: boolean;
  episodes: number;
  first_onset: string;
  current: { onset_at: string; abated_at: string | null; active: boolean };
  last_change: string;
}

export interface ResultBrief extends Provenance {
  at: string;
  /** numeric components by analyte ({ sbp, dbp } for blood pressure) */
  values: Record<string, number>;
  /** a coded answer ("Never smoked") */
  text: string | null;
  flag: Flag | null;
  encounter_id: string | null;
}

export interface MeasureSummary {
  measure: string;
  display: string;
  panel: string;
  panel_display: string;
  unit: string | null;
  digits: number;
  analytes: string[];
  ranges: Record<string, Range | null>;
  count: number;
  out_of_range: number;
  latest: ResultBrief;
  previous: ResultBrief | null;
  spark: [string, number][];
  is_synthetic: boolean;
}

export interface Panel {
  panel: string;
  display: string;
  measures: MeasureSummary[];
}

export interface Derived {
  value: number;
  is_synthetic: boolean;
  display: string;
  unit: string | null;
}

export interface RecordSection<T> {
  total: number;
  active: number;
  items: T[];
}

export interface RecordOverview {
  patient: PatientInfo & { birth_date: string; mrn: string | null; race_ethnicity: string | null; address_city: string | null; address_state: string | null };
  provenance: { cohort: string; composite: boolean; note: string };
  summary: {
    medications_active: number;
    glucose_lowering_active: number;
    diagnoses_active: number;
    last_visit: VisitSummary | null;
    headline: MeasureSummary[];
  };
  medications: RecordSection<MedicationSummary> & { single_day: number };
  conditions: { diagnoses: RecordSection<ConditionSummary>; findings: RecordSection<ConditionSummary> };
  tests: { total: number; out_of_range: number; panels: Panel[] };
  visits: { total: number; with_records: number; recent: VisitSummary[] };
  derived: Record<string, Derived>;
  cgm: TwinRecord["cgm"] | null;
}

export interface TestsList {
  total: number;
  panels: Panel[];
}

export interface MeasureDetail {
  measure: MeasureSummary;
  stats: {
    count: number;
    first_at: string;
    latest_at: string;
    out_of_range: number;
    by_analyte: Record<string, { min: number; max: number; mean: number }>;
  };
  results: (ResultBrief & { visit: VisitBrief | null })[];
  related: { panel: MeasureSummary[]; medications: MedicationSummary[]; diagnoses: ConditionSummary[] };
}

export type ConditionsList = RecordSection<ConditionSummary>;

export interface ConditionDetail {
  condition: ConditionSummary;
  episodes: (Provenance & { onset_at: string; abated_at: string | null; active: boolean; duration_days: number | null; visit: VisitBrief | null })[];
  related: { medications: MedicationSummary[]; measures: MeasureSummary[] };
}

export interface MedicationsList extends RecordSection<MedicationSummary> {
  single_day: MedicationSummary[];
}

export interface MedicationDetail {
  medication: MedicationSummary;
  episodes: (Provenance & {
    regimen_id: number;
    product: string | null;
    product_rxcui: string | null;
    dosage: Dosage;
    started_at: string;
    ended_at: string | null;
    active: boolean;
    single_day: boolean;
    visit: VisitBrief | null;
  })[];
  dose_changes: { at: string; from: string; to: string }[];
  related: { diagnoses: ConditionSummary[]; measures: MeasureSummary[] };
}

export interface VisitsPage {
  total: number;
  items: VisitSummary[];
  next_cursor: string | null;
  years: { year: number; count: number }[];
  classes: { class: string; count: number }[];
}

export interface VisitTest extends ResultBrief {
  measure: string;
  display: string;
  panel: string;
  unit: string | null;
  digits: number;
  analytes: string[];
}

export interface VisitDetail {
  visit: VisitSummary;
  tests: { panel: string; display: string; items: VisitTest[] }[];
  diagnoses: { recorded: ConditionSummary[]; resolved: ConditionSummary[] };
  medications: { started: MedicationSummary[]; stopped: MedicationSummary[] };
  previous: VisitSummary | null;
  next: VisitSummary | null;
}

// ── glucose forecast (GET /patients/{id}/predictions/glucose, src/twin/prediction/assemble.py) ──

export type ForecastWarningKind = "very_high" | "high" | "low" | "very_low" | "spike" | "possible_high" | "possible_low";
export type ForecastSeverity = "danger" | "warning" | "info";

export interface ForecastWarning {
  kind: ForecastWarningKind;
  severity: ForecastSeverity;
  horizon_min: number;
  glucose: number;
  message: string;
}

export interface ForecastPoint {
  horizon_min: number;
  time: string;
  glucose: number;
  low: number;
  high: number;
  change: number;
  band: string;
  warnings: ForecastWarningKind[];
}

export interface ForecastModel {
  name: "gru" | "arima";
  label: string;
  version: string;
  trained_on: string;
  horizons: number[];
  band_level: number;
  /** held-out test RMSE per horizon (mg/dL); null where it wasn't measured */
  test_rmse: Record<string, number | null>;
  band_coverage: Record<string, number> | null;
}

export interface ForecastMeal {
  time: string;
  meal_type: string;
  energy_kcal: number | null;
  carbs_g: number | null;
  protein_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
}

export interface GlucoseForecast {
  patient_id: string;
  at: string;
  model: ForecastModel | null;
  origin: { time: string; glucose: number; band: string; trend: GlucoseTrend | null; trend_mg_dl_min: number | null } | null;
  history: { t: string; v: number }[];
  forecast: ForecastPoint[];
  /** readings after the origin: what actually happened (a past `at` only) */
  actual: { t: string; v: number }[];
  warnings: ForecastWarning[];
  inputs: {
    glucose_only: boolean;
    meals: ForecastMeal[];
    heart_rate: boolean;
    activity: boolean;
    missing: string[];
  } | null;
  unavailable: { reason: string } | null;
  caveat: string;
}
