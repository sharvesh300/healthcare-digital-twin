import { describe, expect, test } from "bun:test";

import type { ForecastModel, ForecastWarning } from "@/lib/api/types";

import { fmtChange, headline, sortWarnings, typicalError, worstKind } from "./format";

const w = (kind: ForecastWarning["kind"], severity: ForecastWarning["severity"], horizon_min: number): ForecastWarning =>
  ({ kind, severity, horizon_min, glucose: 0, message: "" });

describe("warnings", () => {
  test("most severe first, then soonest", () => {
    const sorted = sortWarnings([w("possible_high", "info", 15), w("spike", "warning", 60), w("high", "warning", 45),
      w("very_high", "danger", 60)]);
    expect(sorted.map((x) => x.kind)).toEqual(["very_high", "high", "spike", "possible_high"]);
  });

  test("an info-only forecast gets no headline", () => {
    expect(headline([w("possible_high", "info", 30)])).toBeNull();
    expect(headline([w("possible_high", "info", 15), w("spike", "warning", 45)])?.kind).toBe("spike");
    expect(headline([])).toBeNull();
  });

  test("worst kind at a horizon", () => {
    expect(worstKind(["spike", "very_high"])).toBe("very_high");
    expect(worstKind(["possible_low"])).toBe("possible_low");
    expect(worstKind([])).toBeNull();
  });
});

describe("numbers", () => {
  test("signed change with a true minus", () => {
    expect([fmtChange(12.4), fmtChange(-7.6), fmtChange(0.3)]).toEqual(["+12", "−8", "±0"]);
  });

  test("typical error from the model's test RMSE", () => {
    const model = { test_rmse: { "15": 10.01, "45": null, "60": 22.09 } } as unknown as ForecastModel;
    expect(typicalError(model, 60)).toBe("±22 mg/dL typical error");
    expect(typicalError(model, 45)).toBeNull();
    expect(typicalError(null, 15)).toBeNull();
  });
});
