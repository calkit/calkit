"""Configuration."""

import os

import keyring
import yaml
from pydantic import EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file=os.path.join(
            os.path.expanduser("~"), "." + __package__, "config.yaml"
        ),
        extra="ignore",
    )
    username: EmailStr

    @property
    def password(self) -> str:
        return keyring.get_password(__package__, self.username)

    @password.setter
    def password(self, value: str) -> None:
        keyring.set_password(__package__, self.username, value)

    def write(self) -> None:
        base_dir = os.path.dirname(self.model_config["yaml_file"])
        os.makedirs(base_dir, exist_ok=True)
        with open(self.model_config["yaml_file"], "w") as f:
            yaml.dump(self.model_dump(), f, Dumper=yaml.SafeDumper)


def read() -> Settings:
    """Read the config."""
    fpath = Settings.model_config["yaml_file"]
    with open(fpath) as f:
        return Settings.model_validate(yaml.safe_load(f))
