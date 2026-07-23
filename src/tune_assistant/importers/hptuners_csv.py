"""Import and normalize HP Tuners VCM Scanner CSV log exports."""

from __future__ import annotations

import argparse
import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

KPA_PER_PSI = 6.894757293168
STANDARD_ATMOSPHERIC_PRESSURE_KPA = 101.325


class HPTunersCSVError(ValueError):
    """Raised when an HP Tuners CSV export cannot be parsed safely."""


@dataclass(frozen=True)
class ChannelMetadata:
    """Description of one channel in the original HP Tuners export."""

    channel_id: str
    original_name: str
    original_unit: str
    normalized_name: str
    output_unit: str


@dataclass
class ImportDiagnostics:
    """Non-fatal channel-resolution findings."""

    missing_required_channels: list[str] = field(default_factory=list)
    duplicate_canonical_channels: dict[str, list[str]] = field(default_factory=dict)
    unmatched_channels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class HPTunersLog:
    """A normalized log plus the information needed to trace every column."""

    data: pd.DataFrame
    channels: list[ChannelMetadata]
    log_information: dict[str, str]
    diagnostics: ImportDiagnostics
    source: Path | None = None

    @property
    def units(self) -> dict[str, str]:
        """Return normalized column names mapped to their output units."""

        return {
            channel.normalized_name: channel.output_unit
            for channel in self.channels
        } | {"manifold_gauge_pressure_psi": "psi"}

    def save_csv(self, destination: str | Path) -> Path:
        """Write normalized channel data to a processed CSV file."""

        output_path = Path(destination)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.data.to_csv(output_path, index=False)
        return output_path


def _split_outside_brackets(line: str) -> list[str]:
    """Split a CSV-like line while preserving unquoted commas inside brackets.

    VCM Scanner may export user-math channel names such as
    ``AEM 30-(03x0,2340,5130)`` without quoting the embedded commas.
    """

    fields: list[str] = []
    current: list[str] = []
    bracket_depth = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())

    for character in line:
        if character in pairs:
            bracket_depth += 1
        elif character in closing and bracket_depth:
            bracket_depth -= 1

        if character == "," and bracket_depth == 0:
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(character)

    fields.append("".join(current).strip())
    return fields


def _normalized_key(value: str) -> str:
    value = re.sub(r"\s*\(SAE\)\s*$", "", value, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _slug(value: str) -> str:
    value = re.sub(r"\s*\(SAE\)\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or "unnamed_channel"


def load_channel_config(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load and validate the channel-alias configuration."""

    config_path = Path(path)
    with config_path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream) or {}

    channels = document.get("channels")
    if not isinstance(channels, dict):
        raise HPTunersCSVError(f"{config_path} does not contain a channels mapping")
    return channels


def _alias_lookup(
    channel_config: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], set[str]]:
    aliases: dict[str, str] = {}
    required: set[str] = set()

    for canonical_name, settings in channel_config.items():
        if not isinstance(settings, dict):
            raise HPTunersCSVError(
                f"Channel configuration for {canonical_name!r} must be a mapping"
            )
        if settings.get("required", False):
            required.add(canonical_name)
        names = [canonical_name, *settings.get("aliases", [])]
        for name in names:
            key = _normalized_key(str(name))
            existing = aliases.get(key)
            if existing and existing != canonical_name:
                raise HPTunersCSVError(
                    f"Alias {name!r} is assigned to both {existing!r} "
                    f"and {canonical_name!r}"
                )
            aliases[key] = canonical_name

    return aliases, required


def _parse_sections(text: str) -> tuple[
    dict[str, str], list[str], list[str], list[str], list[list[str]]
]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "HP Tuners CSV Log File":
        raise HPTunersCSVError("File is not an HP Tuners CSV Log File export")

    try:
        log_index = lines.index("[Log Information]")
        channel_index = lines.index("[Channel Information]")
        data_index = lines.index("[Channel Data]")
    except ValueError as error:
        raise HPTunersCSVError(f"Missing required section: {error}") from error

    if data_index <= channel_index + 3:
        raise HPTunersCSVError("Channel Information section is incomplete")

    log_information: dict[str, str] = {}
    for line in lines[log_index + 1 : channel_index]:
        if ":" in line:
            key, value = line.split(":", 1)
            log_information[key.strip()] = value.strip()

    channel_ids = next(csv.reader([lines[channel_index + 1]]))
    channel_names = _split_outside_brackets(lines[channel_index + 2])
    channel_units = next(csv.reader([lines[channel_index + 3]]))

    expected = len(channel_ids)
    counts = {
        "channel IDs": len(channel_ids),
        "channel names": len(channel_names),
        "channel units": len(channel_units),
    }
    if len(set(counts.values())) != 1:
        raise HPTunersCSVError(
            f"Channel Information column counts do not match: {counts}"
        )

    data_text = "\n".join(lines[data_index + 1 :])
    rows = list(csv.reader(io.StringIO(data_text)))
    rows = [row for row in rows if row and any(cell.strip() for cell in row)]
    invalid_rows = [
        data_index + 2 + index
        for index, row in enumerate(rows)
        if len(row) != expected
    ]
    if invalid_rows:
        preview = ", ".join(str(number) for number in invalid_rows[:5])
        raise HPTunersCSVError(
            f"Data rows do not contain {expected} fields; first invalid lines: {preview}"
        )

    return log_information, channel_ids, channel_names, channel_units, rows


def _convert_series(series: pd.Series) -> pd.Series:
    stripped = series.astype("string").str.strip()
    lowered = stripped.str.casefold()
    if lowered.dropna().isin({"yes", "no", "true", "false"}).all():
        return lowered.map({"yes": True, "true": True, "no": False, "false": False})

    numeric = pd.to_numeric(stripped, errors="coerce")
    nonempty = stripped.notna() & stripped.ne("")
    if numeric[nonempty].notna().all():
        return numeric
    return stripped


def _unit_key(unit: str) -> str:
    aliases = {
        "%": "percent",
        "°": "degrees",
        "°c": "degc",
        "°f": "degf",
        "lambda": "lambda",
        "λ": "lambda",
    }
    normalized = unit.strip().casefold().replace(" ", "")
    return aliases.get(normalized, normalized)


def _convert_unit(
    series: pd.Series,
    source_unit: str,
    target_unit: str,
) -> pd.Series | None:
    source = _unit_key(source_unit)
    target = _unit_key(target_unit)
    if not source or not target or source == target:
        return series
    if not pd.api.types.is_numeric_dtype(series):
        return None

    conversions = {
        ("lb/min", "g/s"): lambda values: values * 453.59237 / 60,
        ("g/s", "lb/min"): lambda values: values * 60 / 453.59237,
        ("kpa", "psi"): lambda values: values / KPA_PER_PSI,
        ("psi", "kpa"): lambda values: values * KPA_PER_PSI,
        ("degf", "degc"): lambda values: (values - 32) * 5 / 9,
        ("degc", "degf"): lambda values: values * 9 / 5 + 32,
    }
    converter = conversions.get((source, target))
    return converter(series) if converter else None


def import_hptuners_csv(
    source: str | Path,
    channel_config: str | Path | dict[str, dict[str, Any]],
    *,
    atmospheric_pressure_kpa: float = STANDARD_ATMOSPHERIC_PRESSURE_KPA,
) -> HPTunersLog:
    """Import an HP Tuners CSV export and return normalized channel data."""

    source_path = Path(source)
    text = source_path.read_text(encoding="utf-8-sig")
    (
        log_information,
        channel_ids,
        channel_names,
        channel_units,
        rows,
    ) = _parse_sections(text)

    config = (
        load_channel_config(channel_config)
        if isinstance(channel_config, (str, Path))
        else channel_config
    )
    alias_lookup, required_channels = _alias_lookup(config)

    diagnostics = ImportDiagnostics()
    normalized_names: list[str] = []
    canonical_sources: dict[str, list[str]] = {}
    used_names: dict[str, int] = {}

    for original_name in channel_names:
        canonical_name = alias_lookup.get(_normalized_key(original_name))
        if canonical_name:
            canonical_sources.setdefault(canonical_name, []).append(original_name)
            output_name = canonical_name
        else:
            diagnostics.unmatched_channels.append(original_name)
            output_name = _slug(original_name)

        used_names[output_name] = used_names.get(output_name, 0) + 1
        if used_names[output_name] > 1:
            output_name = f"{output_name}__{used_names[output_name]}"
        normalized_names.append(output_name)

    diagnostics.duplicate_canonical_channels = {
        name: sources
        for name, sources in canonical_sources.items()
        if len(sources) > 1
    }
    diagnostics.missing_required_channels = sorted(
        required_channels - canonical_sources.keys()
    )

    data = pd.DataFrame(rows, columns=normalized_names)
    for column in data.columns:
        data[column] = _convert_series(data[column])

    for original_unit, normalized_name in zip(
        channel_units, normalized_names, strict=True
    ):
        target_unit = str(config.get(normalized_name, {}).get("unit", original_unit))
        converted = _convert_unit(data[normalized_name], original_unit, target_unit)
        if converted is not None:
            data[normalized_name] = converted
        elif _unit_key(original_unit) != _unit_key(target_unit):
            diagnostics.warnings.append(
                f"No conversion is defined for {normalized_name}: "
                f"{original_unit or '(unitless)'} to {target_unit or '(unitless)'}."
            )

    if "map_kpa" in data.columns:
        if "barometric_pressure_kpa" in data.columns:
            reference_pressure = data["barometric_pressure_kpa"]
        else:
            reference_pressure = atmospheric_pressure_kpa
            diagnostics.warnings.append(
                "Barometric pressure channel is absent; "
                f"manifold gauge pressure uses {atmospheric_pressure_kpa:g} kPa."
            )
        data["manifold_gauge_pressure_psi"] = (
            data["map_kpa"] - reference_pressure
        ) / KPA_PER_PSI

    channels: list[ChannelMetadata] = []
    for channel_id, original_name, original_unit, normalized_name in zip(
        channel_ids, channel_names, channel_units, normalized_names, strict=True
    ):
        canonical_settings = config.get(normalized_name, {})
        channels.append(
            ChannelMetadata(
                channel_id=channel_id,
                original_name=original_name,
                original_unit=original_unit,
                normalized_name=normalized_name,
                output_unit=str(canonical_settings.get("unit", original_unit)),
            )
        )

    return HPTunersLog(
        data=data,
        channels=channels,
        log_information=log_information,
        diagnostics=diagnostics,
        source=source_path,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize an HP Tuners VCM Scanner CSV export."
    )
    parser.add_argument("source", type=Path, help="Raw HP Tuners CSV log")
    parser.add_argument(
        "--channels",
        type=Path,
        default=Path("config/channels.yaml"),
        help="Channel alias configuration",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Processed CSV destination; defaults to logs/processed/<name>.csv",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    output = args.output or Path("logs/processed") / f"{args.source.stem}.normalized.csv"
    log = import_hptuners_csv(args.source, args.channels)
    log.save_csv(output)

    print(f"Imported {len(log.data):,} rows and {len(log.channels)} channels")
    print(f"Saved {output}")
    if log.diagnostics.missing_required_channels:
        print(
            "Missing required channels: "
            + ", ".join(log.diagnostics.missing_required_channels)
        )
    for warning in log.diagnostics.warnings:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
