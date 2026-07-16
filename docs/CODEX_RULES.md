# Binding development rules

These 32 rules govern every MediaOS change. Automated checks enforce syntax and dependency boundaries; pull-request evidence and code review enforce intent, scope, data safety, and architecture decisions.

1. **Architecture before code.** Update architecture documentation or add an ADR before changing a boundary.
2. **Implement Phase 0 only.** Every pull request names the Phase 0 objective it satisfies.
3. **No feature without a direct objective.** The pull-request template requires the objective.
4. **No speculative extension.** Non-goals are mandatory in every pull request.
5. **No second leading database.** Architecture checks reject alternate database configuration names and packages.
6. **PostgreSQL is the only truth layer.** The Compose and Python configuration expose one `DATABASE_URL`.
7. **No microservices.** Backend and worker share one package and image.
8. **No technology without a proven bottleneck.** New infrastructure requires evidence and an ADR.
9. **Providers are replaceable.** Later providers implement internal protocols.
10. **External vendors only through internal interfaces.** Direct vendor SDK use is prohibited.
11. **Providers do not change workflow states.** Architecture tests reject direct `current_state` assignments.
12. **Workflow states change only through TransitionService.** Only `workflow_transition_service.py` is allowlisted for assignment.
13. **Every state change is recorded.** Transition tests become a Phase 0.3 merge gate.
14. **Every relevant action creates an AuditEvent.** Use-case integration tests become a merge gate.
15. **Audit events are immutable.** Database permissions/model behavior and tests enforce append-only behavior.
16. **Money is integer cents.** Schema and type tests will reject floating-point money.
17. **Time is UTC.** Schema defaults and serialization tests will enforce timezone-aware UTC.
18. **Primary keys are UUIDs.** Migration and model tests enforce UUID primary keys.
19. **No secrets in the repository.** `.gitignore`, CI pattern checks, and the architecture checker enforce this.
20. **No secrets in logs or API responses.** Central redaction and negative tests are mandatory.
21. **No anonymous write API.** Authentication tests are required for every write route.
22. **No external AI services in Phase 0.** Dependency checks reject external AI SDKs.
23. **No automatic publishing.** Publishing remains a fake interface behind human approval.
24. **No multilingual support in Phase 0.** No locale routing or translation system may be added.
25. **No multi-tenancy in Phase 0.** No tenant abstraction or tenant-scoped database is permitted.
26. **No unnecessary UI complexity.** The internal UI uses simple pages and states without animation platforms.
27. **No refactoring without a concrete need.** Pull requests must link refactoring to their direct objective.
28. **No optimization outside the assignment.** Performance work requires measured evidence.
29. **Every change needs tests.** CI runs backend and frontend checks; pull requests list added tests.
30. **Every architecture change needs an ADR.** The pull-request template and CODEOWNERS review enforce this.
31. **Every pull request names non-goals.** The template contains a required section.
32. **Stop when the definition of done is met.** Completion reports compare evidence with the declared definition of done.

## Enforcement matrix

| Control | Machine enforced | Review enforced |
|---|---:|---:|
| Forbidden infrastructure and external AI dependencies | Yes | Yes |
| Direct workflow-state assignment | Yes | Yes |
| Secret filenames and common secret patterns | Yes | Yes |
| Single database configuration | Yes | Yes |
| Allowed repository structure | Yes | Yes |
| Lint, types, tests, and builds | Yes | Yes |
| Phase scope, objective, non-goals, and cost | Template | Yes |
| ADR necessity and architecture justification | Template | Yes |
| Business correctness, authorization, and data safety | Tests where possible | Yes |

Passing automation is necessary but not sufficient. Reviewers must reject scope expansion or unproved success even when CI is green.

