"""Tests for Elke27 locks."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from elke27_lib import LockState
from elke27_lib.errors import Elke27ConnectionError, Elke27PinRequiredError
import pytest

from homeassistant.components.lock import (
    DOMAIN as LOCK_DOMAIN,
    LockState as HALockState,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
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

ENTITY_ID = "lock.panel_front_door"


@pytest.fixture(autouse=True)
def mock_locks(mock_client: MagicMock) -> None:
    """Add locks to the mocked panel snapshot."""
    mock_client.async_execute.return_value = SimpleNamespace(ok=True, error=None)
    mock_client.get_snapshot.return_value = build_snapshot(
        locks={1: LockState(lock_id=1, name="Front door", locked=True)}
    )


async def test_lock_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test lock entities are created from the snapshot."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == HALockState.LOCKED

    entity_entry = entity_registry.async_get(ENTITY_ID)
    assert entity_entry is not None
    assert entity_entry.unique_id == "1234:lock:1"


@pytest.mark.parametrize(
    ("lock", "expected_state"),
    [
        pytest.param(
            LockState(lock_id=1, name="Front door", locked=False),
            HALockState.UNLOCKED,
            id="unlocked",
        ),
        pytest.param(
            LockState(lock_id=1, name="Front door", status="locked"),
            HALockState.LOCKED,
            id="status-locked",
        ),
        pytest.param(
            LockState(lock_id=1, name="Front door", status="OFF"),
            HALockState.UNLOCKED,
            id="status-off",
        ),
        pytest.param(
            LockState(lock_id=1, name="Front door", status="jammed"),
            STATE_UNKNOWN,
            id="status-unknown",
        ),
        pytest.param(
            LockState(lock_id=1, name="Front door"),
            STATE_UNKNOWN,
            id="no-state",
        ),
    ],
)
async def test_lock_state_mapping(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    lock: LockState,
    expected_state: str,
) -> None:
    """Test panel lock states map to Home Assistant lock states."""
    mock_client.get_snapshot.return_value = build_snapshot(locks={1: lock})
    await setup_integration(hass, mock_config_entry)

    assert hass.states.get(ENTITY_ID).state == expected_state


@pytest.mark.parametrize(
    ("service", "expected_status"),
    [(SERVICE_LOCK, "ON"), (SERVICE_UNLOCK, "OFF")],
)
async def test_lock_services(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    service: str,
    expected_status: str,
) -> None:
    """Test lock services send lock commands to the panel."""
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        LOCK_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )

    mock_client.async_execute.assert_awaited_once_with(
        "lock_set_status", lock_id=1, status=expected_status
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
            SimpleNamespace(ok=False, error=Elke27PinRequiredError("PIN required")),
            "Lock control failed:",
            id="pin-required",
        ),
        pytest.param(
            None,
            SimpleNamespace(ok=False, error=None),
            "Lock 1 command was not acknowledged.",
            id="not-acknowledged",
        ),
    ],
)
async def test_lock_service_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    side_effect: Exception | None,
    return_value: SimpleNamespace | None,
    message: str,
) -> None:
    """Test lock service failures raise Home Assistant errors."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_execute.side_effect = side_effect
    mock_client.async_execute.return_value = return_value

    with pytest.raises(HomeAssistantError, match=message):
        await hass.services.async_call(
            LOCK_DOMAIN, SERVICE_UNLOCK, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
        )


async def test_lock_availability(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test locks become unavailable on disconnect or when removed."""
    await setup_integration(hass, mock_config_entry)

    mock_client.is_ready = False
    mock_client.connection_callback(connection_state_changed_event(connected=False))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    mock_client.is_ready = True
    snapshot = build_snapshot(version=2)
    mock_client.get_snapshot.return_value = snapshot
    mock_client.event_callback(csm_snapshot_updated_event(snapshot))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    snapshot = build_snapshot(
        locks={
            1: LockState(lock_id=1, name="Front door", locked=False),
            2: LockState(lock_id=2, name=None, locked=True),
        },
        version=3,
    )
    mock_client.get_snapshot.return_value = snapshot
    mock_client.event_callback(csm_snapshot_updated_event(snapshot))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == HALockState.UNLOCKED
    assert hass.states.get("lock.panel_lock_2").state == HALockState.LOCKED
