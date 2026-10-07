"""Tests for Elke27 thermostats."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from elke27_lib import ThermostatState
from elke27_lib.errors import Elke27ConnectionError
import pytest

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    DOMAIN as CLIMATE_DOMAIN,
    FAN_AUTO,
    FAN_ON,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from . import (
    build_snapshot,
    connection_state_changed_event,
    csm_snapshot_updated_event,
    setup_integration,
)

from tests.common import MockConfigEntry

ENTITY_ID = "climate.panel_hallway"


@pytest.fixture(autouse=True)
def mock_thermostats(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """Add thermostats to the mocked panel snapshot."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    mock_client.async_execute.return_value = SimpleNamespace(ok=True, error=None)
    mock_client.get_snapshot.return_value = build_snapshot(
        thermostats={
            1: ThermostatState(
                tstat_id=1,
                name="Hallway",
                temperature=71.5,
                heat_setpoint=68,
                cool_setpoint=76,
                mode="heat",
                fan_mode="AUTO",
            )
        }
    )


async def test_thermostat_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test thermostat entities are created with panel temperatures."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    # Fractional readings are shown at whole-degree precision.
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 72
    assert state.attributes[ATTR_TARGET_TEMP_LOW] == 68
    assert state.attributes[ATTR_TARGET_TEMP_HIGH] == 76
    assert state.attributes[ATTR_FAN_MODE] == FAN_AUTO

    entity_entry = entity_registry.async_get(ENTITY_ID)
    assert entity_entry is not None
    assert entity_entry.unique_id == "1234:tstat:1"


@pytest.mark.parametrize(
    ("mode", "expected_state", "expected_action"),
    [
        pytest.param("COOL", HVACMode.COOL, HVACAction.COOLING, id="cool"),
        pytest.param("OFF", HVACMode.OFF, HVACAction.OFF, id="off"),
        pytest.param("AUTO", HVACMode.HEAT_COOL, None, id="auto"),
        pytest.param("EMERGENCY", STATE_UNKNOWN, None, id="unsupported"),
        pytest.param(None, STATE_UNKNOWN, None, id="no-mode"),
    ],
)
async def test_thermostat_mode_mapping(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mode: str | None,
    expected_state: str,
    expected_action: HVACAction | None,
) -> None:
    """Test panel thermostat modes map to Home Assistant HVAC modes."""
    mock_client.get_snapshot.return_value = build_snapshot(
        thermostats={1: ThermostatState(tstat_id=1, name="Hallway", mode=mode)}
    )
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == expected_state
    assert state.attributes.get(ATTR_HVAC_ACTION) == expected_action
    assert state.attributes.get(ATTR_CURRENT_TEMPERATURE) is None
    assert state.attributes.get(ATTR_FAN_MODE) is None


@pytest.mark.parametrize(
    ("service", "data", "expected_params"),
    [
        pytest.param(
            SERVICE_SET_HVAC_MODE,
            {ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
            {"mode": "AUTO"},
            id="hvac-mode",
        ),
        pytest.param(
            SERVICE_SET_FAN_MODE,
            {ATTR_FAN_MODE: FAN_ON},
            {"fan_mode": "ON"},
            id="fan-mode",
        ),
        pytest.param(
            SERVICE_SET_TEMPERATURE,
            {ATTR_TARGET_TEMP_LOW: 66.5, ATTR_TARGET_TEMP_HIGH: 75},
            {"heat_setpoint": 66.5, "cool_setpoint": 75},
            id="temperature-range",
        ),
        pytest.param(SERVICE_TURN_OFF, {}, {"mode": "OFF"}, id="turn-off"),
        pytest.param(SERVICE_TURN_ON, {}, {"mode": "AUTO"}, id="turn-on"),
    ],
)
async def test_thermostat_services(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    service: str,
    data: dict[str, Any],
    expected_params: dict[str, Any],
) -> None:
    """Test climate services send unencoded Fahrenheit values to the library."""
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID, **data}, blocking=True
    )

    mock_client.async_execute.assert_awaited_once_with(
        "tstat_set_status", tstat_id=1, **expected_params
    )


async def test_set_temperature_requires_range(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test setting temperature without a range is rejected."""
    await setup_integration(hass, mock_config_entry)
    entity = hass.data["climate"].get_entity(ENTITY_ID)

    with pytest.raises(ServiceValidationError, match="target temperature range"):
        await entity.async_set_temperature()

    mock_client.async_execute.assert_not_awaited()


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
            SimpleNamespace(ok=False, error=None),
            "Thermostat 1 command was not acknowledged.",
            id="not-acknowledged",
        ),
    ],
)
async def test_thermostat_service_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    side_effect: Exception | None,
    return_value: SimpleNamespace | None,
    message: str,
) -> None:
    """Test climate service failures raise Home Assistant errors."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_execute.side_effect = side_effect
    mock_client.async_execute.return_value = return_value

    with pytest.raises(HomeAssistantError, match=message):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_FAN_MODE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_FAN_MODE: FAN_ON},
            blocking=True,
        )


async def test_thermostat_availability(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test thermostats become unavailable on disconnect or when removed."""
    await setup_integration(hass, mock_config_entry)

    mock_client.is_ready = False
    mock_client.connection_callback(connection_state_changed_event(connected=False))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    mock_client.is_ready = True
    snapshot = build_snapshot(
        thermostats={2: ThermostatState(tstat_id=2, name=None, mode="OFF")},
        version=2,
    )
    mock_client.get_snapshot.return_value = snapshot
    mock_client.event_callback(csm_snapshot_updated_event(snapshot))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    assert hass.states.get("climate.panel_thermostat_2").state == HVACMode.OFF
