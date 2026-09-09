export const PROTOTYPE_LABEL = "Prototype / Demo";

export const PROTOTYPE_DISCLOSURE =
  "数据页面直连真实平台 API（未连接时显示错误状态而非样例）；总览页仍为静态演示，平台能力未达生产级。";

export type RuntimePresentation = {
  label: string;
  productionProven: false;
};

export function presentRuntimePhase(phase: unknown): RuntimePresentation {
  return {
    label: phase === "engineering-preview" ? PROTOTYPE_LABEL : "Unverified Runtime",
    productionProven: false,
  };
}
