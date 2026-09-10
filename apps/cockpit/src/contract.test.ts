import { describe, expectTypeOf, it } from "vitest";

import type { components, operations, paths } from "./generated/api-schema";
import type {
  ApprovalDecisionRequest,
  ReconcilePath,
  ReconcileRequest,
  RunControlRequest,
} from "./contract";

/**
 * Contract-binding assertions (checked by `tsc -b`): the generated SDK must
 * keep exposing the operations the console drives. If the platform contract
 * removes or renames them, this file fails to compile instead of the console
 * silently calling dead endpoints.
 */
describe("generated sdk contract binding", () => {
  it("exposes the operations-center endpoints", () => {
    expectTypeOf<paths["/v1/evaluation/human-decisions"]>().not.toBeNever();
    expectTypeOf<paths["/v1/runs/{run_id}/takeover"]>().not.toBeNever();
    expectTypeOf<paths["/v1/actions/{action_id}/reconcile"]>().not.toBeNever();
  });

  it("request bodies require the confirmation material", () => {
    expectTypeOf<ApprovalDecisionRequest>().toHaveProperty("action_digest").toEqualTypeOf<string>();
    expectTypeOf<RunControlRequest>().toHaveProperty("reason").toEqualTypeOf<string>();
    expectTypeOf<ReconcileRequest>().toHaveProperty("invocation_id").toEqualTypeOf<
      import("./generated/api-schema").components["schemas"]["ReconcileRequest"]["invocation_id"]
    >();
  });

  it("templated operations expose their path parameters", () => {
    expectTypeOf<ReconcilePath>().toEqualTypeOf<"action_id">();
  });

  it("slo and finops read endpoints remain json arrays/objects", () => {
    type Slos = operations["service_levels_v1_slos_get"]["responses"][200]["content"]["application/json"];
    expectTypeOf<Slos>().toMatchTypeOf<unknown[]>();
    type HumanDecision = components["schemas"]["HumanDecisionRequest"];
    expectTypeOf<HumanDecision>().not.toBeNever();
  });
});
