"""Switch platform for Elke27 outputs."""

from typing import Any, override

from elke27_lib import OutputState
from elke27_lib.errors import Elke27PinRequiredError

from homeassistant.components.switch import SwitchEntity
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


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: Elke27ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Elke27 output switches from a config entry."""
    coordinator = entry.runtime_data.coordinator
    known_ids: set[int] = set()

    @callback
    def _async_add_new_outputs() -> None:
        outputs = coordinator.data.outputs
        new_ids = sorted(outputs.keys() - known_ids)
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            Elke27OutputSwitch(coordinator, entry, outputs[output_id])
            for output_id in new_ids
        )

    _async_add_new_outputs()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_outputs))


class Elke27OutputSwitch(CoordinatorEntity[Elke27DataUpdateCoordinator], SwitchEntity):
    """Representation of an Elke27 output."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elke27DataUpdateCoordinator,
        entry: Elke27ConfigEntry,
        output: OutputState,
    ) -> None:
        """Initialize the output entity."""
        super().__init__(coordinator)
        self._output_id = output.output_id
        self._attr_name = output.name or f"Output {output.output_id}"
        panel_identifier = unique_base(entry)
        self._attr_unique_id = build_unique_id(
            panel_identifier, f"output:{output.output_id}"
        )
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, panel_identifier)})

    @property
    def output(self) -> OutputState | None:
        """Return the current output snapshot."""
        return self.coordinator.data.outputs.get(self._output_id)

    @property
    @override
    def available(self) -> bool:
        """Return if the entity is available."""
        return (
            super().available and self.coordinator.is_ready and self.output is not None
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return if the output is on."""
        if (output := self.output) is None:
            return None
        return output.state

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the output on."""
        await self._async_set_output(on=True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the output off."""
        await self._async_set_output(on=False)

    async def _async_set_output(self, *, on: bool) -> None:
        """Request an output state change."""
        try:
            accepted = await self.coordinator.async_set_output(self._output_id, on=on)
        except Elke27PinRequiredError as err:
            msg = "PIN required to perform this action."
            raise HomeAssistantError(msg) from err
        if not accepted:
            msg = f"Output {self._output_id} command was not acknowledged."
            raise HomeAssistantError(msg)
