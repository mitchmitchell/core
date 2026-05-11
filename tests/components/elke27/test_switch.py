"""Tests for Elke27 output switches."""

from unittest.mock import MagicMock

from elke27_lib import OutputState
from elke27_lib.errors import Elke27ConnectionError, Elke27PinRequiredError
import pytest

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
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

ENTITY_ID = "switch.panel_garage_door"


@pytest.fixture(autouse=True)
def mock_outputs(mock_client: MagicMock) -> None:
    """Add outputs to the mocked panel snapshot."""
    mock_client.get_snapshot.return_value = build_snapshot(
        outputs={
            1: OutputState(output_id=1, name="Garage door", state=False),
            2: OutputState(output_id=2, name=None, state=None),
        }
    )


async def test_output_switches(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test output switches are created from the snapshot."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == STATE_OFF
    assert hass.states.get("switch.panel_output_2").state == STATE_UNKNOWN

    entity_entry = entity_registry.async_get(ENTITY_ID)
    assert entity_entry is not None
    assert entity_entry.unique_id == "1234:output:1"


async def test_output_state_updates_and_new_outputs(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test pushed snapshots update state, add outputs and mark missing ones."""
    await setup_integration(hass, mock_config_entry)

    snapshot = build_snapshot(
        outputs={
            1: OutputState(output_id=1, name="Garage door", state=True),
            3: OutputState(output_id=3, name="Siren", state=False),
        },
        version=2,
    )
    mock_client.get_snapshot.return_value = snapshot
    mock_client.event_callback(csm_snapshot_updated_event(snapshot))
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert hass.states.get("switch.panel_siren").state == STATE_OFF
    assert hass.states.get("switch.panel_output_2").state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("service", "expected_on"),
    [(SERVICE_TURN_ON, True), (SERVICE_TURN_OFF, False)],
)
async def test_output_services(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    service: str,
    expected_on: bool,
) -> None:
    """Test switch services control the panel output."""
    mock_client.async_set_output.return_value = None
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )

    mock_client.async_set_output.assert_awaited_once_with(1, on=expected_on)


@pytest.mark.parametrize(
    ("side_effect", "return_value", "message"),
    [
        pytest.param(
            Elke27PinRequiredError("pin"),
            None,
            "PIN required to perform this action.",
            id="pin-required",
        ),
        pytest.param(
            Elke27ConnectionError("lost"),
            None,
            "Unable to refresh panel data",
            id="connection-error",
        ),
        pytest.param(
            None,
            False,
            "Output 1 command was not acknowledged.",
            id="not-acknowledged",
        ),
    ],
)
async def test_output_service_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    side_effect: Exception | None,
    return_value: bool | None,
    message: str,
) -> None:
    """Test switch service failures raise Home Assistant errors."""
    mock_client.async_set_output.side_effect = side_effect
    mock_client.async_set_output.return_value = return_value
    await setup_integration(hass, mock_config_entry)

    with pytest.raises(HomeAssistantError, match=message):
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
        )


async def test_output_unavailable_when_disconnected(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test output switches become unavailable when the panel disconnects."""
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    mock_client.is_ready = False
    mock_client.connection_callback(connection_state_changed_event(connected=False))
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
