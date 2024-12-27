"""Configuration."""

from __future__ import annotations

import os
from typing import Literal

import keyring
import yaml
from keyring.errors import NoKeyringError
from pydantic import computed_field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


def get_env() -> Literal["local", "staging", "production"]:
    return os.getenv(f"{__package__.upper()}_ENV", "production")


def set_env(name: Literal["local", "staging", "production"]) -> None:
    if name not in ["local", "staging", "production"]:
        raise ValueError(f"{name} is not a valid environment name")
    os.environ[f"{__package__.upper()}_ENV"] = name


def get_env_suffix(sep: str = "-") -> str:
    if get_env() != "production":
        return sep + get_env()
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
        env_prefix="CALKIT" + get_env_suffix(sep="_") + "_",
    )
    username: str | None = None
    email: str | None = None
    token: str | None = None
    dvc_token: str | None = None
    dataframe_engine: Literal["pandas", "polars"] = "pandas"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource]:
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
        )

    @computed_field
    @property
    def password(self) -> str | None:
        try:
            return keyring.get_password(get_app_name(), self.username)
        except NoKeyringError:
            return None

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
    return Settings()
