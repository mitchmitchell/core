"""Light platform for Elke27 lights."""

from typing import Any, override

from elke27_lib import LightState

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
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

_ELK_MAX_DIM_LEVEL = 99


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: Elke27ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Elke27 lights from a config entry."""
    coordinator = entry.runtime_data.coordinator
    known_ids: set[int] = set()

    @callback
    def _async_add_new_lights() -> None:
        lights = coordinator.data.lights
        new_ids = sorted(lights.keys() - known_ids)
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            Elke27Light(coordinator, entry, lights[light_id]) for light_id in new_ids
        )

    _async_add_new_lights()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_lights))


class Elke27Light(CoordinatorEntity[Elke27DataUpdateCoordinator], LightEntity):
    """Representation of an Elke27 light."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        coordinator: Elke27DataUpdateCoordinator,
        entry: Elke27ConfigEntry,
        light: LightState,
    ) -> None:
        """Initialize the light entity."""
        super().__init__(coordinator)
        self._light_id = light.light_id
        self._attr_name = light.name or f"Light {light.light_id}"
        panel_identifier = unique_base(entry)
        self._attr_unique_id = build_unique_id(
            panel_identifier, f"light:{light.light_id}"
        )
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, panel_identifier)})

    @property
    def light(self) -> LightState | None:
        """Return the current light snapshot."""
        return self.coordinator.data.lights.get(self._light_id)

    @property
    @override
    def available(self) -> bool:
        """Return if the entity is available."""
        return (
            super().available and self.coordinator.is_ready and self.light is not None
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return if the light is on."""
        if (light := self.light) is None:
            return None
        if light.state is not None:
            return light.state
        if light.level is not None:
            return light.level > 0
        return None

    @property
    @override
    def brightness(self) -> int | None:
        """Return the current brightness (0-255)."""
        if (light := self.light) is None or light.level is None:
            return None
        level = max(0, min(_ELK_MAX_DIM_LEVEL, light.level))
        return round(level * 255 / _ELK_MAX_DIM_LEVEL)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        level = _ELK_MAX_DIM_LEVEL
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            # Keep a minimum level of 1 so an ON request never turns the light off.
            level = max(1, round(brightness * _ELK_MAX_DIM_LEVEL / 255))
        await self._async_set_light(on=True, level=level)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_set_light(on=False, level=0)

    async def _async_set_light(self, *, on: bool, level: int) -> None:
        """Request a light state change."""
        if not await self.coordinator.async_set_light(
            self._light_id, on=on, level=level
        ):
            msg = f"Light {self._light_id} command was not acknowledged."
            raise HomeAssistantError(msg)
