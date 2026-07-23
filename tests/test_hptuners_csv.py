from pathlib import Path

import pandas as pd
import pytest

from tune_assistant.importers.hptuners_csv import (
    HPTunersCSVError,
    import_hptuners_csv,
)


CONFIG = {
    "time_s": {"aliases": ["Offset"], "unit": "s", "required": True},
    "engine_speed_rpm": {
        "aliases": ["Engine RPM", "Engine RPM (SAE)"],
        "unit": "rpm",
        "required": True,
    },
    "map_kpa": {
        "aliases": ["Manifold Absolute Pressure - 2 bar"],
        "unit": "kPa",
        "required": True,
    },
    "wideband_lambda": {
        "aliases": ["MPVI2.1 -> AEM 30-(03x0,2340,5130)"],
        "unit": "lambda",
    },
    "closed_loop_active": {
        "aliases": ["Closed Loop Active"],
        "unit": "boolean",
    },
}


def _write_log(path: Path, rows: str) -> Path:
    path.write_text(
        "HP Tuners CSV Log File\n"
        "Version: 1.0\n"
        "\n"
        "[Log Information]\n"
        "Creation Time: 7/22/2026 11:00:13 PM\n"
        "Notes: fixture\n"
        "\n"
        "[Channel Information]\n"
        "0,12,2333,12942,40101\n"
        "Offset,Engine RPM (SAE),Manifold Absolute Pressure - 2 bar,"
        "Closed Loop Active,MPVI2.1 -> AEM 30-(03x0,2340,5130)\n"
        "s,rpm,kPa,,lambda\n"
        "\n"
        "[Channel Data]\n"
        f"{rows}",
        encoding="utf-8",
    )
    return path


def test_imports_real_export_shape_and_calculates_gauge_pressure(
    tmp_path: Path,
) -> None:
    source = _write_log(
        tmp_path / "idle.csv",
        "1.289,763.25,73.61328125,Yes,1.0357132272\n"
        "2.000,780,110.0,No,0.990\n",
    )

    log = import_hptuners_csv(source, CONFIG)

    assert list(log.data.columns) == [
        "time_s",
        "engine_speed_rpm",
        "map_kpa",
        "closed_loop_active",
        "wideband_lambda",
        "manifold_gauge_pressure_psi",
    ]
    assert len(log.channels) == 5
    assert log.channels[-1].original_name == "MPVI2.1 -> AEM 30-(03x0,2340,5130)"
    assert log.data["closed_loop_active"].tolist() == [True, False]
    assert log.data.loc[0, "manifold_gauge_pressure_psi"] == pytest.approx(-4.02, abs=0.02)
    assert log.data.loc[1, "manifold_gauge_pressure_psi"] == pytest.approx(1.258, abs=0.002)
    assert log.diagnostics.missing_required_channels == []
    assert "Barometric pressure channel is absent" in log.diagnostics.warnings[0]


def test_reports_missing_required_and_unmatched_channels(tmp_path: Path) -> None:
    source = _write_log(
        tmp_path / "idle.csv",
        "1.289,763.25,73.61328125,Yes,1.0357132272\n",
    )
    config = {
        **CONFIG,
        "fuel_pressure_psi": {
            "aliases": ["Fuel Pressure"],
            "unit": "psi",
            "required": True,
        },
    }

    log = import_hptuners_csv(source, config)

    assert log.diagnostics.missing_required_channels == ["fuel_pressure_psi"]
    assert log.diagnostics.unmatched_channels == []


def test_rejects_misaligned_data_row(tmp_path: Path) -> None:
    source = _write_log(tmp_path / "bad.csv", "1.289,763.25,73.61328125,Yes\n")

    with pytest.raises(HPTunersCSVError, match="Data rows do not contain 5 fields"):
        import_hptuners_csv(source, CONFIG)


def test_saves_normalized_csv(tmp_path: Path) -> None:
    source = _write_log(
        tmp_path / "idle.csv",
        "1.289,763.25,73.61328125,Yes,1.0357132272\n",
    )
    log = import_hptuners_csv(source, CONFIG)

    destination = log.save_csv(tmp_path / "processed" / "idle.normalized.csv")

    saved = pd.read_csv(destination)
    assert destination.exists()
    assert list(saved.columns) == list(log.data.columns)
