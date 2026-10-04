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

export interface Timeline {
  patient_id: string;
  start?: string;
  end?: string;
  series: Record<string, number | string | boolean | null>[];
  note?: string;
}
