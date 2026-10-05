# ICE-800 Beta — Product Specification

## Product thesis

ICE-800 turns credit-card management into a control system. It observes balances, limits, statements and due dates; computes individual and global utilization; ranks the next action; simulates decisions before they are made; and, when an authorized credit report is available, adds report-level diagnostic factors without pretending to forecast exact score gains.

## Beta user journey

1. Tester receives a controlled invite code.
2. Tester registers, accepts the current Beta Terms and Privacy versions, and enters the onboarding launchpad.
3. Tester connects a supported institution through the provider flow.
4. ICE-800 synchronizes card/account and available liability data.
5. Tester reviews/customizes strategy thresholds.
6. Tester optionally authorizes the configured credit-report adapter.
7. Dashboard presents global utilization, card-by-card utilization, next best action, priority queue and calendar.
8. Simulator shows the utilization effect of a proposed spend/payment before the user acts.
9. Optimization Engine compares debt/balance transfer, credit-line reallocation and new-card opportunities before suggesting new credit.
10. Application Hub prioritizes prequalification/eligibility checks when available and then the official issuer application path.
11. Autopilot/scheduler refreshes data and creates actionable alerts.
12. Tester can submit structured feedback, export data, disconnect providers or delete the account.

## Decision hierarchy

1. Overdue / payment-history risk.
2. Upcoming statement payment obligation.
3. High utilization near an observed/estimated cutoff.
4. Portfolio/card utilization above configured thresholds.
5. Credit-report derogatories or collections.
6. Hard-inquiry / age / other report diagnostics.
7. Debt-transfer / credit-line reallocation opportunities.
8. New-card opportunity only after lower-risk interventions are evaluated.
9. Low-impact optimization opportunities.

The engine never claims that a specific payment will produce a specific number of score points.

## Optimization Engine (Beta 2)

### Debt Transfer Optimizer

Models a proposed balance/debt transfer using source APR, promotional APR, promotional duration, transfer fee and target available credit. It returns the transferable amount, fee, monthly payoff target, estimated interest under the baseline vs promo scenario, and estimated net savings. It does not execute transfers.

### Credit Line Engineering

Models moving available credit between eligible cards of the same issuer. It shows source/target utilization before and after and explicitly preserves global utilization when total credit is unchanged. Policy eligibility is versioned by issuer; unknown issuers are treated as `confirm_with_issuer`, not assumed eligible.

### New Card Opportunity Engine

Produces a transparent `ICE Fit` score from candidate-card attributes and user priorities. It rewards prequalification routes, rewards fit and useful introductory features, while penalizing annual fees when unwanted, overlap with current cards, recent inquiries and recent account openings. ICE Fit is not an approval probability and never forecasts score points.

### Application / Prequalification Hub

Routes users to a prequalification/eligibility step first when one is available, then to the official issuer application page if the user selects the card. Commercial compensation must never alter ICE Fit and sponsored inventory must be labeled separately.

## Beta-specific product controls

- Invite-only registration; invite codes can be single-use.
- Tester cohort field.
- Versioned Terms/Privacy consent at registration.
- Credit-report consent remains separate and explicit.
- Onboarding completion meter.
- In-product feedback form: bug, idea, confusing, other; optional 1–5 rating.
- Minimal allowlisted telemetry events only.
- Operator scripts for invite generation and aggregate Beta review.

## Data model additions

`beta_profiles`: cohort, invite fingerprint, joined/last-seen, onboarding completion, strategy reviewed.

`beta_feedback`: user, type, optional rating, message, page, timestamp.

`product_events`: user, allowlisted event name, coarse page, timestamp.

No arbitrary telemetry object is accepted by the API.

## Success criteria for founder Beta

A 5–20-person cohort should establish whether users can:

- complete onboarding without operator help;
- connect at least one institution where supported;
- understand individual vs global utilization;
- identify the next action without reading documentation;
- use the simulator before a purchase/payment decision;
- distinguish an estimated cutoff from a provider-reported date;
- understand that score improvement is probabilistic, not guaranteed;
- submit useful feedback when a flow is confusing or broken.

Suggested operational metrics: onboarding completion rate, successful connection rate, weekly active testers, simulations per tester, alert/action engagement, bug count by severity, and qualitative rating. Do not optimize for compulsive checking or excessive credit-score monitoring.

## Not in Beta

- Automated payments or money movement.
- Public self-service production bureau onboarding.
- Exact score forecasts.
- Automated submission of credit applications.
- Affiliate compensation influencing the ICE Fit score.
- Lender underwriting decisions.
- Public App Store / Play Store release.


## Versioned issuer-policy examples

- Chase credit-line exchange: official source `https://www.chase.com/personal/credit-cards/creditline-exchange` (verified 2026-10-04).
- Capital One line transfer: official source `https://www.capitalone.com/credit-cards/faq/line-transfer/` (verified 2026-10-04).
- CardMatch discovery/prequalification route: `https://www.bankrate.com/credit-cards/tools/cardmatch/` (verified 2026-10-04).

These are treated as changeable product-policy data, not permanent business logic.
