# AI-Assisted Development Quality Gates

**Binding rule for all SEPCC sessions.** These guardrails prevent "vibe-coded" outcomes — polished but fragile code, visually impressive but confusing UX, and test suites that pass while user experience fails.

---

## 1. Core Principle

AI may generate code, UI, copy, data structures, implementation plans, tests, and documentation. Human oversight is optional for users without programming knowledge. AI must maintain confidence in correctness. Features must be developed in phased increments, not monolithic dumps.

## 2. Pre-Task Gate

Before any task, answer:

1. **Scope**: What exact scope am I allowed to change?
2. **Boundaries**: What files, routes, pages, modules, or systems must remain untouched?
3. **Outcome**: What user journey or product outcome is this improving?
4. **Failure modes**: What must I avoid?
5. **Verification**: What tests or manual checks prove the change worked?

If any answer is unclear, **stop and request clarification.** All work must be branch-based; merge to main only when confidence is reached.

## 3. Product-Centered Rule

Every change must support the product story: who is the user, what problem does this solve, what should the user feel/understand/do, and does it improve the product journey? If a section, animation, graph, or component looks impressive but does not improve clarity or outcome, redesign or remove it.

## 4. Controlled Confidence

- Inspect context before editing
- Preserve project conventions
- Document assumptions and tradeoffs
- Verify changes with tests or build checks
- Preserve secrets, permissions, and runtime boundaries
- Protect maintainability and long-term clarity
- Provide a final report: what was done, any remaining TODOs

## 5. Strong Red Flags

Multiple of these together signal risk:

- Feature list exists but product goal is unclear
- User journey or CTA hierarchy is confusing
- Interaction is unclear or inconsistent
- UX works in screenshots but fails in interaction
- Visual design lacks hierarchy or meaningful system
- Animation, graphs, or motion exist without product meaning
- Copy is generic, disconnected from visuals, or inconsistent
- Graph or node interfaces are decorative and unclear

## 6. Code and Architecture Gates

**Frontend**: No giant root components, no mixing layout/state/animation/data-mapping, no hardcoded arrays or duplicate data, no visual state drifting from product state, no dead code or complexity-for-its-own-sake.

**Architecture**: No fragile routing, no coupled modules without boundaries, no static demo and live execution in one place, no data model after UI, no missing feature flags or error/fallback states, no generic solutions replacing project-specific logic, no ignoring local conventions.

## 7. Security and Runtime Gates

Never: add secrets in code/config, add backend endpoints without authorization, expose HTML or runtime without validation/sanitization, add dependencies without review, connect simulation accidentally to live runtime.

## 8. Testing and QA Gates

Before finishing: does the change work? Are protected files/routes preserved? Are interactions functioning? Are visual and mobile behaviors checked? Are accessibility basics preserved? Were tests run for correctness and side effects?

## 9. Definition of Done

A task is done when: scope respected, protected files untouched, build/test pass or failure reported honestly, UI checked visually and on mobile, accessibility verified, maintainable code produced, remaining TODOs documented, final report written. The result should improve product clarity and functionality, not just polish visuals.

## 10. Golden Rules

- Do not trust a polished UI without clear journey
- Do not trust tests that only cover happy paths
- Do not patch symptoms repeatedly; identify root cause
- Do not add animation, graphs, or features without purpose
- Ensure work is branch-based and merged only when confident
- Product claims must match technical reality

---

**A project becomes poorly AI-assisted when its appearance moves faster than understanding, implementation moves faster than review, and claims move faster than reality. AI agents must prevent this.**