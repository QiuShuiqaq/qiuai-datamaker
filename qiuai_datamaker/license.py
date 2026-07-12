from __future__ import annotations

import base64
from datetime import date
import hashlib
import json
import os
import platform
import winreg
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .constants import LICENSE_PATH

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAVSwLT0Gc7TQotyYIk/Apb2T5qICYvfnIJfvOmbgBRbY=
-----END PUBLIC KEY-----
"""


@dataclass
class ActivationStatus:
    valid: bool
    fingerprint: str
    message: str = ""
    expires_at: str = ""


def get_device_fingerprint() -> str:
    raw = "|".join(
        [
            _get_machine_guid(),
            os.environ.get("COMPUTERNAME", ""),
            platform.machine(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def build_activation_message(fingerprint: str, expires_at: str) -> bytes:
    return f"{fingerprint.upper()}|{expires_at}".encode("utf-8")


def load_saved_activation(path: Path = LICENSE_PATH) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def save_activation(data: dict, path: Path = LICENSE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def validate_activation_data(
    data: dict,
    expected_fingerprint: str | None = None,
    today: date | None = None,
) -> ActivationStatus:
    fingerprint = str(data.get("fingerprint", "")).strip().upper()
    expires_at = str(data.get("expires_at", "")).strip()
    signature = str(data.get("signature", "")).strip()

    if not fingerprint or not expires_at or not signature:
        return ActivationStatus(False, fingerprint, "Activation file is incomplete.", expires_at)

    if expected_fingerprint and fingerprint != expected_fingerprint.upper():
        return ActivationStatus(
            False,
            fingerprint,
            "Fingerprint does not match this device.",
            expires_at,
        )

    try:
        expiry_date = date.fromisoformat(expires_at)
    except ValueError:
        return ActivationStatus(False, fingerprint, "Expiration date is invalid.", expires_at)

    check_date = today or date.today()
    if check_date > expiry_date:
        return ActivationStatus(False, fingerprint, "Activation has expired.", expires_at)

    try:
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            return ActivationStatus(False, fingerprint, "Invalid public key.", expires_at)
        public_key.verify(
            base64.b64decode(signature),
            build_activation_message(fingerprint, expires_at),
        )
    except (InvalidSignature, ValueError, TypeError):
        return ActivationStatus(False, fingerprint, "Activation signature is invalid.", expires_at)

    return ActivationStatus(True, fingerprint, "Activated.", expires_at)


def get_saved_activation_status(path: Path = LICENSE_PATH) -> ActivationStatus:
    fingerprint = get_device_fingerprint()
    data = load_saved_activation(path)
    if data is None:
        return ActivationStatus(False, fingerprint, "Activation file not found.")
    return validate_activation_data(data, expected_fingerprint=fingerprint)


def _get_machine_guid() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except OSError:
        return "UNKNOWN_MACHINE_GUID"
