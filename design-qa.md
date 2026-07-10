# Decision Cockpit Design QA

## Comparison target

- Source visual truth: `docs/ui_mockups/decision-cockpit-reference.png`
- Browser-rendered implementation: `outputs/ui_decision_cockpit_qa/07-desktop-final.png`
- Combined final comparison input: `outputs/ui_decision_cockpit_qa/08-reference-vs-implementation.png`
- Viewport: 1487 x 1058 pixels for both source and final implementation
- State: `scenario_discovered_fujifilm_dummy_iran_war_escalation_affecting_fujifilm_executive_management_disc_`, pending human review, real Platform API artifacts

## Full-view comparison evidence

The final combined input preserves the selected four-column composition: icon rail, scenario queue, decision workspace, and evidence rail. Header height, emerald and amber hierarchy, card borders, action order, whitespace, and evidence density match the selected direction. The implementation intentionally uses the repository's real scenario, risk, evidence, decision-log, and unknown-item values.

The following source-only values were not copied because they are not present in the real artifacts: the Tavily supplier, assumed USD currency, two contradictions, extra timeline rows, and July evidence dates. The implementation instead shows an unset currency, risk score 64 with medium confidence, zero contradictions, one append-only activity event, four unknown or assumed items, and the actual evidence dates.

## Focused and responsive evidence

A separate focused crop was not required because the final combined input keeps labels, metadata, icons, cards, and evidence text readable at their original 1487 x 1058 resolution. Responsive behavior was checked separately at a 390 x 844 viewport:

- `outputs/ui_decision_cockpit_qa/09-mobile-final.png`
- `outputs/ui_decision_cockpit_qa/11-mobile-queue-final.png`
- `outputs/ui_decision_cockpit_qa/12-mobile-evidence-final.png`

The mobile layout exposes one header navigation, keeps the decision and action flow in document order, and moves the scenario and evidence rails into independently closable drawers without horizontal clipping. Closed drawers are inert and hidden from the named accessibility tree; an open drawer makes the background inert, receives focus, traps Tab navigation, closes with Escape, and restores focus to its trigger.

## Primary interactions tested

- Loaded `/ui/` and `/api/ui/state` from the same FastAPI origin.
- Switched from the selected scenario to a second real scenario and observed the decision workspace refresh.
- Opened the Hold action dialog, confirmed the actor starts blank and required, filled actor and reason fields, and cancelled without mutating the Decision Log.
- Opened and closed both mobile drawers, including Escape, focus restoration, and background focus isolation.
- Checked browser warning and error logs after desktop and mobile flows; no entries were reported.

## Comparison history

### Iteration 1

- Evidence: `outputs/ui_decision_cockpit_qa/10-reference-vs-initial.png`
- [P1] The initial capture was 1472 x 1047 rather than 1487 x 1058, and document-level scrolling clipped the evidence rail.
- [P1] Queue, evidence, header, and activity metadata were too small and light.
- [P2] Long queue owners crowded and wrapped the deadline column.
- [P2] The scenario synopsis used a one-line truncation.
- [P2] One real history item left a large empty bordered region.

Fixes: constrained the cockpit to the viewport with independently scrollable panes, darkened muted text, increased metadata sizes, reserved a no-wrap deadline column, clamped long owners and the synopsis deliberately, and made sparse history compact.

### Iteration 2

- Evidence: `outputs/ui_decision_cockpit_qa/08-reference-vs-implementation.png`
- The implementation capture is exactly 1487 x 1058.
- No page-level clipping remains; long queue content and evidence overflow are contained in their intended panes.
- Metadata and action hierarchy are readable, and the sparse history is compact.

### Iteration 3

- Evidence: `outputs/ui_decision_cockpit_qa/08-reference-vs-implementation.png`, `outputs/ui_decision_cockpit_qa/09-mobile-final.png`, `outputs/ui_decision_cockpit_qa/11-mobile-queue-final.png`, and `outputs/ui_decision_cockpit_qa/12-mobile-evidence-final.png`.
- Review found audit attribution, re-analysis locking and Decision revision identity, risk-score source labeling, truthful queue/history completeness, drawer focus isolation, dialog implicit-submit behavior, and small-text contrast issues.
- Fixes: require an explicit actor; retain decision ID/title, reason, and reassignee in history; label the score as the Treasury metric; lock all decisions through terminal artifact refresh; preserve scenario lineage while content-versioning Decision IDs; normalize only the revision suffix for delta comparison; return all scenario cards and Decision Log actions; make overlays modal to keyboard users; make cancel controls explicit buttons; and darken quiet/amber tokens above 4.5:1 for small text.
- Post-fix browser checks found no warning or error logs, and targeted integration, revision, and delta tests passed.
- No actionable P0, P1, or P2 differences remain.

## Findings

No actionable P0, P1, or P2 findings remain. Real-data copy and count differences are intentional and evidence-backed.

## Open questions

None.

## Follow-up polish

No blocking follow-up polish is required.

final result: passed
