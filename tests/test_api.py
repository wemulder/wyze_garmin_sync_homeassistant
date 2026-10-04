"""Tests for latest-only Wyze profile normalization."""

from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.wyze_garmin_sync.api import (
    authenticate_wyze,
    latest_measurements,
)


class FakeRecord:
    def __init__(self, profile_id: str, timestamp: int, weight: float) -> None:
        self.id = f"{profile_id}-{timestamp}"
        self.family_member_id = profile_id
        self.user_id = "wyze-account"
        self.measure_ts = timestamp
        self.weight = weight
        self.body_fat = 23.4
        self.body_water = 52.1
        self.bone_mineral = 3.0
        self.muscle = 60.0
        self.bmr = 1600
        self.metabolic_age = 36
        self.body_vfr = 8
        self.bmi = 24.2
        self.body_type = 5


class FakeResponse:
    def __init__(self, data) -> None:
        self.data = {"data": data}


class FakeScaleService:
    members = [
        {"family_member_id": "profile-a", "nickname": "Alex"},
        {"family_member_id": "profile-b", "name": "Sam"},
    ]

    def __init__(self, records: list[FakeRecord]) -> None:
        self.records = records

    def get_device_member(self, *, did: str) -> FakeResponse:
        assert did == "AA:BB:CC"
        return FakeResponse(self.members)

    def get_family_member(self, *, did: str) -> FakeResponse:
        assert did == "AA:BB:CC"
        return FakeResponse([])

    def get_latest_records(self, *, user_id: str) -> FakeResponse:
        return FakeResponse(
            [
                record
                for record in self.records
                if record.family_member_id == user_id
            ]
        )

    def get_records(self, **kwargs):
        raise AssertionError("Latest-only integration must not query record history")


class FakeScales:
    def __init__(self, records: list[FakeRecord]) -> None:
        self.service = FakeScaleService(records)

    def _scale_client(self, model: str) -> FakeScaleService:
        assert model == "WL_SC2"
        return self.service


class FakeDevice:
    type = "WyzeScale"
    mac = "AA:BB:CC"
    product = SimpleNamespace(model="WL_SC2")


class FakeClient:
    _user_id = "wyze-account"

    def __init__(self, records: list[FakeRecord]) -> None:
        self.scales = FakeScales(records)

    def devices_list(self) -> list[FakeDevice]:
        return [FakeDevice()]


class TestLatestMeasurements(unittest.TestCase):
    def test_returns_newest_reading_per_profile(self) -> None:
        client = FakeClient(
            [
                FakeRecord("profile-a", 1_700_000_000_000, 150.0),
                FakeRecord("profile-b", 1_700_000_100_000, 180.0),
                FakeRecord("profile-a", 1_700_000_200_000, 149.5),
            ]
        )

        profiles = latest_measurements(client)

        self.assertEqual(set(profiles), {"profile-a", "profile-b"})
        self.assertEqual(profiles["profile-a"]["weight"], 149.5)
        self.assertEqual(profiles["profile-a"]["name"], "Alex")
        self.assertEqual(profiles["profile-b"]["weight"], 180.0)
        self.assertEqual(profiles["profile-b"]["name"], "Sam")

    def test_skips_records_without_timestamps(self) -> None:
        record = FakeRecord("profile-a", 1_700_000_000_000, 150.0)
        record.measure_ts = None

        profiles = latest_measurements(FakeClient([record]))

        self.assertEqual(set(profiles), {"profile-a", "profile-b"})
        self.assertIsNone(profiles["profile-a"]["measurement_id"])
        self.assertIsNone(profiles["profile-b"]["measurement_id"])


class TestWyzeAuthentication(unittest.TestCase):
    @patch("custom_components.wyze_garmin_sync.api.Client")
    def test_saves_token_fields_from_wyze_response(self, client_class) -> None:
        client = client_class.return_value
        client.login.return_value = SimpleNamespace(
            data={
                "access_token": "access-value",
                "refresh_token": "refresh-value",
                "user_id": "user-value",
                "unneeded_response_field": object(),
            }
        )

        with TemporaryDirectory() as temporary_directory:
            token_file = str(Path(temporary_directory) / "wyze" / "tokens.json")
            authenticate_wyze(
                "user@example.test",
                "password",
                "key-id",
                "api-key",
                token_file,
            )

            with Path(token_file).open(encoding="utf-8") as token_handle:
                saved_tokens = json.load(token_handle)

        self.assertEqual(
            saved_tokens,
            {
                "access_token": "access-value",
                "refresh_token": "refresh-value",
                "user_id": "user-value",
            },
        )
        client.login.assert_called_once_with(
            email="user@example.test",
            password="password",
            key_id="key-id",
            api_key="api-key",
        )
