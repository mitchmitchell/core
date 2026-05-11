"""Binary sensor platform for Elke27 zones."""

from typing import Any, override

from elke27_lib import PanelSnapshot, ZoneDefinition, ZoneState

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Elke27DataUpdateCoordinator
from .helpers import build_unique_id, unique_base
from .models import Elke27ConfigEntry

PARALLEL_UPDATES = 0

_UNDEFINED_DEFINITION = "UNDEFINED"

_ZONE_ICON_BY_DEFINITION = {
    _UNDEFINED_DEFINITION: "mdi:help-circle-outline",
    "BURG EE DELAY": "mdi:door-closed-lock",
    "BURG PERIM INST": "mdi:window-closed",
    "BURG INTERIOR": "mdi:motion-sensor",
    "BURG 24HR": "mdi:shield-alert",
    "BURG BOX TAMPER": "mdi:shield-off-outline",
    "FIRE": "mdi:fire",
    "CARBON MONOXIDE": "mdi:molecule-co",
    "PANIC": "mdi:alert-octagon",
    "MEDICAL": "mdi:medical-bag",
    "AUTOMATION": "mdi:home-automation",
    "POWER SUPERVISION": "mdi:power",
    "WATER": "mdi:water",
    "HILO TEMP": "mdi:thermometer",
}
_ZONE_OPEN_ICON_BY_DEFINITION = {
    "BURG EE DELAY": "mdi:door-open",
    "BURG PERIM INST": "mdi:window-open",
    "FIRE": "mdi:fire-alert",
    "POWER SUPERVISION": "mdi:power-alert",
    "WATER": "mdi:water-alert",
    "HILO TEMP": "mdi:thermometer-alert",
}


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: Elke27ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Elke27 zone binary sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    known_ids: set[int] = set()

    @callback
    def _async_add_new_zones() -> None:
        snapshot = coordinator.data
        new_entities: list[Elke27ZoneBinarySensor] = []
        for zone_id, zone in sorted(snapshot.zones.items()):
            if zone_id in known_ids:
                continue
            zone_definition = snapshot.zone_definitions.get(zone_id)
            if _definition(zone_definition) == _UNDEFINED_DEFINITION:
                continue
            known_ids.add(zone_id)
            new_entities.append(
                Elke27ZoneBinarySensor(coordinator, entry, zone, zone_definition)
            )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_zones))


class Elke27ZoneBinarySensor(
    CoordinatorEntity[Elke27DataUpdateCoordinator], BinarySensorEntity
):
    """Representation of an Elke27 zone."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elke27DataUpdateCoordinator,
        entry: Elke27ConfigEntry,
        zone: ZoneState,
        zone_definition: ZoneDefinition | None,
    ) -> None:
        """Initialize the zone entity."""
        super().__init__(coordinator)
        self._zone_id = zone.zone_id
        self._attr_name = (
            (zone_definition.name if zone_definition else None)
            or zone.name
            or f"Zone {zone.zone_id}"
        )
        self._attr_device_class = _zone_device_class(zone_definition)
        panel_identifier = unique_base(entry)
        self._attr_unique_id = build_unique_id(panel_identifier, f"zone:{zone.zone_id}")
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, panel_identifier)})

    @property
    def zone(self) -> ZoneState | None:
        """Return the current zone snapshot."""
        return self.coordinator.data.zones.get(self._zone_id)

    @property
    def definition(self) -> str | None:
        """Return the current zone definition."""
        return _definition(_zone_definition(self.coordinator.data, self._zone_id))

    @property
    @override
    def available(self) -> bool:
        """Return if the entity is available."""
        return super().available and self.coordinator.is_ready and self.zone is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return if the zone is open."""
        if (zone := self.zone) is None:
            return None
        return zone.open

    @property
    @override
    def icon(self) -> str | None:
        """Return an icon based on the zone definition and state."""
        if (definition := self.definition) is None:
            return None
        if self.is_on and definition in _ZONE_OPEN_ICON_BY_DEFINITION:
            return _ZONE_OPEN_ICON_BY_DEFINITION[definition]
        return _ZONE_ICON_BY_DEFINITION.get(definition)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional zone attributes."""
        if (zone := self.zone) is None:
            return {}
        return {
            "definition": self.definition,
            "bypassed": zone.bypassed,
            "trouble": zone.trouble,
        }


def _zone_definition(snapshot: PanelSnapshot, zone_id: int) -> ZoneDefinition | None:
    return snapshot.zone_definitions.get(zone_id)


def _definition(zone_definition: ZoneDefinition | None) -> str | None:
    if zone_definition is None or not zone_definition.definition:
        return None
    return zone_definition.definition


def _zone_device_class(
    zone_definition: ZoneDefinition | None,
) -> BinarySensorDeviceClass:
    zone_type = None
    if zone_definition is not None:
        zone_type = zone_definition.zone_type or zone_definition.kind
    if zone_type:
        normalized = zone_type.lower()
        if "motion" in normalized:
            return BinarySensorDeviceClass.MOTION
        if "window" in normalized:
            return BinarySensorDeviceClass.WINDOW
        if "door" in normalized:
            return BinarySensorDeviceClass.DOOR
    return BinarySensorDeviceClass.OPENING
