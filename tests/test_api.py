"""Tests for latest-only Wyze profile normalization."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import HomeAssistantError

from custom_components.wyze_garmin_sync import async_setup_entry
from custom_components.wyze_garmin_sync.api import (
    authenticate_wyze,
    latest_measurements,
)
from custom_components.wyze_garmin_sync.button import WyzeGarminSyncButton
from custom_components.wyze_garmin_sync.const import (
    CONF_POLL_INTERVAL_MINUTES,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DISABLE_POLLING,
)
from custom_components.wyze_garmin_sync.coordinator import (
    _async_clear_sync_failure,
    _async_notify_sync_failure,
)
from custom_components.wyze_garmin_sync.sensor import WyzeProfileWeighInSensor


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


class TestWeighInTimestampSensor(unittest.TestCase):
    def test_sensor_state_is_the_measurement_time(self) -> None:
        coordinator = SimpleNamespace(
            data={
                "profiles": {
                    "profile-a": {
                        "timestamp": "2026-10-04T18:42:15+00:00",
                        "measurement_id": "reading-a",
                        "name": "Alex",
                    }
                }
            },
            entry=SimpleNamespace(entry_id="entry-a"),
            last_update_success=True,
        )

        sensor = WyzeProfileWeighInSensor(
            coordinator,
            "entry-a",
            "profile-a",
        )

        self.assertEqual(
            sensor.native_value.isoformat(),
            "2026-10-04T18:42:15+00:00",
        )


class TestManualSyncButton(unittest.IsolatedAsyncioTestCase):
    async def test_logs_and_surfaces_sync_failure(self) -> None:
        coordinator = SimpleNamespace(
            async_sync_now=AsyncMock(side_effect=RuntimeError("diagnostic detail"))
        )
        button = WyzeGarminSyncButton(coordinator, "entry-a")

        with self.assertLogs(
            "custom_components.wyze_garmin_sync.button",
            level="ERROR",
        ) as captured:
            with self.assertRaises(HomeAssistantError) as raised:
                await button.async_press()

        self.assertIn("diagnostic detail", str(raised.exception))
        self.assertIn("Manual Wyze/Garmin synchronization failed", captured.output[0])


class TestSyncFailureNotification(unittest.TestCase):
    @patch(
        "custom_components.wyze_garmin_sync.coordinator.persistent_notification.async_create"
    )
    def test_creates_deduplicated_notification(
        self,
        async_create,
    ) -> None:
        hass = object()

        _async_notify_sync_failure(hass, "entry-a_failure", "Wyze sync failed")

        async_create.assert_called_once_with(
            hass,
            "Wyze sync failed",
            title="Wyze Garmin Sync failed",
            notification_id="entry-a_failure",
        )

    @patch(
        "custom_components.wyze_garmin_sync.coordinator.persistent_notification.async_dismiss"
    )
    def test_dismisses_notification_after_recovery(self, async_dismiss) -> None:
        hass = object()

        _async_clear_sync_failure(hass, "entry-a_failure")

        async_dismiss.assert_called_once_with(hass, "entry-a_failure")


class TestPollInterval(unittest.IsolatedAsyncioTestCase):
    async def test_setup_uses_default_poll_interval(self) -> None:
        await self._assert_setup_interval(
            {},
            DEFAULT_POLL_INTERVAL_MINUTES,
        )

    async def test_setup_uses_configured_poll_interval(self) -> None:
        await self._assert_setup_interval(
            {CONF_POLL_INTERVAL_MINUTES: 1440},
            1440,
        )

    async def test_setup_disables_recurring_polling_when_set_to_zero(self) -> None:
        await self._assert_setup_interval(
            {CONF_POLL_INTERVAL_MINUTES: DISABLE_POLLING},
            None,
        )

    async def _assert_setup_interval(
        self,
        options: dict[str, int],
        expected_minutes: int | None,
    ) -> None:
        coordinator = SimpleNamespace(
            async_config_entry_first_refresh=AsyncMock()
        )
        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock()
            ),
        )
        entry = SimpleNamespace(
            options=options,
            entry_id="entry-a",
            async_on_unload=Mock(),
            add_update_listener=Mock(),
        )

        with patch(
            "custom_components.wyze_garmin_sync.WyzeGarminCoordinator",
            return_value=coordinator,
        ) as coordinator_class:
            await async_setup_entry(hass, entry)

        coordinator_class.assert_called_once_with(
            hass,
            entry,
            update_interval=(
                None
                if expected_minutes is None
                else timedelta(minutes=expected_minutes)
            ),
        )
        coordinator.async_config_entry_first_refresh.assert_awaited_once()
