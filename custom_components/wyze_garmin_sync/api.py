"""Synchronous Wyze and Garmin API operations."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from garminconnect import Garmin
from wyze_sdk import Client
from wyze_sdk.models.devices import ScaleRecord

_LOGGER = logging.getLogger(__name__)


class GarminMFARequired(Exception):
    """Raised when Garmin requests MFA outside of an interactive setup flow."""


def save_wyze_tokens(token_file: str, tokens: dict[str, Any]) -> None:
    """Persist Wyze tokens with owner-only file permissions."""
    path = Path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as token_handle:
        json.dump(tokens, token_handle)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)


def _load_wyze_tokens(token_file: str) -> dict[str, Any] | None:
    try:
        with Path(token_file).open(encoding="utf-8") as token_handle:
            tokens = json.load(token_handle)
    except (OSError, json.JSONDecodeError):
        return None
    return tokens if tokens.get("access_token") else None


def authenticate_wyze(
    email: str,
    password: str,
    key_id: str,
    api_key: str,
    token_file: str,
) -> None:
    """Authenticate a Wyze account and save its refreshable token."""
    client = Client()
    response = client.login(
        email=email,
        password=password,
        key_id=key_id,
        api_key=api_key,
    )
    save_wyze_tokens(token_file, response)


def _refresh_wyze_token(
    client: Client, tokens: dict[str, Any], token_file: str
) -> None:
    response = client.refresh_token()
    refreshed = response["data"]
    tokens["access_token"] = refreshed["access_token"]
    tokens["refresh_token"] = refreshed["refresh_token"]
    save_wyze_tokens(token_file, tokens)


def get_wyze_client(
    email: str,
    password: str,
    key_id: str,
    api_key: str,
    token_file: str,
) -> tuple[Client, list[Any]]:
    """Create a Wyze client and retrieve its device list once."""
    tokens = _load_wyze_tokens(token_file)
    if tokens:
        client = Client(
            token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
        )
        if tokens.get("user_id"):
            client._user_id = tokens["user_id"]
        try:
            return client, client.devices_list()
        except Exception:
            if not tokens.get("refresh_token"):
                raise
            _refresh_wyze_token(client, tokens, token_file)
            return client, client.devices_list()

    authenticate_wyze(email, password, key_id, api_key, token_file)
    tokens = _load_wyze_tokens(token_file)
    if not tokens:
        raise RuntimeError("Wyze authentication completed without a saved token")
    client = Client(
        token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
    )
    if tokens.get("user_id"):
        client._user_id = tokens["user_id"]
    return client, client.devices_list()


def profile_id_for_record(record: Any, fallback_id: str) -> str:
    """Return the Wyze household profile identifier for a scale record."""
    profile_id = getattr(record, "family_member_id", None)
    if profile_id in (None, "") and fallback_id not in ("", "primary"):
        profile_id = fallback_id
    if profile_id in (None, ""):
        profile_id = getattr(record, "user_id", None)
    return str(profile_id) if profile_id not in (None, "") else fallback_id


def _member_items(value: Any) -> list[dict[str, Any]]:
    """Flatten Wyze membership payloads into member dictionaries."""
    if isinstance(value, list):
        return [
            item
            for member in value
            for item in _member_items(member)
        ]
    if not isinstance(value, dict):
        return []

    member_keys = {
        "family_member_id",
        "familyMemberId",
        "user_id",
        "member_id",
        "memberId",
        "id",
    }
    if member_keys.intersection(value):
        return [value]

    members = []
    for key, nested in value.items():
        if isinstance(nested, dict):
            members.extend(
                _member_items({"id": nested.get("id", key), **nested})
            )
        elif isinstance(nested, list):
            members.extend(_member_items(nested))
    return members


def profile_names_for_scale(*membership_data: Any) -> dict[str, str]:
    """Build profile display names from Wyze scale membership metadata."""
    names: dict[str, str] = {}
    for member in (
        item
        for data in membership_data
        for item in _member_items(data)
    ):
        profile_id = (
            member.get("family_member_id")
            or member.get("familyMemberId")
            or member.get("user_id")
            or member.get("member_id")
            or member.get("memberId")
            or member.get("id")
        )
        name = (
            member.get("nickname")
            or member.get("name")
            or member.get("username")
            or member.get("user_name")
            or member.get("member_name")
            or member.get("family_member_name")
        )
        if profile_id is not None:
            names[str(profile_id)] = str(name or f"Wyze profile {profile_id}")
    return names


def _response_payload(response: Any) -> Any:
    """Return the payload under a Wyze SDK response's data key."""
    response_data = getattr(response, "data", None)
    if isinstance(response_data, dict):
        return response_data.get("data")
    return None


def _latest_record_items(payload: Any) -> list[Any]:
    """Normalize the latest-record endpoint's supported response shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("records", "record_list", "latest_records"):
            if isinstance(payload.get(key), list):
                return payload[key]
        if "measure_ts" in payload:
            return [payload]
    return []


def latest_measurements(
    client: Client, devices: list[Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Retrieve only each profile's latest record using Wyze's latest endpoint."""
    profiles: dict[str, dict[str, Any]] = {}
    fallback_id = str(getattr(client, "_user_id", None) or "primary")
    for device in devices if devices is not None else client.devices_list():
        if getattr(device, "type", None) != "WyzeScale":
            continue

        model = getattr(getattr(device, "product", None), "model", None)
        if not model:
            raise RuntimeError(f"Wyze scale {device.mac} has no product model")
        service = client.scales._scale_client(model)
        device_members = _response_payload(
            service.get_device_member(did=device.mac)
        )
        family_members = _response_payload(
            service.get_family_member(did=device.mac)
        )
        profile_names = profile_names_for_scale(device_members, family_members)
        profile_ids = list(profile_names) or [fallback_id]

        for profile_id, name in profile_names.items():
            profiles.setdefault(
                profile_id,
                {
                    "profile_id": profile_id,
                    "name": name,
                    "measurement_id": None,
                    "timestamp": None,
                    "weight": None,
                    "body_fat": None,
                    "body_water": None,
                    "bone_mineral": None,
                    "muscle": None,
                    "bmr": None,
                    "metabolic_age": None,
                    "body_vfr": None,
                    "bmi": None,
                    "body_type": None,
                    "_record": None,
                },
            )

        for profile_id in profile_ids:
            response = service.get_latest_records(user_id=profile_id)
            for record_data in _latest_record_items(_response_payload(response)):
                record = (
                    record_data
                    if hasattr(record_data, "measure_ts")
                    else ScaleRecord(**record_data)
                )
                timestamp_ms = getattr(record, "measure_ts", None)
                if timestamp_ms is None:
                    continue
                record_profile_id = profile_id_for_record(record, profile_id)
                try:
                    recorded_at = datetime.fromtimestamp(
                        float(timestamp_ms) / 1000,
                        tz=timezone.utc,
                    )
                except (TypeError, ValueError, OverflowError, OSError):
                    _LOGGER.warning(
                        "Skipping a Wyze reading with an invalid timestamp"
                    )
                    continue

                current = profiles.get(record_profile_id)
                if (
                    current
                    and current["timestamp"]
                    and current["timestamp"] >= recorded_at.isoformat()
                ):
                    continue

                measurement_id = getattr(record, "id", None)
                if not measurement_id or str(measurement_id) == "None":
                    measurement_id = hashlib.sha256(
                        (
                            f"{record_profile_id}:{timestamp_ms}:"
                            f"{getattr(record, 'weight', None)}"
                        ).encode()
                    ).hexdigest()

                profiles[record_profile_id] = {
                    "profile_id": record_profile_id,
                    "name": profile_names.get(
                        record_profile_id,
                        f"Wyze profile {record_profile_id}",
                    ),
                    "measurement_id": str(measurement_id),
                    "timestamp": recorded_at.isoformat(),
                    "weight": _float_or_none(getattr(record, "weight", None)),
                    "body_fat": _float_or_none(
                        getattr(record, "body_fat", None)
                    ),
                    "body_water": _float_or_none(
                        getattr(record, "body_water", None)
                    ),
                    "bone_mineral": _float_or_none(
                        getattr(record, "bone_mineral", None)
                    ),
                    "muscle": _float_or_none(getattr(record, "muscle", None)),
                    "bmr": _float_or_none(getattr(record, "bmr", None)),
                    "metabolic_age": _float_or_none(
                        getattr(record, "metabolic_age", None)
                    ),
                    "body_vfr": _float_or_none(
                        getattr(record, "body_vfr", None)
                    ),
                    "bmi": _float_or_none(getattr(record, "bmi", None)),
                    "body_type": _float_or_none(
                        getattr(record, "body_type", None)
                    ),
                    "_record": record,
                }
    return profiles


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def get_garmin_client(account: dict[str, str], token_dir: str) -> Garmin:
    """Load cached Garmin authentication, or authenticate without prompting."""
    token_path = Path(token_dir)
    token_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (token_path / "garmin_tokens.json").is_file():
        garmin = Garmin()
        garmin.login(str(token_path))
        return garmin

    def reject_interactive_mfa() -> str:
        raise GarminMFARequired(
            "Garmin requires MFA; reconfigure this account with a current MFA code"
        )

    garmin = Garmin(
        email=account["email"],
        password=account["password"],
        prompt_mfa=reject_interactive_mfa,
    )
    garmin.client.skip_strategies.update({"mobile+cffi", "mobile+requests"})
    garmin.login(str(token_path))
    return garmin


def authenticate_garmin(
    email: str, password: str, mfa_code: str, token_dir: str
) -> None:
    """Authenticate Garmin during setup, where an MFA code can be supplied."""
    token_path = Path(token_dir)
    token_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    garmin = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: mfa_code,
    )
    garmin.client.skip_strategies.update({"mobile+cffi", "mobile+requests"})
    garmin.login(str(token_path))


def upload_record_to_garmin(record: Any, garmin: Garmin) -> None:
    """Upload one latest Wyze measurement to Garmin Connect."""
    timestamp_ms = float(record.measure_ts)
    recorded_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    weight_kg = float(record.weight) * 0.45359237
    basal_met = getattr(record, "bmr", None)
    garmin.add_body_composition(
        timestamp=recorded_at.isoformat(),
        weight=weight_kg,
        percent_fat=_float_or_none(getattr(record, "body_fat", None)),
        percent_hydration=_float_or_none(getattr(record, "body_water", None)),
        bone_mass=_float_or_none(getattr(record, "bone_mineral", None)),
        muscle_mass=_float_or_none(getattr(record, "muscle", None)),
        basal_met=_float_or_none(basal_met),
        active_met=int(float(basal_met) * 1.25) if basal_met is not None else None,
        physique_rating=float(getattr(record, "body_type", None) or 5),
        metabolic_age=_float_or_none(getattr(record, "metabolic_age", None)),
        visceral_fat_rating=_float_or_none(getattr(record, "body_vfr", None)),
        bmi=_float_or_none(getattr(record, "bmi", None)),
    )


def profile_token_dir(base_dir: str, profile_id: str) -> str:
    """Return a stable, filesystem-safe token directory per Wyze profile."""
    safe_id = hashlib.sha256(profile_id.encode()).hexdigest()[:24]
    return str(Path(base_dir) / "garmin" / safe_id)


def wyze_token_file(base_dir: str) -> str:
    """Return the persistent Wyze token file path."""
    return str(Path(base_dir) / "wyze_tokens.json")
