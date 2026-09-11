"""Functionality for working with Zenodo."""

from app.config import settings

if settings.ENVIRONMENT != "production":
    BASE_URL = "https://sandbox.zenodo.org/api"
    AUTH_URL = "https://sandbox.zenodo.org/oauth/token"
else:
    BASE_URL = "https://zenodo.org/api"
    AUTH_URL = "https://zenodo.org/oauth/token"
