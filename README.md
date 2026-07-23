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

## HP Tuners CSV importer

The importer reads the complete VCM Scanner CSV export instead of treating it as a conventional one-row-header CSV. It:

- reads log metadata, channel IDs, original channel names, and units;
- handles unquoted commas inside HP Tuners user-math channel names;
- resolves channels through `config/channels.yaml`;
- reports missing, duplicate, and unmatched channels;
- converts configured units, including airflow from lb/min to g/s;
- converts Yes/No channels to booleans;
- creates `manifold_gauge_pressure_psi`, where vacuum is negative and boost is positive; and
- writes a normalized CSV suitable for later analysis modules.

Import a log from the repository root:

```bash
python -m tune_assistant.importers.hptuners_csv \
  "logs/raw/3nd Idle In GEAR.csv"
```

The default output is:

```text
logs/processed/3nd Idle In GEAR.normalized.csv
```

Specify a different destination when needed:

```bash
python -m tune_assistant.importers.hptuners_csv \
  "logs/raw/3nd Idle In GEAR.csv" \
  --output "logs/processed/idle-in-gear.csv"
```

When a BARO channel is logged, gauge pressure uses it as the reference. Otherwise, it uses standard atmospheric pressure of 101.325 kPa and adds a diagnostic warning.

## Development

Install the project with test tools:

```bash
python -m pip install -e ".[dev]"
```

Run the tests:

```bash
pytest
```

## Development status

The initial scaffold and HP Tuners CSV importer are complete. The next module will analyze idle airflow and RPM stability from normalized logs.
