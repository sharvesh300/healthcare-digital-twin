import { expect, test } from "bun:test";

import { fmtSpan, fromZonedInput, toZonedInput } from "./format";

test("datetime-local values round-trip in the clinic zone (America/Chicago)", () => {
  const t = Date.parse("2026-10-04T14:30:00Z"); // 09:30 CDT
  expect(toZonedInput(t)).toBe("2026-10-04T09:30");
  expect(fromZonedInput("2026-10-04T09:30")).toBe(t);
  expect(fromZonedInput("2026-12-01T09:30")).toBe(Date.parse("2026-12-01T15:30:00Z")); // CST
  expect(fromZonedInput("2026-10-04")).toBeNull();
});

test("spans", () => {
  expect(fmtSpan(3 * 3600_000)).toBe("3 h");
  expect(fmtSpan(90 * 60_000)).toBe("1 h 30 min");
  expect(fmtSpan(45 * 60_000)).toBe("45 min");
  expect(fmtSpan(18_000)).toBe("18 s");
});
