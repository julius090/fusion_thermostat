import logging, asyncio

from homeassistant.const import (CONF_NAME,  UnitOfTemperature)
from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity, HVACMode, ClimateEntityFeature, HVACAction

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.reload import async_setup_reload_service

from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_call_later
)

from . import DOMAIN, PLATFORMS

# Create Logger
_LOGGER = logging.getLogger(__name__)

CONF_TEMPERATURE_ENTITY_ID = "target_sensor"
CONF_REAL_THERMOSTATS = "real_thermostats"
CONF_WINDOWS_SENSOR = "windows_sensor"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_WINDOW_DELAY = "window_delay"

# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_TEMPERATURE_ENTITY_ID): cv.entity_id,
    vol.Required(CONF_REAL_THERMOSTATS): cv.ensure_list(cv.entity_id),
    vol.Optional(CONF_WINDOWS_SENSOR): cv.entity_id,
    vol.Optional(CONF_MIN_TEMP, default=7): cv.positive_float,
    vol.Optional(CONF_MAX_TEMP, default=25): cv.positive_float,
    vol.Optional(CONF_HOT_TOLERANCE, default=0.5): cv.positive_float,
    vol.Optional(CONF_COLD_TOLERANCE, default=0.5): cv.positive_float,
    vol.Optional(CONF_WINDOW_DELAY, default=10): cv.positive_int,
})

async def async_setup_platform(hass: HomeAssistant, config: ConfigType, async_add_entities: AddEntitiesCallback, discovery_info=None) -> None:
    """
    Sets up the FusionThermostat platform for Home Assistant. This function initializes
    the platform, registers the reload service, and adds the FusionThermostat entity
    to the Home Assistant ecosystem. It retrieves configuration parameters necessary
    for the thermostat's operation and handles exceptions during the setup process.

    Parameters
    ----------
    hass: HomeAssistant
        The HomeAssistant instance to associate the FusionThermostat platform with.

    config: ConfigType
        The configuration dictionary providing specific details for the platform such as
        unique ID, name, temperature entity ID, real thermostats, window sensor, and temperature
        tolerances.

    async_add_entities: AddEntitiesCallback
        A callback function to add entities to the platform.

    discovery_info: Optional
        Additional information that may be passed during platform discovery.

    Raises
    ------
    Exception
        If any error occurs during the setup of the FusionThermostat platform.
    """
    _LOGGER.debug("Setting up FusionThermostat platform")
    try:
        # Registriert den Reload-Service für diese Integration
        await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

        name = config.get(CONF_NAME)
        temperature_entity_id = config.get(CONF_TEMPERATURE_ENTITY_ID)
        real_thermostats = config.get(CONF_REAL_THERMOSTATS)
        windows_sensor = config.get(CONF_WINDOWS_SENSOR)
        min_temp = config.get(CONF_MIN_TEMP)
        max_temp = config.get(CONF_MAX_TEMP)
        cold_tolerance = config.get(CONF_COLD_TOLERANCE)
        hot_tolerance = config.get(CONF_HOT_TOLERANCE)
        window_delay = config.get(CONF_WINDOW_DELAY)

        async_add_entities([
            FusionThermostat(name, temperature_entity_id, real_thermostats, windows_sensor, window_delay, min_temp, max_temp, hot_tolerance, cold_tolerance)
        ])
        _LOGGER.info("FusionThermostat platform set up successfully")
    except Exception as e:
        _LOGGER.error("Error during setup: %s", e)
        raise

class FusionThermostat(ClimateEntity, RestoreEntity):
    def __init__(self, name, temperature_entity_id, real_thermostats, windows_sensor, window_delay, min_temp, max_temp, hot_tolerance, cold_tolerance):
        self._name = name
        self._unique_id = f"{self._name}_{DOMAIN}"
        self._temperature_unit = UnitOfTemperature.CELSIUS
        self._target_temperature = 20
        self._real_thermostats = real_thermostats
        self._windows_sensor = windows_sensor
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._hot_tolerance = hot_tolerance
        self._cold_tolerance = cold_tolerance
        self._local_temperature_calibration = 0.0
        self._hvac_mode = HVACMode.HEAT
        self._hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._hvac_action = HVACAction.HEATING
        self._supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TURN_ON |
            ClimateEntityFeature.TURN_OFF
        )
        self._current_temperature = 10
        self._temperature_entity_id = temperature_entity_id
        self._call_delay = 0.5
        self._window_delay = window_delay
        self._is_updating_real_thermostats = False
        self._cancel_call = None

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        # Add listener
        # External temperature sensor
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._temperature_entity_id], self._async_sensor_changed
            )
        )
        # Real thermostat
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._real_thermostats, self._async_thermostat_changed
            )
        )
        # Window contact
        if self._windows_sensor and len(self._windows_sensor) > 0:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._windows_sensor], self._async_windows_changed
                )
            )

        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state is not None:
            self._hvac_mode = last_state.state
            self._hvac_action = last_state.attributes.get("hvac_action", self._hvac_action)
            self._target_temperature = last_state.attributes.get("temperature", self._target_temperature)
            self._current_temperature = last_state.attributes.get("current_temperature", self._current_temperature)
            _LOGGER.debug("Restored state for %s: hvac_mode=%s, hvac_action=%s, target_temperature=%s, current_temperature=%s",
                          self.name, self._hvac_mode, self._hvac_action, self._target_temperature, self._current_temperature)

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        try:
            _LOGGER.debug("Attempting to set HVAC mode to %s for %s", hvac_mode, self.name)

            if self._hvac_modes is None:
                _LOGGER.error("HVAC modes are None for %s. Cannot set mode.", self.name)
                return

            if hvac_mode in self._hvac_modes:
                self._hvac_mode = hvac_mode
                _LOGGER.debug("HVAC mode successfully set to %s for %s", hvac_mode, self.name)
                if self._hvac_mode == HVACMode.OFF:
                    self._hvac_action = HVACAction.OFF
                    self.async_write_ha_state()
                elif self._hvac_mode == HVACMode.HEAT:
                    self._hvac_action = HVACAction.HEATING
                    self.async_write_ha_state()
                    await self._async_control_heating()
                for target in self._real_thermostats:
                    await self._async_real_thermostats_set_hvac_mode(hvac_mode=hvac_mode, entity_id=target, delay=self._call_delay)
            else:
                _LOGGER.warning(
                    "Invalid HVAC mode '%s' for %s. Supported modes are: %s",
                    hvac_mode, self.name, self._hvac_modes
                )
        except Exception as e:
            _LOGGER.error("Error setting HVAC mode for %s: %s", self.name, e, exc_info=True)

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        temp = kwargs.get('temperature')
        if temp is not None:
            self._target_temperature = temp
            _LOGGER.debug("Target temperature set to %s°C for %s", temp, self.name)
            if self._hvac_mode == HVACMode.HEAT:
                await self._async_control_heating()
            self.async_write_ha_state()
            for target in self._real_thermostats:
                await self._async_real_thermostats_set_temperature(temperature=temp, entity_id=target, delay=self._call_delay)
        else:
            _LOGGER.warning("No temperature provided to set for %s", self.name)

    async def _async_sensor_changed(self, event) -> None:
        """Handle temperature changes from the sensor."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (None, "unknown", "unavailable"):
            return

        try:
            self._current_temperature = float(new_state.state)
            _LOGGER.debug("Current temperature updated to %s°C from sensor %s", new_state.state, self._temperature_entity_id)
            if self._hvac_mode == HVACMode.HEAT:
                await self._async_control_heating()
            self.async_write_ha_state()
        except ValueError:
            _LOGGER.error("Failed to parse temperature from sensor %s: %s", self._temperature_entity_id, new_state.state)


    async def _async_windows_changed(self, event):
        """Handle window changes."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None or old_state is None or new_state.state == old_state.state:
            return

        # Fenster geschlossen (state: "off")
        if new_state.state == "off":
            _LOGGER.info("Fenster geschlossen erkannt.")
            if self._cancel_call:
                _LOGGER.info("Abbrechen der Verzögerung für das Ausschalten, da Fenster geschlossen wurde.")
                self._cancel_call()
                self._cancel_call = None
            else:
                _LOGGER.info("Starten der Verzögerung für das Einschalten der Heizung.")
                self._cancel_call = async_call_later(
                    self.hass, self._window_delay, self._async_set_hvac_mode_heat
                )

        # Fenster geöffnet (state: "on")
        elif new_state.state == "on":
            _LOGGER.info("Fenster geöffnet erkannt.")
            if self._cancel_call:
                _LOGGER.info("Abbrechen der Verzögerung für das Einschalten, da Fenster geöffnet wurde.")
                self._cancel_call()
                self._cancel_call = None
            else:
                _LOGGER.info("Starten der Verzögerung für das Ausschalten der Heizung.")
                self._cancel_call = async_call_later(
                    self.hass, self._window_delay, self._async_set_hvac_mode_off
                )

    async def _async_thermostat_changed(self, event) -> None:
        """Handle changes from real thermostats."""
        if self._is_updating_real_thermostats:  # Überspringe, wenn eine eigene Änderung läuft
            _LOGGER.debug("Skipping _async_thermostat_changed due to self-trigger.")
            return

        try:
            trigger_entity_id = event.data.get("entity_id")
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")

            if new_state is None or new_state.state in (None, "unknown", "unavailable") or old_state is None or old_state.state in (None, "unknown", "unavailable"):
                return

            # Check if target temperature changed
            new_target_temp = new_state.attributes.get("temperature")
            old_target_temp = old_state.attributes.get("temperature")
            if old_target_temp != new_target_temp:
                await self.async_set_temperature(temperature=new_target_temp)
                for entity_id in self._real_thermostats:
                    if entity_id != trigger_entity_id:
                        await self._async_real_thermostats_set_temperature(temperature=new_target_temp, entity_id=entity_id, delay=self._call_delay)

            # Check if HVAC mode changed
            new_hvac_mode = new_state.state
            old_hvac_mode = old_state.state
            if new_hvac_mode != old_hvac_mode:
                if new_hvac_mode in self._hvac_modes:
                    await self.async_set_hvac_mode(new_hvac_mode)
                    for entity_id in self._real_thermostats:
                        if entity_id != trigger_entity_id:
                            await self._async_real_thermostats_set_hvac_mode(hvac_mode=new_hvac_mode, entity_id=entity_id, delay=self._call_delay)
        except Exception as e:
            _LOGGER.error("Error in _async_thermostat_changed: %s", e, exc_info=True)

    async def _async_control_heating(self) -> None:
        current_temp = self._current_temperature
        target_temp = self._target_temperature

        if current_temp is None or target_temp is None:
            _LOGGER.error(
                "Cannot control heating: current temperature or target temperature is None. "
                "Current: %s, Target: %s", current_temp, target_temp
            )
            self._hvac_action = None
            return

        heating_demand = target_temp - current_temp

        if heating_demand == 0 and self._cold_tolerance == 0 and self._hot_tolerance == 0:
            await self._async_set_hvac_action_idle()
        # Heating
        elif current_temp <= target_temp - self._cold_tolerance:
            await self._async_set_hvac_action_heating()
            _LOGGER.info(
                "Heating required. Current temperature: %.1f°C, Target temperature: %.1f°C, "
                "Heating demand: %.1f°C (Cold tolerance: %.1f°C)",
                current_temp, target_temp, heating_demand, self._cold_tolerance
            )
        # Idle
        elif current_temp >= target_temp + self._hot_tolerance:
            await self._async_set_hvac_action_idle()
            _LOGGER.info(
                "No heating required. Current temperature: %.1f°C, Target temperature: %.1f°C, "
                "Heating demand: %.1f°C (Hot tolerance: %.1f°C)",
                current_temp, target_temp, heating_demand, self._hot_tolerance
            )
        else:
            _LOGGER.info(
                "Heating state unchanged. Current temperature: %.1f°C, Target temperature: %.1f°C, "
                "Heating demand: %.1f°C, Cold tolerance: %.1f°C, Hot tolerance: %.1f°C",
                current_temp, target_temp, heating_demand, self._cold_tolerance, self._hot_tolerance
            )

    async def _async_set_hvac_mode_heat(self, _):
        hvac_mode = HVACMode.HEAT
        self._hvac_mode = hvac_mode
        await self.async_set_hvac_mode(hvac_mode)
        self._cancel_call = None

    async def _async_set_hvac_mode_off(self, _):
        hvac_mode = HVACMode.OFF
        await self.async_set_hvac_mode(hvac_mode)
        self._cancel_call = None

    async def _async_set_hvac_action_heating(self):
        self._hvac_action = HVACAction.HEATING
        for target in self._real_thermostats:
            await self._async_real_thermostat_set_calibration(calibration_value=-5, entity_id=target, delay=self._call_delay)

    async def _async_set_hvac_action_off(self):
        self._hvac_action = HVACAction.OFF
        for target in self._real_thermostats:
            await self._async_real_thermostat_set_calibration(calibration_value=0, entity_id=target, delay=self._call_delay)

    async def _async_set_hvac_action_idle(self):
        self._hvac_action = HVACAction.IDLE
        for target in self._real_thermostats:
            await self._async_real_thermostat_set_calibration(calibration_value=5, entity_id=target, delay=self._call_delay)

    async def _async_real_thermostats_set_hvac_mode(self, hvac_mode, entity_id, delay) -> None:
        self._is_updating_real_thermostats = True
        try:
            if delay > 0:
                _LOGGER.debug(f"Verzögerung von {delay} Sekunden.")
                await asyncio.sleep(delay)
            await self.hass.services.async_call(
                "climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": hvac_mode},
            )
            _LOGGER.debug("HVAC mode set to %s for real Thermostat %s", hvac_mode, entity_id)
        finally:
            self._is_updating_real_thermostats = False

    async def _async_real_thermostats_set_temperature(self, temperature, entity_id, delay) -> None:
        self._is_updating_real_thermostats = True
        try:
            if delay > 0:
                _LOGGER.debug(f"Verzögerung von {delay} Sekunden.")
                await asyncio.sleep(delay)
            await self.hass.services.async_call(
                "climate", "set_temperature", {"entity_id": entity_id, "temperature": temperature},
            )
            _LOGGER.debug("Target temperature set to %s°C for real Thermostat %s", temperature, entity_id)
        finally:
            self._is_updating_real_thermostats = False

    async def _async_real_thermostat_set_calibration(self, calibration_value, entity_id, delay) -> None:
        if delay > 0:
            _LOGGER.debug(f"Verzögerung von {delay} Sekunden.")
            await asyncio.sleep(delay)
        calibration_entity_id = f"number.{entity_id.split(".")[1]}_local_temperature_calibration"
        self._local_temperature_calibration = calibration_value
        await self.hass.services.async_call(domain="number", service="set_value", service_data={"entity_id": calibration_entity_id,"value": calibration_value})
        _LOGGER.debug("Calibration value set to %s for real Thermostat %s", calibration_value, entity_id)

    @property
    def name(self):
        if self._name is None:
            _LOGGER.warning("Name property is None for FusionThermostat")
        return self._name

    @property
    def unique_id(self):
        if self._unique_id is None:
            _LOGGER.warning("Unique ID property is None for FusionThermostat")
        return self._unique_id

    @property
    def temperature_unit(self):
        return self._temperature_unit

    @property
    def hvac_mode(self):
        if self._hvac_mode is None:
            _LOGGER.warning("HVAC mode is None for %s", self.name)
        return self._hvac_mode

    @property
    def hvac_modes(self):
        return self._hvac_modes

    @property
    def hvac_action(self):
        return self._hvac_action

    @property
    def supported_features(self):
        return self._supported_features

    @property
    def min_temp(self):
        return self._min_temp

    @property
    def max_temp(self):
        return self._max_temp

    @property
    def current_temperature(self):
        if self._current_temperature is None:
            _LOGGER.warning("Current temperature is None for %s", self.name)
        return self._current_temperature

    @property
    def target_temperature(self):
        if self._target_temperature is None:
            _LOGGER.warning("Target temperature is None for %s", self.name)
        return self._target_temperature

    @property
    def extra_state_attributes(self):
        """Gibt zusätzliche Zustandsattribute zurück."""
        return {
            "local_temperature_calibration": self._local_temperature_calibration,
        }
