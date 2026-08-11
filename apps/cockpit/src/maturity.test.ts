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

  it("keeps the static-data disclosure explicit", () => {
    expect(PROTOTYPE_DISCLOSURE).toContain("静态样例数据");
    expect(PROTOTYPE_DISCLOSURE).toContain("不代表真实运行状态");
  });
});
