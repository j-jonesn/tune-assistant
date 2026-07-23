# P59 Tune Assistant

Configuration-driven tools for analyzing HP Tuners logs and managing calibration changes for a Gen III GM P59 ECM.

## Initial goals

- Maintain versioned vehicle, sensor, and safety configurations.
- Import HP Tuners CSV logs using configurable channel aliases.
- Calculate derived channels such as boost/vacuum, fueling error, fuel-pressure differential, injector duty cycle, and transmission slip.
- Analyze idle airflow, VE, fueling, spark, boost, and transmission behavior.
- Generate reports and VCM Editor-ready recommendations.
- Preserve the reason, evidence, and result for every tuning change.

## Project layout

```text
config/                 Vehicle, sensor, channel, and safety configuration
calibrations/           Calibration metadata and local file placeholders
logs/                    Raw and processed log placeholders
reports/                 Generated reports (ignored except for README)
src/tune_assistant/      Python package
  importers/             HP Tuners log ingestion
  calculations/          Derived channels
  analysis/              Tuning analysis modules
  recommendations/       Suggested calibration changes
  reporting/             Tables, charts, and reports
tests/                   Automated tests
tuning_history/          Versioned tuning change records
```

## Development status

Initial project scaffold.
