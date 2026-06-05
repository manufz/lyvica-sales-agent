# Reply Classification Guide

When a lead replies, classify into one of these buckets and decide next action.

## Classifications

| Label | Signals | Next Action |
|-------|---------|-------------|
| `not_interested` | unsubscribe, stop, no thanks, not interested, remove me | Mark opt_out, stop all contact |
| `asks_price` | price, cost, how much, rates | Share package pricing |
| `asks_examples` | portfolio, examples, work, samples | Send portfolio link |
| `interested` | yes, send it, sounds good, go ahead | Send website snapshot |
| `ready_to_buy` | pay, invoice, start, proceed, ready | Generate Stripe link |
| `unclear` | anything else | Draft response for Manuel to approve |

## Important
- If `not_interested`: confirm opt-out to Manuel, do NOT attempt re-contact.
- If `unclear` and the reply sounds angry or frustrated: apologize briefly and stop.
- Never assume positive intent when signals are mixed — ask Manuel.
