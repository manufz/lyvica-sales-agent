import logging

import stripe

from app.config import settings

log = logging.getLogger(__name__)


def get_or_create_checkout_link(package: str) -> str:
    """
    Returns a fixed payment link from env if configured,
    otherwise creates a Stripe Checkout Session.
    """
    if package == "starter":
        if settings.STRIPE_STARTER_LINK:
            return settings.STRIPE_STARTER_LINK
        price_id = settings.STRIPE_STARTER_PRICE_ID
    elif package == "pro":
        if settings.STRIPE_PRO_LINK:
            return settings.STRIPE_PRO_LINK
        price_id = settings.STRIPE_PRO_PRICE_ID
    else:
        raise ValueError(f"Unknown package: {package}")

    if not price_id:
        raise RuntimeError(f"No Stripe link or price ID configured for package '{package}'")

    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.APP_BASE_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.APP_BASE_URL}/payment/cancel",
    )
    log.info("created Stripe Checkout Session %s for package %s", session.id, package)
    return session.url
