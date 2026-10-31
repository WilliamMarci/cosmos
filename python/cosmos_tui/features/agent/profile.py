"""Private Cosmos Agent profile: settings, credentials, sessions and exports."""

import json
import os
from pathlib import Path
import stat

from cosmos_tui.core.paths import config_home

DEFAULTS = {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com/v1",
}


def profile_root():
    if os.getenv("COSMOS_AGENT") == "1" and os.getenv("COSMOS_AGENT_PROFILE"):
        return Path(os.environ["COSMOS_AGENT_PROFILE"])
    return config_home() / "cosmos/agent"


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Agent profile directories must not be symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid():
        raise PermissionError("Agent profile belongs to another user")
    path.chmod(0o700)
    return path


def secure_profile():
    root = private_directory(profile_root())
    for path in root.rglob("*"):
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(
                    "Agent profile symlinks must remain inside the profile"
                )
            continue
        info = path.stat()
        if info.st_uid != os.getuid():
            raise PermissionError("Agent profile contains files owned by another user")
        path.chmod(
            0o700 if stat.S_ISDIR(info.st_mode) or info.st_mode & 0o111 else 0o600
        )
    return root


def write_private_json(path, value):
    path = Path(path)
    if path.parent.resolve().is_relative_to(profile_root().resolve()):
        private_directory(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path


def load_profile():
    root = profile_root()
    settings = dict(DEFAULTS)
    if (root / "profile.json").exists():
        saved = json.loads((root / "profile.json").read_text())
        if not isinstance(saved, dict) or set(saved) - {
            "provider",
            "model",
            "base_url",
        }:
            raise ValueError("Invalid Agent profile.json fields")
        settings.update(saved)
    validate_settings(settings)
    keys = {}
    if (root / "credentials.json").exists():
        keys = json.loads((root / "credentials.json").read_text())
        if not isinstance(keys, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in keys.items()
        ):
            raise ValueError("credentials.json must map provider IDs to API keys")
    return settings, keys


def validate_settings(settings):
    from urllib.parse import urlsplit
    import re

    if any(not isinstance(v, str) or not v.strip() for v in settings.values()):
        raise ValueError("Provider, model and base_url must be nonempty strings")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", settings["provider"]):
        raise ValueError("Provider ID must use lowercase letters, digits, _ or -")
    if settings["provider"].startswith("opencode"):
        raise ValueError("Select a direct API provider for Cosmos Agent")
    url = urlsplit(settings["base_url"])
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
    ):
        raise ValueError(
            "base_url must be an HTTP(S) endpoint without embedded credentials"
        )


def initialize_profile():
    root = secure_profile()
    for name, value in (("profile.json", DEFAULTS), ("credentials.json", {})):
        if not (root / name).exists():
            write_private_json(root / name, value)
    return root


def provider_config():
    settings, _ = load_profile()
    provider, model = settings["provider"], settings["model"]
    return {
        "model": {"providerID": provider, "model": model},
        "share": "disabled",
        "update": "disable",
        "policies": [
            {"action": "provider.use", "resource": "opencode*", "effect": "deny"}
        ],
        "providers": {
            provider: {
                "name": provider.title() + " API",
                "package": {
                    "deepseek": "@opencode/ai/providers/deepseek",
                    "anthropic": "@opencode/ai/providers/anthropic",
                }.get(provider, "@opencode/ai/providers/openai-compatible"),
                "env": ["COSMOS_AGENT_API_KEY"],
                "settings": {"baseURL": settings["base_url"]},
                "models": {model: {"name": model, "capabilities": {"tools": True}}},
            }
        },
    }


def configure(provider=None, model=None, base_url=None, set_key=False):
    """Update Cosmos-owned settings; API keys are prompted, never CLI arguments."""
    import getpass
    import tempfile

    initialize_profile()
    settings, keys = load_profile()
    for field, value in (
        ("provider", provider),
        ("model", model),
        ("base_url", base_url),
    ):
        if value is not None:
            settings[field] = value
    validate_settings(settings)
    if set_key:
        key = getpass.getpass("API key (hidden): ").strip()
        if not key:
            raise ValueError("API key cannot be empty")
        keys[settings["provider"]] = key
    root = profile_root()
    for filename, value in (("profile.json", settings), ("credentials.json", keys)):
        descriptor, temporary = tempfile.mkstemp(dir=root, prefix=".profile-")
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, root / filename)
    return settings["provider"], settings["model"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Configure the private Cosmos Agent API profile"
    )
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument(
        "--set-key", action="store_true", help="prompt for the API key without echo"
    )
    args = parser.parse_args()
    try:
        provider, model = configure(
            args.provider, args.model, args.base_url, args.set_key
        )
        print(f"Cosmos Agent provider: {provider}; model: {model}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"cosmos profile: {error}\n")
