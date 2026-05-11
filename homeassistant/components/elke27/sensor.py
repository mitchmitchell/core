"""Sensor platform for Elke27 panel diagnostics."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Elke27DataUpdateCoordinator
from .helpers import build_unique_id, unique_base
from .models import Elke27ConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class Elke27SensorEntityDescription(SensorEntityDescription):
    """Describe an Elke27 panel sensor."""

    numeric_id: int
    value_fn: Callable[[Elke27DataUpdateCoordinator], StateType]


SENSORS: tuple[Elke27SensorEntityDescription, ...] = (
    Elke27SensorEntityDescription(
        key="panel_name",
        translation_key="panel_name",
        numeric_id=1,
        value_fn=lambda coordinator: coordinator.data.panel.panel_name,
    ),
    Elke27SensorEntityDescription(
        key="panel_ready",
        translation_key="panel_ready",
        numeric_id=2,
        device_class=SensorDeviceClass.ENUM,
        options=["connected", "disconnected"],
        value_fn=lambda coordinator: (
            "connected" if coordinator.is_ready else "disconnected"
        ),
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: Elke27ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Elke27 panel sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        Elke27Sensor(coordinator, entry, description) for description in SENSORS
    )


class Elke27Sensor(CoordinatorEntity[Elke27DataUpdateCoordinator], SensorEntity):
    """Representation of an Elke27 panel sensor."""

    entity_description: Elke27SensorEntityDescription
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elke27DataUpdateCoordinator,
        entry: Elke27ConfigEntry,
        description: Elke27SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        panel_identifier = unique_base(entry)
        self._attr_unique_id = build_unique_id(
            panel_identifier, f"panel:{description.numeric_id}"
        )
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, panel_identifier)})

    @property
    @override
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator)
