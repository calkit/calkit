"""Configuration."""

from __future__ import annotations

import os
import platform
import re
import warnings
from typing import Any, Literal
from typing import get_args as get_type_args

import keyring
import keyring.errors
from pydantic import GetCoreSchemaHandler, field_validator
from pydantic.fields import FieldInfo
from pydantic_core import core_schema
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


def supports_keyring() -> bool:
    """Check if the system supports the Python keyring library with a usable
    backend.
    """
    try:
        # Attempt to get a password (this will trigger backend initialization)
        keyring.get_password("test_service", "test_user")
        return True
    except keyring.errors.NoKeyringError:
        return False
    except keyring.errors.PasswordDeleteError:
        # This can happen if the backend is functional but empty
        # We consider this as supported
        return True
    except keyring.errors.InitError:
        # Backend failed to initialize (e.g., user dismissed prompt)
        return False
    except keyring.errors.KeyringLocked:
        warnings.warn("Keyring is locked; will use YAML config file")
        return False
    except keyring.errors.KeyringError as e:
        # Check if the underlying exception indicates no backend
        if "No backend found" in str(e):
            return False
        else:
            # Some other error occurred, which we consider as supported
            return True
    except ImportError:
        # The keyring library itself is not installed, which should not happen
        return False
    except Exception:
        # Catch any other unexpected errors during initialization
        return False


KEYRING_SUPPORTED = supports_keyring()


def get_env() -> Literal["test", "local", "staging", "production"]:
    env = os.getenv("CALKIT_ENV", "production")
    if env not in ["test", "local", "staging", "production"]:
        raise ValueError(f"{env} is not a valid environment name")
    return env  # type: ignore


def set_env(name: Literal["local", "staging", "production"]) -> None:
    if name not in ["local", "staging", "production"]:
        raise ValueError(f"{name} is not a valid environment name")
    os.environ["CALKIT_ENV"] = name


def _get_default_hub() -> str | None:
    """Read ``default_hub`` from the base (unsuffixed) config file.

    Read directly rather than through ``Settings``, since the active hub
    determines which config file ``Settings`` reads, which would recurse.
    """
    import yaml

    fpath = os.path.join(os.path.expanduser("~"), ".calkit", "config.yaml")
    try:
        with open(fpath) as f:
            data = yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError):
        return None
    val = data.get("default_hub")
    if isinstance(val, str) and val:
        return val
    return None


def get_hub() -> str:
    """Return the active hub key: a built-in environment name or an
    arbitrary hub URL.

    ``CALKIT_HUB`` takes precedence and must be a hub URL (with or
    without scheme), e.g., ``https://staging.calkit.io``; environment
    names belong to ``CALKIT_ENV``. Then an explicitly set environment;
    then the ``default_hub`` config value (also a URL); then production
    (calkit.io).
    """
    hub = os.getenv("CALKIT_HUB")
    source = "CALKIT_HUB"
    if not hub and os.getenv("CALKIT_ENV"):
        return get_env()
    if not hub:
        hub = _get_default_hub()
        source = "default_hub"
    if not hub:
        return "production"
    if hub in ["test", "local", "staging", "production"]:
        raise ValueError(
            f"{source} must be a hub URL like https://calkit.io, not an "
            f"environment name ('{hub}'); use CALKIT_ENV for environment "
            "names"
        )
    # Map built-in hub URLs to their environment names so they share
    # config with the env-based spellings
    from calkit.hub import env_for_hub

    env = env_for_hub(hub) or env_for_hub("https://" + hub)
    if env is not None:
        return env
    return hub.rstrip("/")


def slugify_hub(hub: str, sep: str = "-") -> str:
    """Make a hub key safe for filenames, keyring service names, and
    environment variable prefixes.

    For example, ``http://localhost:5173`` cannot appear in a Windows
    filename, and calkit-python's CI runs on Windows.
    """
    slug = hub.lower().removeprefix("https://").removeprefix("http://")
    slug = re.sub(r"[^a-z0-9.]+", sep, slug).strip(sep)
    # Environment variable names can't contain dots either
    if sep == "_":
        slug = slug.replace(".", "_")
    return slug


def get_env_suffix(sep: str = "-") -> str:
    hub = get_hub()
    if hub == "production":
        return ""
    if hub in ["test", "local", "staging"]:
        return sep + hub
    return sep + slugify_hub(hub, sep=sep)


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
        keyring.set_password(service_name, key, value_bytes)  # type: ignore
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
    email: str | None = None
    # The hub commands target when no hub is otherwise specified; only
    # consulted from the base (unsuffixed) config file
    default_hub: str | None = None
    token: KeyringOptionalSecret | None = None
    access_token: KeyringOptionalSecret | None = None
    refresh_token: KeyringOptionalSecret | None = None
    dvc_token: KeyringOptionalSecret | None = None
    dataframe_engine: Literal["pandas", "polars"] = "pandas"
    github_token: KeyringOptionalSecret | None = None
    zenodo_token: KeyringOptionalSecret | None = None
    caltechdata_token: KeyringOptionalSecret | None = None
    overleaf_token: KeyringOptionalSecret | None = None

    @field_validator("default_hub")
    @classmethod
    def _validate_default_hub(cls, v: str | None) -> str | None:
        # Environment names are deployment-internal vocabulary; the hub
        # is identified by its URL
        if v in ["test", "local", "staging", "production"]:
            raise ValueError(
                "default_hub must be a hub URL like https://calkit.io, "
                "not an environment name"
            )
        return v

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
        )  # type: ignore

    def write(self) -> None:
        import yaml

        base_dir = os.path.dirname(self.model_config["yaml_file"])  # type: ignore
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
        with open(self.model_config["yaml_file"], "w") as f:  # type: ignore
            yaml.safe_dump(cfg, f)
        # Ensure permissions are user read/write only
        os.chmod(self.model_config["yaml_file"], 0o600)  # type: ignore


def read() -> Settings:
    """Read the config."""
    # Update YAML file path and env prefix in case the active hub or
    # environment has changed since import, e.g., via a --hub option
    Settings.model_config["yaml_file"] = get_config_yaml_fpath()
    Settings.model_config["env_prefix"] = (
        "CALKIT" + get_env_suffix(sep="_") + "_"
    )
    return Settings()
