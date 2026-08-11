package autonoesis.action

import future.keywords.in

default allow := {"allowed": false, "requires_approval": false, "reason": "denied by default"}

allow := {"allowed": true, "requires_approval": false, "reason": "read-only action"} if {
  input.identity.roles[_] in {"platform_admin", "tenant_admin", "operator", "worker"}
  input.action.risk in {"l0_compute", "l1_read"}
}

allow := {"allowed": true, "requires_approval": true, "reason": "write requires approval"} if {
  input.identity.roles[_] in {"platform_admin", "tenant_admin", "operator", "worker"}
  input.action.risk in {"l2_reversible_write", "l3_high_impact_write"}
}
