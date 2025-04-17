"""Configuration."""

from __future__ import annotations

import os
import platform
from typing import Any, Literal
from typing import get_args as get_type_args

import keyring
import keyring.errors
import yaml
from pydantic import GetCoreSchemaHandler
from pydantic.fields import FieldInfo
from pydantic_core import core_schema
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


def supports_keyring() -> bool:
    """Checks if the system supports the Python keyring library with a usable
    backend.

    Returns:
        bool: True if keyring is supported, False otherwise.
    """
    try:
        # Attempt to get a password (this will trigger backend initialization)
        keyring.get_password("test_service", "test_user")
        return True
    except keyring.errors.NoKeyringError:
        return False
    except keyring.errors.PasswordDeleteError:
        # This can happen if the backend is functional but empty.
        # We consider this as supported.
        return True
    except keyring.errors.ExceptionRaised as e:
        # Check if the underlying exception indicates no backend
        if "No backend found" in str(e):
            return False
        else:
            # Some other error occurred, might still be considered supported
            # depending on your needs. For strict checking, return False.
            return True  # Or False if you want to be strict
    except ImportError:
        # keyring library itself is not installed
        return False
    except Exception:
        # Catch any other unexpected errors during initialization
        return False


KEYRING_SUPPORTED = supports_keyring()


def get_env() -> Literal["local", "staging", "production"]:
    return os.getenv("CALKIT_ENV", "production")


def set_env(name: Literal["local", "staging", "production"]) -> None:
    if name not in ["local", "staging", "production"]:
        raise ValueError(f"{name} is not a valid environment name")
    os.environ["CALKIT_ENV"] = name


def get_env_suffix(sep: str = "-") -> str:
    if get_env() != "production":
        return sep + get_env()
    return ""


def get_app_name() -> str:
    return "calkit" + get_env_suffix()


def get_local_config_path() -> str:
    return os.path.join(".calkit", "config.yaml")


def get_config_yaml_fpath() -> str:
    return os.path.join(
        os.path.expanduser("~"),
        ".calkit",
        f"config{get_env_suffix()}.yaml",
    )


def set_secret(key: str, value: str) -> None:
    """Sets a secret using keyring, handling byte conversion for Linux."""
    service_name = get_app_name()
    if platform.system() == "Linux":
        value_bytes = value.encode("utf-8")
        keyring.set_password(service_name, key, value_bytes)
    else:
        keyring.set_password(service_name, key, value)


def get_secret(key: str) -> str | None:
    """Gets a secret using keyring, handling byte conversion for Linux."""
    service_name = get_app_name()
    password = keyring.get_password(service_name, key)
    if platform.system() == "Linux" and isinstance(password, bytes):
        return password.decode("utf-8")
    return password


def delete_secret(key: str) -> None:
    """Delete a secret using keyring."""
    keyring.delete_password(get_app_name(), key)


class KeyringOptionalSecret(str):
    pass

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_before_validator_function(
            cls._convert, core_schema.str_schema()
        )

    @classmethod
    def _convert(cls, value: Any) -> "KeyringOptionalSecret":
        if not isinstance(value, str):
            raise TypeError("Expected a string")
        return cls(value)


class KeyringSecretsSource(PydanticBaseSettingsSource):
    """A Pydantic settings source that tries to load KeyringOptionalSecret
    values from the system keyring.
    """

    def get_field_value(self, field: FieldInfo, field_name: str):
        value = get_secret(field_name)
        return (value, field_name, False)

    def __call__(self) -> dict[str, Any]:
        if not KEYRING_SUPPORTED:
            return {}
        secrets = {}
        for field_name, field in self.settings_cls.model_fields.items():
            if KeyringOptionalSecret in get_type_args(field.annotation):
                secrets[field_name] = self.get_field_value(field, field_name)[
                    0
                ]
        return secrets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file=get_config_yaml_fpath(),
        extra="ignore",
        env_prefix="CALKIT" + get_env_suffix(sep="_") + "_",
        env_file=".env",
        env_file_encoding="utf-8",
    )
    username: str | None = None
    email: str | None = None
    password: KeyringOptionalSecret | None = None
    token: KeyringOptionalSecret | None = None
    dvc_token: KeyringOptionalSecret | None = None
    dataframe_engine: Literal["pandas", "polars"] = "pandas"
    github_token: KeyringOptionalSecret | None = None
    zenodo_token: KeyringOptionalSecret | None = None
    overleaf_token: KeyringOptionalSecret | None = None

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
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            KeyringSecretsSource(settings_cls),
        )

    def write(self) -> None:
        base_dir = os.path.dirname(self.model_config["yaml_file"])
        os.makedirs(base_dir, exist_ok=True)
        cfg = self.model_dump()
        # Remove anything that should be in the keyring
        if KEYRING_SUPPORTED:
            for key, value in Settings.model_fields.items():
                if (
                    KeyringOptionalSecret in get_type_args(value.annotation)
                ) and key in cfg:
                    secret_val = cfg.pop(key)
                    if secret_val is not None:
                        set_secret(key, secret_val)
                    else:
                        try:
                            delete_secret(key)
                        except keyring.errors.KeyringError:
                            # Ignore errors when deleting secrets
                            pass
        with open(self.model_config["yaml_file"], "w") as f:
            yaml.safe_dump(cfg, f)


def read() -> Settings:
    """Read the config."""
    # Update YAML file path in case environment has changed
    Settings.model_config["yaml_file"] = get_config_yaml_fpath()
    return Settings()
