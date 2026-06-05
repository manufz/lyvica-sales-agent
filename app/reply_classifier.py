"""
Heuristic reply classifier.
Replace or augment with a Hermes/LLM call later by swapping classify_reply_text().
"""

_RULES: list[tuple[list[str], str, str]] = [
    (
        ["unsubscribe", "not interested", "stop", "remove me", "no thanks", "no thank you"],
        "not_interested",
        "mark_opted_out",
    ),
    (
        ["price", "cost", "how much", "pricing", "rates", "fee"],
        "asks_price",
        "send_pricing",
    ),
    (
        ["example", "portfolio", "work", "sample", "previous", "show me"],
        "asks_examples",
        "send_portfolio",
    ),
    (
        ["yes", "interested", "send it", "go ahead", "sure", "sounds good", "please send"],
        "interested",
        "send_snapshot",
    ),
    (
        ["start", "pay", "invoice", "proceed", "ready", "let's go", "sign up"],
        "ready_to_buy",
        "offer_stripe_link",
    ),
]


def classify_reply_text(body: str) -> tuple[str, str]:
    """Returns (classification, recommended_next_action)."""
    lower = body.lower()
    for keywords, classification, action in _RULES:
        if any(kw in lower for kw in keywords):
            return classification, action
    return "unclear", "draft_for_manuel_approval"
