"""Functionality for working with Stripe."""

import uuid
from typing import Literal

import stripe
from app.config import settings
from pydantic import EmailStr

stripe.api_key = settings.STRIPE_SECRET_KEY


def get_products():
    return list(stripe.Product.list())


def get_prices():
    return list(stripe.Price.list())


def get_customers():
    return list(stripe.Customer.list())


def get_customer(email: EmailStr) -> stripe.Customer | None:
    res = stripe.Customer.search(query=f"email: '{email}'")
    res = list(res["data"])
    if not res:
        return
    if len(res) > 1:
        raise ValueError("There are two customers with this email")
    return res[0]


def create_customer(
    email: EmailStr, full_name: str | None, user_id: uuid.UUID
) -> stripe.Customer:
    return stripe.Customer.create(
        email=email, name=full_name, metadata=dict(user_id=user_id)
    )


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
