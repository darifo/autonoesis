export const PROTOTYPE_LABEL = "Prototype / Demo";

export const PROTOTYPE_DISCLOSURE =
  "当前页面使用静态样例数据，不代表真实运行状态、生产能力或审计证据。";

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
