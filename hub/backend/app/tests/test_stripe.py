import uuid
from types import SimpleNamespace
from unittest.mock import patch

import stripe

from app import stripe as app_stripe
from app.models import User


def _customer(id: str, created: int = 0, deleted: bool = False):
    c = SimpleNamespace(id=id, created=created)
    c.get = lambda key: deleted if key == "deleted" else None  # type: ignore[attr-defined]
    return c


def test_user_customers() -> None:
    user = User(
        id=uuid.uuid4(),
        email="someone@example.com",
        hashed_password="x",
        full_name="Some One",
    )
    customers: dict[str, SimpleNamespace] = {}
    searchable: list[SimpleNamespace] = []
    created = []

    def retrieve(id: str):
        if id not in customers:
            raise stripe.InvalidRequestError(
                "No such customer", "id", code="resource_missing"
            )
        return customers[id]

    def create(**kwargs):
        # Creating with the same idempotency key returns the same customer
        key = kwargs["idempotency_key"]
        if key not in customers:
            customers[key] = _customer(f"cus_{len(customers)}", created=1)
            created.append(kwargs)
        return customers[key]

    with (
        patch.object(stripe.Customer, "retrieve", side_effect=retrieve),
        patch.object(stripe.Customer, "create", side_effect=create),
        patch.object(
            app_stripe,
            "find_customers",
            side_effect=lambda email: list(searchable),
        ),
    ):
        # With no customer yet, one is created and its ID stored, even
        # though search can't see it yet
        cust = app_stripe.get_or_create_user_customer(user)
        assert user.stripe_customer_id == cust.id
        assert created[0]["idempotency_key"] == f"customer-{user.id}"
        assert created[0]["metadata"] == {"user_id": str(user.id)}
        customers[cust.id] = cust
        assert app_stripe.get_or_create_user_customer(user) is cust
        assert len(created) == 1
        assert app_stripe.get_user_customers(user) == [cust]
        # Once searchable, it isn't listed twice, and others with the
        # email are included
        other = _customer("cus_other", created=0)
        searchable[:] = [other, cust]
        assert app_stripe.get_user_customers(user) == [other, cust]
        # A stored ID Stripe doesn't know falls back to the oldest by email
        user.stripe_customer_id = "cus_gone"
        assert app_stripe.get_user_customers(user) == [other, cust]
        assert app_stripe.get_or_create_user_customer(user) is other
        assert user.stripe_customer_id == "cus_other"
        # As does one that's been deleted
        customers["cus_deleted"] = _customer("cus_deleted", deleted=True)
        user.stripe_customer_id = "cus_deleted"
        assert app_stripe.get_or_create_user_customer(user) is other
