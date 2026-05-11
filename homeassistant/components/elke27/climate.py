"""Climate platform for Elke27 thermostats."""

from typing import Any, override

from elke27_lib import ThermostatState

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    FAN_AUTO,
    FAN_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Elke27DataUpdateCoordinator
from .helpers import build_unique_id, unique_base
from .models import Elke27ConfigEntry

PARALLEL_UPDATES = 1

_HVAC_TO_TSTAT_MODE: dict[HVACMode, str] = {
    HVACMode.OFF: "OFF",
    HVACMode.HEAT: "HEAT",
    HVACMode.COOL: "COOL",
    HVACMode.HEAT_COOL: "AUTO",
}
_TSTAT_TO_HVAC_MODE: dict[str, HVACMode] = {
    value: key for key, value in _HVAC_TO_TSTAT_MODE.items()
}
_FAN_TO_TSTAT_MODE: dict[str, str] = {
    FAN_AUTO: "AUTO",
    FAN_ON: "ON",
}
_TSTAT_TO_FAN_MODE: dict[str, str] = {
    value: key for key, value in _FAN_TO_TSTAT_MODE.items()
}
# Some panels report temperatures with one implied decimal place.
_IMPLIED_DECIMAL_TEMP_THRESHOLD = 200


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: Elke27ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Elke27 thermostats from a config entry."""
    coordinator = entry.runtime_data.coordinator
    known_ids: set[int] = set()

    @callback
    def _async_add_new_thermostats() -> None:
        thermostats = coordinator.data.thermostats
        new_ids = sorted(thermostats.keys() - known_ids)
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            Elke27Thermostat(coordinator, entry, thermostats[tstat_id])
            for tstat_id in new_ids
        )

    _async_add_new_thermostats()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_thermostats))


class Elke27Thermostat(CoordinatorEntity[Elke27DataUpdateCoordinator], ClimateEntity):
    """Representation of an Elke27 thermostat."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_hvac_modes = list(_HVAC_TO_TSTAT_MODE)
    _attr_fan_modes = list(_FAN_TO_TSTAT_MODE)
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_min_temp = 40
    _attr_max_temp = 99

    def __init__(
        self,
        coordinator: Elke27DataUpdateCoordinator,
        entry: Elke27ConfigEntry,
        tstat: ThermostatState,
    ) -> None:
        """Initialize the thermostat entity."""
        super().__init__(coordinator)
        self._tstat_id = tstat.tstat_id
        self._attr_name = tstat.name or f"Thermostat {tstat.tstat_id}"
        panel_identifier = unique_base(entry)
        self._attr_unique_id = build_unique_id(
            panel_identifier, f"tstat:{tstat.tstat_id}"
        )
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, panel_identifier)})

    @property
    def tstat(self) -> ThermostatState | None:
        """Return the current thermostat snapshot."""
        return self.coordinator.data.thermostats.get(self._tstat_id)

    @property
    @override
    def available(self) -> bool:
        """Return if the entity is available."""
        return (
            super().available and self.coordinator.is_ready and self.tstat is not None
        )

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode."""
        if (tstat := self.tstat) is None or tstat.mode is None:
            return None
        return _TSTAT_TO_HVAC_MODE.get(tstat.mode.strip().upper())

    @property
    @override
    def hvac_action(self) -> HVACAction | None:
        """Return the HVAC action implied by the current mode."""
        mode = self.hvac_mode
        if mode is HVACMode.HEAT:
            return HVACAction.HEATING
        if mode is HVACMode.COOL:
            return HVACAction.COOLING
        if mode is HVACMode.OFF:
            return HVACAction.OFF
        return None

    @property
    @override
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if (tstat := self.tstat) is None:
            return None
        return _normalize_temperature(tstat.temperature)

    @property
    @override
    def target_temperature_low(self) -> float | None:
        """Return the heat setpoint."""
        if (tstat := self.tstat) is None:
            return None
        return _normalize_temperature(tstat.heat_setpoint)

    @property
    @override
    def target_temperature_high(self) -> float | None:
        """Return the cool setpoint."""
        if (tstat := self.tstat) is None:
            return None
        return _normalize_temperature(tstat.cool_setpoint)

    @property
    @override
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        if (tstat := self.tstat) is None or tstat.fan_mode is None:
            return None
        return _TSTAT_TO_FAN_MODE.get(tstat.fan_mode.strip().upper())

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode."""
        await self._async_set_status(mode=_HVAC_TO_TSTAT_MODE[hvac_mode])

    @override
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new fan mode."""
        await self._async_set_status(fan_mode=_FAN_TO_TSTAT_MODE[fan_mode])

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the heat and/or cool setpoints in degrees Fahrenheit."""
        heat_setpoint: float | None = kwargs.get(ATTR_TARGET_TEMP_LOW)
        cool_setpoint: float | None = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        if heat_setpoint is None and cool_setpoint is None:
            msg = "A target temperature range is required."
            raise ServiceValidationError(msg)
        # The library encodes Fahrenheit setpoints to protocol tenths.
        await self._async_set_status(
            heat_setpoint=heat_setpoint, cool_setpoint=cool_setpoint
        )

    async def _async_set_status(
        self,
        *,
        mode: str | None = None,
        fan_mode: str | None = None,
        heat_setpoint: float | None = None,
        cool_setpoint: float | None = None,
    ) -> None:
        """Request a thermostat status change."""
        if not await self.coordinator.async_set_tstat_status(
            self._tstat_id,
            mode=mode,
            fan_mode=fan_mode,
            heat_setpoint=heat_setpoint,
            cool_setpoint=cool_setpoint,
        ):
            msg = f"Thermostat {self._tstat_id} command was not acknowledged."
            raise HomeAssistantError(msg)


def _normalize_temperature(value: float | None) -> float | None:
    """Normalize a panel temperature to degrees Fahrenheit."""
    if value is None:
        return None
    if abs(value) >= _IMPLIED_DECIMAL_TEMP_THRESHOLD:
        return value / 10
    return float(value)
