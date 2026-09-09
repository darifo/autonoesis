import { describe, expect, it } from "vitest";

import {
  PROTOTYPE_DISCLOSURE,
  PROTOTYPE_LABEL,
  presentRuntimePhase,
} from "./maturity";

describe("runtime maturity presentation", () => {
  it("never upgrades an unverified API phase to a production claim", () => {
    expect(presentRuntimePhase("engineering-preview")).toEqual({
      label: PROTOTYPE_LABEL,
      productionProven: false,
    });
    expect(presentRuntimePhase("production")).toEqual({
      label: "Unverified Runtime",
      productionProven: false,
    });
  });

  it("keeps the live-API and sample-data boundary explicit", () => {
    expect(PROTOTYPE_DISCLOSURE).toContain("真实平台 API");
    expect(PROTOTYPE_DISCLOSURE).toContain("错误状态而非样例");
    expect(PROTOTYPE_DISCLOSURE).toContain("未达生产级");
  });
});
