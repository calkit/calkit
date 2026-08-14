"""Configuration."""

from __future__ import annotations

import os
import platform
import warnings
from typing import Any, Literal
from typing import get_args as get_type_args

import keyring
import keyring.errors
from pydantic import GetCoreSchemaHandler, PrivateAttr, field_validator
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
    """Return the deployment environment serving the active hub.

    Internal vocabulary: a hub is named by its URL everywhere the user
    can see. This maps the built-in hub URLs onto the names the code uses
    to pick API URLs and sandbox credentials.
    """
    if os.getenv("CALKIT_ENV") == "test":
        return "test"
    hub = get_hub()
    if hub in ["test", "local", "staging", "production"]:
        return hub  # type: ignore[return-value]
    return "production"


def set_hub(hub_url: str) -> None:
    """Point subsequent commands in this process at a hub."""
    os.environ["CALKIT_HUB"] = normalize_hub_url(hub_url)


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
    without scheme), e.g., ``https://staging.calkit.io``. Then the
    working directory project's declared ``hub``; then the
    ``default_hub`` config value (also a URL); then production
    (calkit.io).

    A hub is named by its URL, never by a deployment environment name:
    "staging" is the hub operator's word for one of its own instances,
    not something a project or a user's shell should have to know.
    ``CALKIT_ENV`` therefore doesn't select a hub; it's reserved for the
    test suite, whose environment gets its own isolated config.
    """
    hub = os.getenv("CALKIT_HUB")
    source = "CALKIT_HUB"
    if not hub and os.getenv("CALKIT_ENV") == "test":
        # The test environment has its own hub, and its own isolated
        # config and keyring service to go with it. Checked after
        # CALKIT_HUB so a test can still exercise real resolution
        # without giving up that isolation.
        return "test"
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
            f"environment name ('{hub}')"
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
# Every field whose value may live in the system keyring. Kept as a
# constant rather than derived from the model at each access, since it's
# consulted on every attribute read; a test keeps the two in step.
KEYRING_FIELDS = frozenset(
    HUB_SCOPED_FIELDS
    + [
        "github_token",
        "zenodo_token",
        "caltechdata_token",
        "overleaf_token",
    ]
)


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


# Secrets already fetched from the keyring this process, keyed by
# (service, username). Reading one is a keychain authorization prompt on
# macOS, and a command that reads the config twice shouldn't ask twice.
_secret_cache: dict[tuple[str, str], str | None] = {}


def set_secret(key: str, value: str) -> None:
    """Sets a secret using keyring, handling byte conversion for Linux."""
    service_name = get_app_name()
    username = _keyring_username(key)
    if platform.system() == "Linux":
        value_bytes = value.encode("utf-8")
        keyring.set_password(service_name, username, value_bytes)  # type: ignore
    else:
        keyring.set_password(service_name, username, value)
    _secret_cache[(service_name, username)] = value


def get_secret(key: str) -> str | None:
    """Gets a secret using keyring, handling byte conversion for Linux."""
    service_name = get_app_name()
    username = _keyring_username(key)
    cache_key = (service_name, username)
    if cache_key in _secret_cache:
        return _secret_cache[cache_key]
    password = keyring.get_password(service_name, username)
    if platform.system() == "Linux" and isinstance(password, bytes):
        password = password.decode("utf-8")
    _secret_cache[cache_key] = password
    return password


def delete_secret(key: str) -> None:
    """Delete a secret using keyring."""
    service_name = get_app_name()
    username = _keyring_username(key)
    _secret_cache.pop((service_name, username), None)
    keyring.delete_password(service_name, username)


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
    run_history_length: int = 10
    github_token: KeyringOptionalSecret | None = None
    zenodo_token: KeyringOptionalSecret | None = None
    caltechdata_token: KeyringOptionalSecret | None = None
    overleaf_token: KeyringOptionalSecret | None = None

    # Which fields have been resolved from the keyring, so a secret that
    # is genuinely absent isn't looked up again, and an assignment (even
    # of None) isn't overwritten by what's still stored
    _resolved_secrets: set[str] = PrivateAttr(default_factory=set)

    def __getattribute__(self, name: str) -> Any:
        """Fetch a secret from the keyring the first time it's read.

        Fetching one costs a keychain authorization prompt on macOS, and
        reading the config used to fetch all eight up front -- so opening
        a project prompted eight times for secrets no command wanted.
        Most commands need one of them, and plenty need none.
        """
        if name not in KEYRING_FIELDS:
            return super().__getattribute__(name)
        value = super().__getattribute__(name)
        if value is not None:
            return value
        # A private attribute doesn't live in __dict__, so it's reached by
        # ordinary lookup (which falls through to pydantic) rather than by
        # asking object for it directly
        resolved = self._resolved_secrets
        if name in resolved:
            return None
        resolved.add(name)
        secret = get_secret(name) if supports_keyring() else None
        if secret is not None:
            # Straight into __dict__ so model_dump sees it too: write()
            # reads an absent value as "delete this from the keyring"
            super().__getattribute__("__dict__")[name] = secret
        return secret

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Dump the settings, resolving any secret not yet read.

        Serialization reads ``__dict__`` rather than going through
        attribute access, so an unresolved secret would dump as None --
        which ``write`` reads as "delete this credential", and callers
        read as "there isn't one".
        """
        for key in KEYRING_FIELDS:
            getattr(self, key)
        return super().model_dump(*args, **kwargs)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in KEYRING_FIELDS:
            # An explicit value wins over the keyring, including a None
            # meaning "forget this credential"
            self._resolved_secrets.add(name)
        super().__setattr__(name, value)

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
