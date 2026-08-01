# Cockpit

Operator and administrator web application for Case/Goal status, Run timelines, approvals, evidence, evaluations, releases, audit exploration, and kill switches.

The UI implementation starts after an ADR defines authentication, BFF/view-model contracts, and the initial operator journey. It must use `@autonoesis/ts-sdk` and must not access platform databases directly.
