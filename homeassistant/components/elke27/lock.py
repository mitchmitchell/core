"""Lock platform for Elke27 locks."""

from typing import Any, override

from elke27_lib import LockState

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Elke27DataUpdateCoordinator
from .helpers import build_unique_id, unique_base
from .models import Elke27ConfigEntry

PARALLEL_UPDATES = 1

_LOCKED_STATUSES = frozenset({"ON", "LOCKED"})
_UNLOCKED_STATUSES = frozenset({"OFF", "UNLOCKED"})


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: Elke27ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Elke27 locks from a config entry."""
    coordinator = entry.runtime_data.coordinator
    known_ids: set[int] = set()

    @callback
    def _async_add_new_locks() -> None:
        locks = coordinator.data.locks
        new_ids = sorted(locks.keys() - known_ids)
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            Elke27Lock(coordinator, entry, locks[lock_id]) for lock_id in new_ids
        )

    _async_add_new_locks()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_locks))


class Elke27Lock(CoordinatorEntity[Elke27DataUpdateCoordinator], LockEntity):
    """Representation of an Elke27 lock."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elke27DataUpdateCoordinator,
        entry: Elke27ConfigEntry,
        lock: LockState,
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(coordinator)
        self._lock_id = lock.lock_id
        self._attr_name = lock.name or f"Lock {lock.lock_id}"
        panel_identifier = unique_base(entry)
        self._attr_unique_id = build_unique_id(panel_identifier, f"lock:{lock.lock_id}")
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, panel_identifier)})

    @property
    def lock_state(self) -> LockState | None:
        """Return the current lock snapshot."""
        return self.coordinator.data.locks.get(self._lock_id)

    @property
    @override
    def available(self) -> bool:
        """Return if the entity is available."""
        return (
            super().available
            and self.coordinator.is_ready
            and self.lock_state is not None
        )

    @property
    @override
    def is_locked(self) -> bool | None:
        """Return if the lock is locked."""
        if (lock := self.lock_state) is None:
            return None
        if lock.locked is not None:
            return lock.locked
        if lock.status is None:
            return None
        status = lock.status.strip().upper()
        if status in _LOCKED_STATUSES:
            return True
        if status in _UNLOCKED_STATUSES:
            return False
        return None

    @override
    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock."""
        await self._async_set_lock(locked=True)

    @override
    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        await self._async_set_lock(locked=False)

    async def _async_set_lock(self, *, locked: bool) -> None:
        """Request a lock state change."""
        if not await self.coordinator.async_set_lock(self._lock_id, locked=locked):
            msg = f"Lock {self._lock_id} command was not acknowledged."
            raise HomeAssistantError(msg)
