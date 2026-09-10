/**
 * Typed surface over the frozen OpenAPI contract.
 *
 * All request/response shapes come from the generated SDK
 * (`src/generated/api-schema.ts`, produced by `pnpm run gen:api` from
 * `docs/contracts/generated/openapi-v1.json`). The runtime transport stays in
 * `./api`; this module only binds compile-time types so the console cannot
 * drift from the contract without failing `tsc`.
 */

import type { components, operations } from "./generated/api-schema";

// Request bodies used by the operations center.
export type HumanDecisionRequest = components["schemas"]["HumanDecisionRequest"];
export type RunControlRequest = components["schemas"]["RunControlRequest"];
export type ReconcileRequest = components["schemas"]["ReconcileRequest"];
export type PackReasonRequest = components["schemas"]["PackReasonRequest"];
export type PackStableRequest = components["schemas"]["PackStableRequest"];
export type CanaryRequest = components["schemas"]["CanaryRequest"];
export type PromotionRequest = components["schemas"]["PromotionRequest"];
export type ApprovalDecisionRequest = components["schemas"]["ApprovalDecisionRequest"];

// Response shapes for live data pages.
export type ReconcileResponse = operations["reconcile_unknown_action_v1_actions__action_id__reconcile_post"]["responses"][202]["content"]["application/json"];
export type TakeoverResponse = operations["take_over_run_v1_runs__run_id__takeover_post"]["responses"][202]["content"]["application/json"];
export type SlosResponse = operations["service_levels_v1_slos_get"]["responses"][200]["content"]["application/json"];

/** Path-parameter binding check for templated operations (compile-time). */
export type ReconcilePath = keyof operations["reconcile_unknown_action_v1_actions__action_id__reconcile_post"]["parameters"]["path"];
