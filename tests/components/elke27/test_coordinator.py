"""Tests for the Elke27 data update coordinator."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from elke27_lib import ArmMode
from elke27_lib.errors import Elke27ConnectionError, Elke27PinRequiredError
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.elke27 import coordinator as coordinator_module
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from . import (
    connection_state_changed_event,
    domain_csm_changed_event,
    setup_integration,
    table_csm_changed_event,
)


@pytest.mark.parametrize(
    "event_factory",
    [
        pytest.param(domain_csm_changed_event, id="domain-csm"),
        pytest.param(table_csm_changed_event, id="table-csm"),
    ],
)
async def test_csm_change_refreshes_domain_config(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    event_factory: Callable[[str], Any],
) -> None:
    """Test CSM change events trigger a debounced domain config refresh."""
    monkeypatch.setattr(coordinator_module, "_DEBOUNCE_SECONDS", 0)
    await setup_integration(hass, mock_config_entry)

    mock_client.event_callback(event_factory("zone"))
    await hass.async_block_till_done()

    mock_client.async_refresh_domain_config.assert_awaited_once_with("zone")


async def test_domain_refresh_errors_are_deferred(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test connection errors during a domain refresh are not raised."""
    monkeypatch.setattr(coordinator_module, "_DEBOUNCE_SECONDS", 0)
    await setup_integration(hass, mock_config_entry)
    mock_client.async_refresh_domain_config.side_effect = Elke27ConnectionError()

    mock_client.event_callback(domain_csm_changed_event("zone"))
    await hass.async_block_till_done()

    mock_client.async_refresh_domain_config.assert_awaited_once_with("zone")


async def test_reconnect_triggers_full_refresh(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a reconnect event triggers a full CSM refresh."""
    await setup_integration(hass, mock_config_entry)
    assert mock_client.async_refresh_csm.await_count == 1

    mock_client.event_callback(connection_state_changed_event(connected=True))
    await hass.async_block_till_done()

    assert mock_client.async_refresh_csm.await_count == 2


async def test_unload_cancels_pending_domain_refresh(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test unloading cancels a pending debounced domain refresh."""
    await setup_integration(hass, mock_config_entry)

    mock_client.event_callback(domain_csm_changed_event("zone"))
    await asyncio.sleep(0)

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.async_refresh_domain_config.assert_not_awaited()
    mock_client.async_disconnect.assert_awaited_once()


async def test_arm_area_connection_error(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test arm area propagates connection errors as update failed."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    mock_client.async_arm_area.side_effect = Elke27ConnectionError()

    with pytest.raises(UpdateFailed, match="Unable to refresh panel data"):
        await coordinator.async_arm_area(1, ArmMode.ARMED_AWAY, "1234")


async def test_zone_bypass_requires_pin(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test zone bypass without a PIN is rejected."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    with pytest.raises(Elke27PinRequiredError):
        await coordinator.async_set_zone_bypass(1, bypassed=True, pin=None)


async def test_disarm_area_command_error(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test disarm commands surface command failures."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    mock_client.async_disarm_area.return_value = SimpleNamespace(
        ok=False, error="denied"
    )

    with pytest.raises(Exception, match="Area disarm failed: denied"):
        await coordinator.async_disarm_area(1, "1234")


async def test_arm_area_requires_pin(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test arm area without a PIN is rejected."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator

    with pytest.raises(Elke27PinRequiredError):
        await coordinator.async_arm_area(1, ArmMode.ARMED_AWAY, None)


async def test_zone_bypass_connection_error(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test zone bypass propagates connection errors."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    mock_client.async_set_zone_bypass.side_effect = Elke27ConnectionError()

    with pytest.raises(UpdateFailed, match="Unable to refresh panel data"):
        await coordinator.async_set_zone_bypass(1, bypassed=True, pin="1234")


async def test_disarm_area_connection_error(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test disarm area propagates connection errors."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    mock_client.async_disarm_area.side_effect = Elke27ConnectionError()

    with pytest.raises(UpdateFailed, match="Unable to refresh panel data"):
        await coordinator.async_disarm_area(1, "1234")


async def test_arm_area_command_failure_exception(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test arm commands surface exception failures."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    mock_client.async_arm_area.return_value = SimpleNamespace(
        ok=False, error=ValueError("rejected")
    )

    with pytest.raises(Exception, match="Area arming failed: rejected"):
        await coordinator.async_arm_area(1, ArmMode.ARMED_AWAY, "1234")


async def test_arm_area_command_failure_bool(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test arm commands propagate boolean rejections."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    mock_client.async_arm_area.return_value = False

    assert await coordinator.async_arm_area(1, ArmMode.ARMED_AWAY, "1234") is False


async def test_require_client_raises_when_disconnected(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test coordinator commands fail after the client is cleared."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    coordinator._client = None

    with pytest.raises(Exception, match="Client is not connected."):
        await coordinator.async_arm_area(1, ArmMode.ARMED_AWAY, "1234")


async def test_async_disconnect_client_swallows_connection_errors() -> None:
    """Test failed disconnect during setup cleanup is ignored."""

    client = MagicMock()
    client.async_disconnect = AsyncMock(side_effect=Elke27ConnectionError())

    await coordinator_module._async_disconnect_client(client)
