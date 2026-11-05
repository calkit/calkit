"""Functionality for working with Stripe."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

import stripe
from pydantic import EmailStr

from app.config import settings

if TYPE_CHECKING:
    from app.models import User

stripe.api_key = settings.STRIPE_SECRET_KEY


def get_products():
    return list(stripe.Product.list())


def get_prices():
    return list(stripe.Price.list())


def get_customers():
    return list(stripe.Customer.list())


def find_customers(email: EmailStr) -> list[stripe.Customer]:
    """Return every customer with this email, oldest first.

    Search lags behind writes by up to a minute, so it can miss a customer
    just created, and there may be several from before IDs were stored.
    """
    res = stripe.Customer.search(query=f"email: '{email}'")
    customers = cast(list[stripe.Customer], res.data)
    return sorted(customers, key=lambda c: c.created)


def _get_stored_customer(user: User) -> stripe.Customer | None:
    if user.stripe_customer_id is None:
        return None
    try:
        customer = stripe.Customer.retrieve(user.stripe_customer_id)
    except stripe.InvalidRequestError as e:
        # E.g., an ID from another Stripe account or mode
        if e.code == "resource_missing":
            return None
        raise
    return None if customer.get("deleted") else customer


def get_user_customers(user: User) -> list[stripe.Customer]:
    """Return every customer a user's subscriptions may be under: the one
    stored on the user, plus any with their email.
    """
    customers = find_customers(user.email)
    stored = _get_stored_customer(user)
    if stored is not None and stored.id not in [c.id for c in customers]:
        customers.insert(0, stored)
    return customers


def get_or_create_user_customer(user: User) -> stripe.Customer:
    """Return the customer to bill a user as, creating one if needed.

    Its ID is stored on the user, for the caller to commit, since search
    can't be relied on to find a customer just created. Creation is
    idempotent per user, so a retry within a day can't make a second.
    """
    customer = _get_stored_customer(user)
    if customer is None:
        customers = find_customers(user.email)
        if customers:
            customer = customers[0]
        else:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.full_name or "",
                metadata=dict(user_id=str(user.id)),
                idempotency_key=f"customer-{user.id}",
            )
    user.stripe_customer_id = customer.id
    return customer


def interval_from_period(period: Literal["monthly", "annual"]) -> str:
    return {"monthly": "month", "annual": "year"}[period]


def create_product(name: str, plan_id: int) -> stripe.Product:
    """Create a new product.

    Note that ``name`` is meant to be displayable to the customer.
    """
    return stripe.Product.create(name=name, metadata=dict(plan_id=plan_id))


def create_price(
    product_id: str,
    monthly_price_dollars: float,
    period: Literal["monthly", "annual"],
    plan_id: int,
) -> stripe.Price:
    unit_amount = int(monthly_price_dollars * 100)
    if period == "annual":
        unit_amount *= 12
    return stripe.Price.create(
        product=product_id,
        currency="usd",
        recurring=dict(interval=interval_from_period(period)),
        unit_amount=unit_amount,
        metadata=dict(plan_id=plan_id, period=period),
    )


def get_price(
    plan_id: int, period: Literal["monthly", "annual"]
) -> stripe.Price | None:
    res = stripe.Price.search(
        query=(
            f"metadata['plan_id']:'{plan_id}' "
            f"AND metadata['period']:'{period}'"
        )
    )
    res = list(res["data"])
    if not res:
        return
    if len(res) > 1:
        raise ValueError("There are two prices with this information")
    return res[0]  # type: ignore


def create_subscription(
    customer_id,
    price_id,
    org_id: int | None = None,
    description: str | None = None,
) -> stripe.Subscription:
    return stripe.Subscription.create(
        customer=customer_id,
        items=[
            {
                "price": price_id,
            }
        ],
        payment_behavior="default_incomplete",
        expand=["latest_invoice.payment_intent"],
        metadata=dict(org_id=org_id),  # type: ignore
        description=description,  # type: ignore
    )


def cancel_subscription(subscription_id):
    return stripe.Subscription.delete(subscription_id)


def update_subscription(subscription_id, **kwargs):
    return stripe.Subscription.modify(subscription_id, **kwargs)


def get_customer_subscriptions(
    customer_id, status: Literal["all", "active", "canceled", "ended"] = "all"
) -> list[stripe.Subscription]:
    return list(
        stripe.Subscription.list(
            customer=customer_id,
            status=status,
            expand=["data.default_payment_method"],
        )["data"]
    )  # type: ignore
