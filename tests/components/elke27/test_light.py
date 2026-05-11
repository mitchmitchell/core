"""Tests for Elke27 lights."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from elke27_lib import LightState
from elke27_lib.errors import Elke27ConnectionError
import pytest

from homeassistant.components.light import ATTR_BRIGHTNESS, DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from . import (
    build_snapshot,
    connection_state_changed_event,
    csm_snapshot_updated_event,
    setup_integration,
)

from tests.common import MockConfigEntry

ENTITY_ID = "light.panel_porch"


@pytest.fixture(autouse=True)
def mock_lights(mock_client: MagicMock) -> None:
    """Add lights to the mocked panel snapshot."""
    mock_client.async_execute.return_value = SimpleNamespace(ok=True, error=None)
    mock_client.get_snapshot.return_value = build_snapshot(
        lights={1: LightState(light_id=1, name="Porch", state=True, level=99)}
    )


async def test_light_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test light entities are created from the snapshot."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 255

    entity_entry = entity_registry.async_get(ENTITY_ID)
    assert entity_entry is not None
    assert entity_entry.unique_id == "1234:light:1"


@pytest.mark.parametrize(
    ("light", "expected_state", "expected_brightness"),
    [
        pytest.param(
            LightState(light_id=1, name="Porch", state=False, level=0),
            STATE_OFF,
            None,
            id="off",
        ),
        pytest.param(
            LightState(light_id=1, name="Porch", level=50),
            STATE_ON,
            129,
            id="level-only",
        ),
        pytest.param(
            LightState(light_id=1, name="Porch", level=0),
            STATE_OFF,
            None,
            id="level-zero",
        ),
        pytest.param(
            LightState(light_id=1, name="Porch", state=True),
            STATE_ON,
            None,
            id="no-level",
        ),
        pytest.param(
            LightState(light_id=1, name="Porch"),
            STATE_UNKNOWN,
            None,
            id="no-state",
        ),
    ],
)
async def test_light_state_mapping(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    light: LightState,
    expected_state: str,
    expected_brightness: int | None,
) -> None:
    """Test panel light states map to Home Assistant light states."""
    mock_client.get_snapshot.return_value = build_snapshot(lights={1: light})
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == expected_state
    assert state.attributes.get(ATTR_BRIGHTNESS) == expected_brightness


@pytest.mark.parametrize(
    ("service", "data", "expected_params"),
    [
        pytest.param(SERVICE_TURN_ON, {}, {"status": "ON", "level": 99}, id="turn-on"),
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_BRIGHTNESS: 128},
            {"status": "ON", "level": 50},
            id="turn-on-brightness",
        ),
        pytest.param(
            SERVICE_TURN_ON,
            {ATTR_BRIGHTNESS: 1},
            {"status": "ON", "level": 1},
            id="turn-on-minimum",
        ),
        pytest.param(
            SERVICE_TURN_OFF, {}, {"status": "OFF", "level": 0}, id="turn-off"
        ),
    ],
)
async def test_light_services(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    service: str,
    data: dict[str, Any],
    expected_params: dict[str, Any],
) -> None:
    """Test light services send light commands to the panel."""
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        LIGHT_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID, **data}, blocking=True
    )

    mock_client.async_execute.assert_awaited_once_with(
        "light_set_status", light_id=1, **expected_params
    )


@pytest.mark.parametrize(
    ("side_effect", "return_value", "message"),
    [
        pytest.param(
            Elke27ConnectionError("lost"),
            None,
            "Unable to refresh panel data",
            id="connection-error",
        ),
        pytest.param(
            None,
            SimpleNamespace(ok=False, error="rejected"),
            "Light control failed: rejected",
            id="rejected",
        ),
        pytest.param(
            None,
            SimpleNamespace(ok=False, error=None),
            "Light 1 command was not acknowledged.",
            id="not-acknowledged",
        ),
    ],
)
async def test_light_service_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    side_effect: Exception | None,
    return_value: SimpleNamespace | None,
    message: str,
) -> None:
    """Test light service failures raise Home Assistant errors."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_execute.side_effect = side_effect
    mock_client.async_execute.return_value = return_value

    with pytest.raises(HomeAssistantError, match=message):
        await hass.services.async_call(
            LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
        )


async def test_light_availability(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test lights become unavailable on disconnect or when removed."""
    await setup_integration(hass, mock_config_entry)

    mock_client.is_ready = False
    mock_client.connection_callback(connection_state_changed_event(connected=False))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    mock_client.is_ready = True
    snapshot = build_snapshot(
        lights={2: LightState(light_id=2, name=None, state=False)}, version=2
    )
    mock_client.get_snapshot.return_value = snapshot
    mock_client.event_callback(csm_snapshot_updated_event(snapshot))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    assert hass.states.get("light.panel_light_2").state == STATE_OFF
