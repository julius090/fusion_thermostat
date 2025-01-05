# Fusion Thermostat

## Beschreibung
**Fusion Thermostat** ist eine benutzerdefinierte Home-Assistant-Integration zur Steuerung smarter Thermostate. Sie kombiniert externe Temperatursensoren, berücksichtigt Fenstersensoren und steuert reale Thermostate synchron.

## Features
- **Mehrere reale Thermostate**: Synchronisierte Steuerung mehrerer Geräte.
- **Fenstersensor-Unterstützung**: Heizungsabschaltung bei geöffnetem Fenster mit konfigurierbarer Verzögerung.
- **Temperaturtoleranzen**: Präzise Regelung durch **hot/cold tolerance**.
  
## Installation

1. **HACS hinzufügen**:  
   HACS → Benutzerdefinierte Repositories:  
   `https://github.com/julius090/fusion_thermostat`.

2. **Integration installieren**.

3. **Neustart** von Home Assistant.

---

## Konfiguration

```yaml
climate:
  - platform: fusion_thermostat
    name: "Wohnzimmer Thermostat"
    target_sensor: sensor.temperature_wohnzimmer   # Pflicht: Externer Temperatursensor
    real_thermostats:                             # Pflicht: Reale Thermostate
      - climate.real_thermostat_1
      - climate.real_thermostat_2
    windows_sensor: binary_sensor.fenster_wohnzimmer  # Optional: Fenstersensor, der das Öffnen und Schließen des Fensters überwacht
    min_temp: 10                                      # Optional: Thermostat-Minimaltemperatur
    max_temp: 25                                      # Optional: Thermostat-Maximaltemperatur
    hot_tolerance: 0.5                                # Optional: Obere Schaltschwelle
    cold_tolerance: 0.5                               # Optional: Untere Schaltschwelle
    calibration_value: 5                              # Optional: Kalibrierwert für den Temperatursensor des realen Thermostats
    window_delay: 10                                  # Optional: Verzögerung in Sekunden nach dem Öffnen des Fensters, bevor der Thermostat die Heizung abschaltet
    test_server: false                                # Optional: Gibt an, ob ein Testserver verwendet wird (true) oder nicht (false)