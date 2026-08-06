"""Functionality for working with subscriptions."""

import logging
from typing import Literal

import app.stripe
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ANNUAL_DISCOUNT_FACTOR = 0.9
PLAN_IDS = {
    level: n for n, level in enumerate(["free", "standard", "professional"])
}
PLAN_NAMES = {i: level for level, i in PLAN_IDS.items()}
PRICES_BY_PLAN_NAME = {
    "free": 0.0,
    "standard": 10.0,
    "professional": 50.0,
}
PRIVATE_PROJECTS_LIMITS_BY_PLAN_NAME = {
    "free": 5,
    "standard": None,
    "professional": None,
}
STORAGE_LIMITS_BY_PLAN_NAME = {
    "free": 10,
    "standard": 100,
    "professional": 500,
}


class SubscriptionPlan(BaseModel):
    name: str
    id: int
    price: float
    private_projects_limit: int | None
    storage_limit: int
    annual_discount_factor: float = ANNUAL_DISCOUNT_FACTOR


def get_plans() -> list[SubscriptionPlan]:
    plans = []
    for plan_name, plan_id in PLAN_IDS.items():
        plans.append(
            SubscriptionPlan(
                name=plan_name,
                id=plan_id,
                price=PRICES_BY_PLAN_NAME[plan_name],
                private_projects_limit=PRIVATE_PROJECTS_LIMITS_BY_PLAN_NAME[
                    plan_name
                ],
                storage_limit=STORAGE_LIMITS_BY_PLAN_NAME[plan_name],
            )
        )
    return plans


def get_monthly_price(
    plan_name: Literal["free", "standard", "professional"],
    period: Literal["monthly", "annual"],
) -> float:
    price = PRICES_BY_PLAN_NAME[plan_name]
    if period == "annual":
        price = price * ANNUAL_DISCOUNT_FACTOR
    return price


def get_storage_limit(
    plan_name: Literal["free", "standard", "professional"],
) -> int:
    """Return the storage limit for a given plan in GB."""
    return STORAGE_LIMITS_BY_PLAN_NAME[plan_name]


def get_private_projects_limit(
    plan_name: Literal["free", "standard", "professional"],
) -> int | None:
    return PRIVATE_PROJECTS_LIMITS_BY_PLAN_NAME[plan_name]


def sync_with_stripe():
    """Ensure all Stripe products and prices are up-to-date."""
    skip_plan_names = ["free"]
    logger.info("Fetching all Stripe products")
    products = app.stripe.get_products()
    products_by_plan_id = {
        product.metadata.plan_id: product for product in products
    }

    def product_exists(plan_id: str | int) -> bool:
        return products_by_plan_id.get(str(plan_id)) is not None

    # First make sure all products exist
    for plan_name, plan_id in PLAN_IDS.items():
        if plan_name in skip_plan_names:
            continue
        if not product_exists(plan_id):
            logger.info(f"Creating product: {plan_name}")
            product = app.stripe.create_product(
                name=f"Calkit {plan_name.title()}",
                plan_id=plan_id,
            )
            products.append(product)
            products_by_plan_id[str(plan_id)] = product
        else:
            logger.info(f"Product exists for {plan_name}")
    # TODO: Make sure we don't have any products we don't want, and deactivate
    # Now let's make sure all of the correct prices exist
    logger.info("Fetching all Stripe prices")
    prices = app.stripe.get_prices()

    def price_exists(
        product_id: str,
        monthly_price_dollars: float,
        period: Literal["monthly", "annual"],
    ) -> float:
        unit_amount = int(100 * monthly_price_dollars)
        if period == "annual":
            unit_amount *= 12
        interval = app.stripe.interval_from_period(period)
        for price in prices:
            if (
                price.product == product_id
                and price.recurring.interval == interval
                and price.unit_amount == unit_amount
            ):
                return True
        return False

    for plan_name, plan_id in PLAN_IDS.items():
        if plan_name in skip_plan_names:
            continue
        product = products_by_plan_id[str(plan_id)]
        for period in ["monthly", "annual"]:
            monthly_price = get_monthly_price(plan_name, period)
            if not price_exists(
                product_id=product.id,
                monthly_price_dollars=monthly_price,
                period=period,
            ):
                logger.info(f"Creating {period} price for {plan_name}")
                app.stripe.create_price(
                    product_id=product.id,
                    monthly_price_dollars=monthly_price,
                    period=period,
                    plan_id=plan_id,
                )
            else:
                logger.info(f"{period.title()} price exists for {plan_name}")
    # TODO: Make sure we don't have any prices we don't want, and deactivate
