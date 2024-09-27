"""Configuration."""

from __future__ import annotations

import os
from typing import Literal

import keyring
import yaml
from pydantic import EmailStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_env() -> Literal["local", "staging", "production"]:
    return os.getenv(f"{__package__.upper()}_ENV", "production")


def set_env(name: Literal["local", "staging", "production"]) -> None:
    if name not in ["local", "staging", "production"]:
        raise ValueError(f"{name} is not a valid environment name")
    os.environ[f"{__package__.upper()}_ENV"] = name


def get_env_suffix() -> str:
    if get_env() != "production":
        return "-" + get_env()
    return ""


def get_app_name() -> str:
    return __package__ + get_env_suffix()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file=os.path.join(
            os.path.expanduser("~"),
            "." + __package__,
            f"config{get_env_suffix()}.yaml",
        ),
        extra="ignore",
    )
    username: EmailStr | None = None
    token: str | None = None
    dvc_token: str | None = None
    dataframe_engine: Literal["pandas", "polars"] = "pandas"

    @computed_field
    @property
    def password(self) -> str:
        return keyring.get_password(get_app_name(), self.username)

    @password.setter
    def password(self, value: str) -> None:
        keyring.set_password(get_app_name(), self.username, value)

    def write(self) -> None:
        base_dir = os.path.dirname(self.model_config["yaml_file"])
        os.makedirs(base_dir, exist_ok=True)
        cfg = self.model_dump()
        # Remove password
        _ = cfg.pop("password")
        with open(self.model_config["yaml_file"], "w") as f:
            yaml.safe_dump(cfg, f)


def read() -> Settings:
    """Read the config."""
    fpath = Settings.model_config["yaml_file"]
    if not os.path.isfile(fpath):
        return Settings()
    with open(fpath) as f:
        return Settings.model_validate(yaml.safe_load(f))
