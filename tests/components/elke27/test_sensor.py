"""Tests for Elke27 panel sensors."""

from unittest.mock import MagicMock

from homeassistant.components.sensor import ATTR_OPTIONS
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import connection_state_changed_event, setup_integration

from tests.common import MockConfigEntry

PANEL_NAME_ENTITY_ID = "sensor.panel_panel_name"
PANEL_STATE_ENTITY_ID = "sensor.panel_panel_state"


async def test_panel_sensors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test panel diagnostic sensors."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(PANEL_NAME_ENTITY_ID)
    assert state is not None
    assert state.state == "Panel"

    state = hass.states.get(PANEL_STATE_ENTITY_ID)
    assert state is not None
    assert state.state == "connected"
    assert state.attributes[ATTR_OPTIONS] == ["connected", "disconnected"]

    for entity_id, unique_id in (
        (PANEL_NAME_ENTITY_ID, "1234:panel:1"),
        (PANEL_STATE_ENTITY_ID, "1234:panel:2"),
    ):
        entity_entry = entity_registry.async_get(entity_id)
        assert entity_entry is not None
        assert entity_entry.unique_id == unique_id
        assert entity_entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_panel_state_tracks_connection(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the panel state sensor reports connection changes."""
    await setup_integration(hass, mock_config_entry)

    mock_client.is_ready = False
    mock_client.connection_callback(connection_state_changed_event(connected=False))
    await hass.async_block_till_done()

    assert hass.states.get(PANEL_STATE_ENTITY_ID).state == "disconnected"
