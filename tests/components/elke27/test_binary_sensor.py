"""Tests for Elke27 zone binary sensors."""

from unittest.mock import MagicMock

from elke27_lib import ZoneDefinition, ZoneState
import pytest

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ICON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import (
    build_snapshot,
    connection_state_changed_event,
    csm_snapshot_updated_event,
    setup_integration,
)

from tests.common import MockConfigEntry

FRONT_DOOR_ENTITY_ID = "binary_sensor.panel_front_door"


@pytest.fixture(autouse=True)
def mock_zones(mock_client: MagicMock) -> None:
    """Add zones to the mocked panel snapshot."""
    mock_client.get_snapshot.return_value = build_snapshot(
        zones={
            1: ZoneState(
                zone_id=1, name="Front door", open=False, bypassed=False, trouble=False
            ),
            2: ZoneState(zone_id=2, name="Spare", open=False),
            3: ZoneState(zone_id=3, name="Hall", open=True),
            4: ZoneState(zone_id=4, name=None, open=None),
        },
        zone_definitions={
            1: ZoneDefinition(
                zone_id=1,
                name="Front door",
                definition="BURG EE DELAY",
                zone_type="door",
            ),
            2: ZoneDefinition(zone_id=2, name="Spare", definition="UNDEFINED"),
            3: ZoneDefinition(
                zone_id=3, name="Hallway", definition="BURG INTERIOR", kind="motion"
            ),
        },
    )


async def test_zone_binary_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test zone binary sensors are created from the snapshot."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(FRONT_DOOR_ENTITY_ID)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_DEVICE_CLASS] == BinarySensorDeviceClass.DOOR
    assert state.attributes[ATTR_ICON] == "mdi:door-closed-lock"
    assert state.attributes["definition"] == "BURG EE DELAY"
    assert state.attributes["bypassed"] is False
    assert state.attributes["trouble"] is False

    state = hass.states.get("binary_sensor.panel_hallway")
    assert state.state == STATE_ON
    assert state.attributes[ATTR_DEVICE_CLASS] == BinarySensorDeviceClass.MOTION
    assert state.attributes[ATTR_ICON] == "mdi:motion-sensor"

    state = hass.states.get("binary_sensor.panel_zone_4")
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_DEVICE_CLASS] == BinarySensorDeviceClass.OPENING
    assert ATTR_ICON not in state.attributes

    # Zones with an UNDEFINED definition are skipped.
    assert hass.states.get("binary_sensor.panel_spare") is None

    entity_entry = entity_registry.async_get(FRONT_DOOR_ENTITY_ID)
    assert entity_entry is not None
    assert entity_entry.unique_id == "1234:zone:1"


@pytest.mark.parametrize(
    ("zone_type", "expected_device_class"),
    [
        ("window", BinarySensorDeviceClass.WINDOW),
        ("door", BinarySensorDeviceClass.DOOR),
        ("motion", BinarySensorDeviceClass.MOTION),
        ("other", BinarySensorDeviceClass.OPENING),
    ],
)
async def test_zone_device_class(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    zone_type: str,
    expected_device_class: BinarySensorDeviceClass,
) -> None:
    """Test the zone type selects the device class."""
    mock_client.get_snapshot.return_value = build_snapshot(
        zones={1: ZoneState(zone_id=1, name="Front door", open=False)},
        zone_definitions={
            1: ZoneDefinition(zone_id=1, definition="WATER", zone_type=zone_type)
        },
    )
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(FRONT_DOOR_ENTITY_ID)
    assert state.attributes[ATTR_DEVICE_CLASS] == expected_device_class


async def test_zone_updates(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test pushed snapshots update zones, add new zones and mark missing ones."""
    await setup_integration(hass, mock_config_entry)

    snapshot = build_snapshot(
        zones={
            1: ZoneState(zone_id=1, name="Front door", open=True),
            2: ZoneState(zone_id=2, name="Spare", open=False),
        },
        zone_definitions={
            1: ZoneDefinition(zone_id=1, name="Front door", definition="BURG EE DELAY"),
            2: ZoneDefinition(zone_id=2, name="Spare", definition="WATER"),
        },
        version=2,
    )
    mock_client.get_snapshot.return_value = snapshot
    mock_client.event_callback(csm_snapshot_updated_event(snapshot))
    await hass.async_block_till_done()

    state = hass.states.get(FRONT_DOOR_ENTITY_ID)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_ICON] == "mdi:door-open"
    assert hass.states.get("binary_sensor.panel_spare").state == STATE_OFF
    state = hass.states.get("binary_sensor.panel_hallway")
    assert state.state == STATE_UNAVAILABLE
    assert "definition" not in state.attributes


async def test_zone_unavailable_when_disconnected(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test zone binary sensors become unavailable when the panel disconnects."""
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(FRONT_DOOR_ENTITY_ID).state == STATE_OFF

    mock_client.is_ready = False
    mock_client.connection_callback(connection_state_changed_event(connected=False))
    await hass.async_block_till_done()

    assert hass.states.get(FRONT_DOOR_ENTITY_ID).state == STATE_UNAVAILABLE
