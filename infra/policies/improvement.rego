package autonoesis.improvement

import future.keywords.in

# ADR-0011 / ADR-0025: the self-evolution pipeline must never propose changes to
# governance roots. This list mirrors the domain FORBIDDEN_IMPROVEMENT_TARGETS
# set and is enforced independently of the in-process Application guard.
forbidden_targets := {
	"identity",
	"delegation",
	"tenant_isolation",
	"policy_root",
	"audit_retention",
	"kill_switch",
	"production_code",
	"infrastructure",
}

default allow := {"allowed": false, "reason": "denied by default"}

allow := {"allowed": true, "reason": "target is improvable"} if {
	not input.target in forbidden_targets
	is_string(input.target)
	trim_space(input.target) != ""
}
