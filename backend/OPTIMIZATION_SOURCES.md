# ICE-800 Optimization Engine — versioned external references

Verified: 2026-10-04. These references are operational inputs, not permanent assumptions. Production should re-check them periodically.

## Credit-line reallocation

- Chase Credit Line Exchange: https://www.chase.com/personal/credit-cards/creditline-exchange
  - Official page states eligible customers can move available credit between personal Chase cards or between business Chase cards.
  - No fee or credit check for the exchange described there; eligibility/minimums/restrictions apply.
- Capital One Line Transfer: https://www.capitalone.com/credit-cards/faq/line-transfer/
  - Official page states eligible customers may move part of available credit between eligible Capital One and/or Discover cards.
  - Outstanding balances stay on their original accounts; the operation changes credit lines, not debt balances.
  - Eligibility and frequency restrictions apply.

## Balance transfers

- Capital One balance-transfer overview: https://www.capitalone.com/credit-cards/balance-transfer/
  - Official page notes fees may apply and that balances from another Capital One card or affiliate cannot be transferred to a Capital One card.
  - Production rules should be issuer-specific and offer-specific.

## Prequalification / application discovery

- Bankrate CardMatch: https://www.bankrate.com/credit-cards/tools/cardmatch/
  - Platform describes personalized/prequalified partner offers and a soft credit pull for its matching flow.
  - It does not represent every issuer or every available product.

## Product-design rules

1. ICE Fit must not be altered by affiliate economics.
2. Sponsored inventory, if ever added, must be labeled separately from algorithmic ranking.
3. Live terms must be refreshed immediately before recommendation/application handoff.
4. A prequalification/eligibility result is not an approval guarantee.
5. ICE-800 does not submit a formal credit application without an explicit user action.
