"""Configuration."""

from __future__ import annotations

import os
import platform
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
)


def _probe_keyring() -> bool:
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


_keyring_supported: bool | None = None


def supports_keyring() -> bool:
    """Whether a usable keyring backend exists, probed once and cached.

    Deliberately lazy: the probe reads from the system keyring, which on
    macOS can pop an unlock prompt. Most commands never touch a secret --
    editors run things like ``calkit status`` on every file save -- so
    probing at import made those prompt for nothing.
    """
    global _keyring_supported
    if _keyring_supported is None:
        _keyring_supported = _probe_keyring()
    return _keyring_supported


def __getattr__(name: str) -> Any:
    # Keep the old module-level constant working, lazily
    if name == "KEYRING_SUPPORTED":
        return supports_keyring()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_env() -> Literal["test", "local", "staging", "production"]:
    env = os.getenv("CALKIT_ENV", "production")
    if env not in ["test", "local", "staging", "production"]:
        raise ValueError(f"{env} is not a valid environment name")
    return env  # type: ignore


def set_env(name: Literal["local", "staging", "production"]) -> None:
    if name not in ["local", "staging", "production"]:
        raise ValueError(f"{name} is not a valid environment name")
    os.environ["CALKIT_ENV"] = name


def normalize_hub_url(hub: str) -> str:
    """Normalize a hub URL, adding a scheme if missing: https, unless the
    host is local (localhost or a loopback address, which won't have
    certificates).
    """
    if not hub.startswith(("http://", "https://")):
        host = hub.split("/")[0]
        if host.startswith(("localhost", "127.")):
            hub = "http://" + hub
        else:
            hub = "https://" + hub
    return hub.rstrip("/")


# The project hub lookup result, keyed by (path, mtime, size) so edits to
# calkit.yaml invalidate it; get_hub is called several times per command
# and shouldn't re-parse the file each time
_project_hub_cache: dict[tuple[str, int, int], str | None] = {}


def _get_project_hub() -> str | None:
    """Read the working directory project's declared ``hub``."""
    import yaml

    fpath = os.path.join(os.getcwd(), "calkit.yaml")
    try:
        st = os.stat(fpath)
    except OSError:
        return None
    key = (fpath, st.st_mtime_ns, st.st_size)
    if key in _project_hub_cache:
        return _project_hub_cache[key]
    try:
        with open(fpath) as f:
            data = yaml.safe_load(f) or {}
        val = data.get("hub")
    except Exception:
        val = None
    hub = val if isinstance(val, str) and val else None
    _project_hub_cache[key] = hub
    return hub


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
    then the working directory project's declared ``hub``; then the
    ``default_hub`` config value (also a URL); then production
    (calkit.io).
    """
    hub = os.getenv("CALKIT_HUB")
    source = "CALKIT_HUB"
    if not hub and os.getenv("CALKIT_ENV"):
        return get_env()
    if not hub:
        hub = _get_project_hub()
        source = "the project's hub"
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

    hub = normalize_hub_url(hub)
    env = env_for_hub(hub)
    if env is not None:
        return env
    return hub


def get_env_suffix(sep: str = "-") -> str:
    """Suffix for the config file name, keyring service, and env var
    prefix.

    All real hubs share a single config file and keyring service, with
    hub credentials scoped inside them (see ``_hub_storage_key``); only
    the test environment gets its own isolated config, so tests never
    touch real credentials.
    """
    if os.getenv("CALKIT_ENV") == "test":
        return sep + "test"
    return ""


# The fields that are per-hub credentials; everything else in the config
# is shared across hubs
HUB_SCOPED_FIELDS = ["token", "access_token", "refresh_token", "dvc_token"]


def _hub_storage_key() -> str | None:
    """Return where the active hub's credentials live: ``None`` means the
    flat top level of the config (the default hub -- calkit.io, or the
    test environment's own instance), otherwise the hub URL keying a
    ``hubs`` sub-map and namespaced keyring entries.
    """
    hub = get_hub()
    if hub in ["production", "test"]:
        return None
    from calkit.hub import HUB_URLS

    return HUB_URLS.get(hub, hub)


def _keyring_username(key: str) -> str:
    """Return the keyring username for a config key, namespaced by hub
    for hub-scoped credentials of non-default hubs."""
    hub = _hub_storage_key()
    if hub is None or key not in HUB_SCOPED_FIELDS:
        return key
    return f"{key}@{hub}"


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
    username = _keyring_username(key)
    if platform.system() == "Linux":
        value_bytes = value.encode("utf-8")
        keyring.set_password(service_name, username, value_bytes)  # type: ignore
    else:
        keyring.set_password(service_name, username, value)


def get_secret(key: str) -> str | None:
    """Gets a secret using keyring, handling byte conversion for Linux."""
    service_name = get_app_name()
    password = keyring.get_password(service_name, _keyring_username(key))
    if platform.system() == "Linux" and isinstance(password, bytes):
        return password.decode("utf-8")
    return password


def delete_secret(key: str) -> None:
    """Delete a secret using keyring."""
    keyring.delete_password(get_app_name(), _keyring_username(key))


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


class CalkitYamlSource(PydanticBaseSettingsSource):
    """Loads settings from the config YAML file, resolving hub-scoped
    credential fields from the active hub's ``hubs`` sub-map when the
    active hub isn't the config's default.
    """

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        # Loading happens wholesale in __call__
        return (None, field_name, False)

    def __call__(self) -> dict[str, Any]:
        import yaml

        fpath = get_config_yaml_fpath()
        try:
            with open(fpath) as f:  # type: ignore[arg-type]
                data = yaml.safe_load(f) or {}
        except (FileNotFoundError, yaml.YAMLError):
            return {}
        if not isinstance(data, dict):
            return {}
        hubs = data.pop("hubs", None) or {}
        fields = self.settings_cls.model_fields
        out = {k: v for k, v in data.items() if k in fields}
        hub = _hub_storage_key()
        if hub is not None:
            # The flat credential entries belong to the default hub;
            # the active hub's live in its sub-map (possibly absent)
            for key in HUB_SCOPED_FIELDS:
                out.pop(key, None)
            sub = hubs.get(hub)
            if isinstance(sub, dict):
                out |= {k: v for k, v in sub.items() if k in HUB_SCOPED_FIELDS}
        return out


class KeyringSecretsSource(PydanticBaseSettingsSource):
    """A Pydantic settings source that tries to load KeyringOptionalSecret
    values from the system keyring.
    """

    def get_field_value(self, field: FieldInfo, field_name: str):
        value = get_secret(field_name)
        return (value, field_name, False)

    def __call__(self) -> dict[str, Any]:
        if not supports_keyring():
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
            CalkitYamlSource(settings_cls),
            KeyringSecretsSource(settings_cls),
        )  # type: ignore

    def write(self) -> None:
        import yaml

        fpath = get_config_yaml_fpath()
        base_dir = os.path.dirname(fpath)
        os.makedirs(base_dir, exist_ok=True)
        cfg = self.model_dump()
        # Remove anything that should be in the keyring; hub-scoped
        # credentials get hub-namespaced usernames via set/delete_secret
        if supports_keyring():
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
        # Preserve other hubs' credential sub-maps from the existing file
        try:
            with open(fpath) as f:
                existing = yaml.safe_load(f) or {}
        except (FileNotFoundError, yaml.YAMLError):
            existing = {}
        hubs = existing.get("hubs") if isinstance(existing, dict) else None
        hubs = hubs if isinstance(hubs, dict) else {}
        hub = _hub_storage_key()
        if hub is not None:
            # This model's credential values belong to the active hub's
            # sub-map, not the flat top level (which is the default
            # hub's); drop absent values rather than writing nulls
            sub = {
                k: cfg.pop(k)
                for k in HUB_SCOPED_FIELDS
                if k in cfg and cfg[k] is not None
            }
            for k in HUB_SCOPED_FIELDS:
                cfg.pop(k, None)
            if sub:
                hubs[hub] = sub
            else:
                hubs.pop(hub, None)
            # The flat credentials in the file (the default hub's) were
            # not loaded into this model, so restore them from the file
            for k in HUB_SCOPED_FIELDS:
                if isinstance(existing, dict) and k in existing:
                    cfg[k] = existing[k]
        if hubs:
            cfg["hubs"] = hubs
        with open(fpath, "w") as f:
            yaml.safe_dump(cfg, f)
        # Ensure permissions are user read/write only
        os.chmod(fpath, 0o600)


def read() -> Settings:
    """Read the config."""
    # Update the env prefix in case the environment has changed since
    # import; the YAML source resolves its file path itself
    Settings.model_config["env_prefix"] = (
        "CALKIT" + get_env_suffix(sep="_") + "_"
    )
    return Settings()
