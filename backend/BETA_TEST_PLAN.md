# ICE-800 Beta Test Plan

Each tester should attempt these scenarios and submit feedback for any ambiguity.

1. Register with an unused invite; verify a reused invite is rejected.
2. Log out/in and verify session handling.
3. Connect an institution; verify only their accounts appear.
4. Disconnect it and confirm the connection disappears.
5. Review a card with known limit/balance and manually verify utilization math.
6. Check global utilization against the sum of known card limits/balances.
7. Simulate a purchase and a payment; verify resulting utilization.
8. Verify due-date priority beats micro-optimization of utilization.
9. If cutoff is estimated, verify the UI labels it as estimated.
10. Change strategy thresholds and verify recommendations update.
11. Submit Beta feedback.
12. Export account data and inspect the export.
13. Delete the account and verify the session no longer works.
14. On mobile, install the PWA and repeat dashboard/simulator flows.
15. Test with slow/failed provider connectivity and confirm errors do not create fabricated financial values.


## Optimization Engine scenarios

1. Debt transfer: compare a 20%+ APR balance with a 0% promo offer plus a transfer fee; verify that monthly payoff and net savings are understandable.
2. Line reallocation: simulate $5,000/$1,000 limits with a highly utilized target card; confirm that per-card utilization changes while global utilization does not.
3. Policy guardrail: select an unknown issuer and verify that ICE asks for issuer confirmation instead of assuming eligibility.
4. New-card ranking: toggle “carry balance” and “need balance transfer”; confirm that the ranking changes for rational, visible reasons.
5. Application hub: verify that the user sees a prequalification/discovery step before a formal application route.
