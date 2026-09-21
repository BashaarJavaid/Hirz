"""Offline replay; --fetch explicitly archives public inputs before replay."""

import argparse
import asyncio
import csv
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, cast

import numpy as np

from hirz.adapters.energy.real import feeds
from hirz.adapters.energy.real.tariff import CHICAGO, load_tariff
from hirz.pipeline.hashing import digest
from hirz.planner.heuristic import baseline
from hirz.planner.history import (
    END,
    START,
    counterfactual_rate,
    fetch_archive,
    hourly,
    persistence,
    read_raw,
)
from hirz.planner.models import Replay, Slot, boundaries
from hirz.planner.replay import replay
from hirz.planner.service import compare, peak
from hirz.planner.solver import solve
from hirz.planner.workload import CONFIGURATIONS, Configuration, workload
from hirz.twin.environment import Solar
from hirz.twin.physics import changed

ROOT = Path("scripts/backtest-data")
STRATEGIES = ("milp", "timer", "immediate", "greedy")


def load_history(
    root: Path,
) -> tuple[dict[datetime, float | None], dict[datetime, Any]]:
    quotes: dict[datetime, Decimal | None] = {}
    for path in sorted(root.glob("realtime-*.json.gz")):
        for at, value in feeds.realtime(read_raw(root, path.name)).items():
            feeds.put(quotes, at, value)
    return hourly(quotes), feeds.weather(read_raw(root, "weather.json.gz"))


def inputs(
    day: date,
    profile: str,
    configuration: Configuration,
    prices: dict[datetime, float | None],
    weather: dict[datetime, Any],
) -> tuple[tuple[Slot, ...], tuple[Slot, ...], tuple[float | None, ...]]:
    tariff = load_tariff(Path("tariffs/comed-time-of-day.yaml"))
    start = (
        datetime.combine(day, datetime.min.time(), CHICAGO)
        .replace(hour=17, minute=30)
        .astimezone(UTC)
    )
    edges = boundaries(start)
    solar = Solar(tilt_degrees=30, orientation_degrees=180)
    forecast: list[Slot] = []
    realized: list[Slot] = []
    supply: list[float | None] = []
    for left, right in zip(edges, edges[1:]):
        hour = left.replace(minute=0)
        predicted_weather, weather_source = persistence(weather, hour, start)
        actual_weather = weather.get(hour)
        if actual_weather is None:
            raise ValueError(f"Missing realized weather at {hour.isoformat()}")
        price_source = None
        if profile == "comed_hourly":
            predicted, price_source = persistence(prices, hour, start)
            forecast_price = counterfactual_rate(tariff, left, hourly_supply=predicted)
            realized_price = (
                None
                if prices.get(hour) is None
                else counterfactual_rate(tariff, left, hourly_supply=prices[hour])
            )
        else:
            forecast_price = realized_price = counterfactual_rate(tariff, left)
        supply.append(prices.get(hour) if profile == "comed_hourly" else None)
        for collection, w, price in (
            (forecast, predicted_weather, forecast_price),
            (realized, actual_weather, realized_price),
        ):
            collection.append(
                Slot(
                    start=left,
                    end=right,
                    price=0 if price is None else price,
                    outdoor_f=w.temp_f,
                    solar_kw=0
                    if configuration == "ev_only"
                    else solar.kw_peak
                    * solar.irradiance(left, 41.88, -87.63, w.cloud_cover_percent),
                    price_source=price_source if collection is forecast else None,
                    weather_source=weather_source if collection is forecast else None,
                )
            )
    return tuple(forecast), tuple(realized), tuple(supply)


def metrics(rows: list[dict[str, Any]], total: int) -> dict[str, Any]:
    eligible = [r for r in rows if r.get("savings", {}).get("timer") is not None]
    values = [r["savings"]["timer"] for r in eligible]

    def quantiles(values: list[float]) -> list[float | None]:
        return (
            [float(v) for v in np.quantile(values, [0.1, 0.5, 0.9], method="linear")]
            if values
            else [None] * 3
        )

    worst = max(
        eligible,
        key=lambda r: (
            r["strategies"]["timer"]["electricity_usd"]
            + r["strategies"]["timer"]["wear_usd"]
        ),
        default=None,
    )
    return {
        "eligible_days": len(eligible),
        "total_days": total,
        "coverage": len(eligible) / total,
        "net_savings_p10_median_p90": quantiles(values),
        "immediate_p10_median_p90": quantiles(
            [
                r["savings"]["immediate"]
                for r in rows
                if r.get("savings", {}).get("immediate") is not None
            ]
        ),
        "greedy_p10_median_p90": quantiles(
            [
                r["savings"]["greedy"]
                for r in rows
                if r.get("savings", {}).get("greedy") is not None
            ]
        ),
        "observed_net_savings": sum(values) if values else None,
        "annualized_extrapolation_usd": float(np.mean(values)) * 365
        if values
        else None,
        "near_zero_days": sum(abs(v) <= 0.10 for v in values),
        "worst_timer_day": None if worst is None else worst["date"],
        "worst_spike_night_saving": None
        if worst is None
        else worst["savings"]["timer"],
        "peak_kwh_avoided": sum(r["peak_kwh_avoided"] for r in eligible),
        "negative_supply_charging_hours": sum(
            r.get("negative_supply_charging_hours", 0) for r in eligible
        ),
        "negative_supply_distribution_charging_hours": sum(
            r.get("negative_total_charging_hours", 0) for r in eligible
        ),
        "observed_electricity_usd": {
            s: sum(
                r["strategies"][s]["electricity_usd"]
                for r in eligible
                if s in r["strategies"]
                and r["strategies"][s]["electricity_usd"] is not None
            )
            for s in STRATEGIES
        },
        "observed_wear_usd": {
            s: sum(
                r["strategies"][s]["wear_usd"] for r in eligible if s in r["strategies"]
            )
            for s in STRATEGIES
        },
        "observed_losses_kwh": {
            strategy: {
                field: sum(
                    r["strategies"][strategy][field]
                    for r in eligible
                    if strategy in r["strategies"]
                )
                for field in ("ev_loss_kwh", "battery_loss_kwh")
            }
            for strategy in STRATEGIES
        },
        "exported_kwh": {
            strategy: sum(
                sum(r["strategies"][strategy]["export_kwh"])
                for r in eligible
                if strategy in r["strategies"]
            )
            for strategy in STRATEGIES
        },
        "bias": "Eligible-day mean × 365 is extrapolation, not a full-year bill; missing or infeasible days may bias the mean.",
    }


def run(
    profile: str,
    configuration: Configuration,
    wear: float,
    prices: dict[datetime, float | None],
    weather: dict[datetime, Any],
    start: date,
    end: date,
) -> dict[str, Any]:
    states: dict[str, Replay] = {}
    stopped: dict[str, Any] = {}
    rows = []
    day = start
    while day < end:
        row: dict[str, Any] = {"date": day.isoformat(), "strategies": {}, "savings": {}}
        try:
            forecast, actual, supply = inputs(
                day, profile, configuration, prices, weather
            )
        except ValueError as exc:
            stopped["inputs"] = {
                "date": day.isoformat(),
                "reason": str(exc),
                "states": {s: r.model_dump(mode="json") for s, r in states.items()},
            }
            break
        billing_complete = profile != "comed_hourly" or all(
            p is not None for p in supply
        )
        row["billing_complete"] = billing_complete
        row["forecast_sources"] = [
            {
                "price": s.price_source.isoformat() if s.price_source else None,
                "weather": s.weather_source.isoformat() if s.weather_source else None,
            }
            for s in forecast
        ]
        day_results = {}
        for strategy in STRATEGIES:
            if strategy in stopped:
                continue
            state = states.get(strategy)
            kwargs: dict[str, Any] = {}
            if state:
                ev = None if state.ev is None else state.ev
                if ev:
                    ev = changed(ev, plugged_in=True)
                kwargs = dict(
                    ev=ev,
                    battery=state.battery,
                    zones=state.zones,
                    appliance=state.appliance,
                )
            p = workload(forecast, configuration, wear=wear, **kwargs)
            diagnostic = None
            if strategy == "milp":
                schedule, diagnostic = solve(p)
                if schedule is None and diagnostic.status == "timeout":
                    schedule = baseline(p)
            else:
                schedule = baseline(
                    p, cast(Literal["timer", "immediate", "greedy"], strategy)
                )
            check = replay(p, schedule) if schedule is not None else None
            if check is None or not check.valid:
                stopped[strategy] = {
                    "date": day.isoformat(),
                    "stage": "forecast",
                    "input": p.model_dump(mode="json"),
                    "diagnostics": None
                    if diagnostic is None
                    else diagnostic.model_dump(),
                    "replay": None if check is None else check.model_dump(mode="json"),
                }
                continue
            assert schedule is not None
            realized_p = p.model_copy(update={"slots": actual})
            result = replay(realized_p, schedule)
            if result.ev is not None:
                # No charging is allowed after 08:00; this drive is at that departure.
                result = result.model_copy(
                    update={
                        "ev": changed(
                            result.ev, plugged_in=False, charging=False
                        ).drive(12)
                    }
                )
            states[strategy] = result
            row["strategies"][strategy] = result.model_dump(
                mode="json", exclude={"ev", "battery", "zones", "appliance"}
            )
            row["strategies"][strategy]["schedule_hash"] = digest(
                schedule.model_dump(mode="json")
            )
            if not billing_complete:
                row["strategies"][strategy]["electricity_usd"] = None
            if diagnostic:
                row["solver"] = diagnostic.model_dump()
            if not result.valid:
                stopped[strategy] = {
                    "date": day.isoformat(),
                    "stage": "realized",
                    "input": p.model_dump(mode="json"),
                    "schedule": schedule.model_dump(mode="json"),
                    "replay": result.model_dump(mode="json"),
                }
            else:
                day_results[strategy] = result
                if strategy == "milp":
                    row["negative_supply_charging_hours"] = sum(
                        c.ev_kwh / p.ev.charger_kw
                        for c, s in zip(schedule.controls, supply, strict=True)
                        if p.ev and s is not None and s < 0
                    )
                    row["negative_total_charging_hours"] = sum(
                        c.ev_kwh / p.ev.charger_kw
                        for c, s in zip(schedule.controls, actual, strict=True)
                        if p.ev and s.price < 0
                    )
        optimized = day_results.get("milp")
        for strategy in STRATEGIES[1:]:
            other = day_results.get(strategy)
            row["savings"][strategy] = (
                compare(optimized, other)[1]
                if optimized and other and billing_complete
                else None
            )
        row["peak_kwh_avoided"] = (
            peak(realized_p, day_results["timer"]) - peak(realized_p, optimized)
            if optimized and "timer" in day_results
            else None
        )
        row["comparison_exclusions"] = (
            [] if billing_complete else ["Incomplete realized billing hour"]
        ) + [
            f"{strategy} unavailable or failed replay"
            for strategy in STRATEGIES
            if strategy not in day_results
        ]
        rows.append(row)
        if all(s in stopped for s in STRATEGIES):
            break
        day += timedelta(days=1)
    return {
        "profile": profile,
        "household": configuration,
        "wear_per_internal_kwh": wear,
        "metrics": metrics(rows, (end - start).days),
        "days": rows,
        "stopped": stopped,
        "final_states": {s: r.model_dump(mode="json") for s, r in states.items()},
    }


def publish(report: dict[str, Any], root: Path) -> None:
    (root / "results.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    with (root / "daily.csv").open("w") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "profile",
                "household",
                "wear",
                "date",
                "billing_complete",
                "saving_timer",
                "saving_immediate",
                "saving_greedy",
            ]
        )
        for run in report["runs"]:
            for row in run["days"]:
                writer.writerow(
                    [
                        run["profile"],
                        run["household"],
                        run["wear_per_internal_kwh"],
                        row["date"],
                        row["billing_complete"],
                        *[row["savings"].get(s) for s in STRATEGIES[1:]],
                    ]
                )
    lines = [
        "| Rate | Household | Net saving vs timer: median (p10–p90) | vs immediate: median | vs greedy: median | Annualized extrapolation | Eligible/total |",
        "|---|---|---|---|---|---|---|",
    ]

    def dollars(value: float | None) -> str:
        return "unavailable" if value is None else f"${value:.2f}"

    for run in report["runs"]:
        if run["wear_per_internal_kwh"] != 0.01:
            continue
        m = run["metrics"]
        q = m["net_savings_p10_median_p90"]
        rate_label = (
            "Time-of-Day" if run["profile"] == "comed_time_of_day" else "Hourly"
        )
        home_label = {
            "solar_battery_ev": "solar + battery + EV",
            "ev_only": "EV only",
            "solar_battery": "solar + battery, no EV",
        }[run["household"]]
        lines.append(
            f"| {rate_label} | {home_label} | {dollars(q[1])} ({dollars(q[0])}–{dollars(q[2])}) | {dollars(m['immediate_p10_median_p90'][1])} | {dollars(m['greedy_p10_median_p90'][1])} | {dollars(m['annualized_extrapolation_usd'])} | {m['eligible_days']}/{m['total_days']} |"
        )
    (root / "readme-table.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Reproduce retained outputs offline, ignoring timing measurements",
    )
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.fetch and args.verify:
        parser.error("--verify is offline; do not combine it with --fetch")
    previous = (
        json.loads((args.output / "results.json").read_text()) if args.verify else None
    )
    if args.fetch:
        asyncio.run(fetch_archive(ROOT / "raw", args.start, args.end))
    began = perf_counter()
    prices, weather = load_history(ROOT / "raw")
    tariff = load_tariff(Path("tariffs/comed-time-of-day.yaml"))
    report: dict[str, Any] = {
        "start": str(args.start),
        "end": str(args.end),
        "timezone": "America/Chicago",
        "label": "Pinned 2026 tariff counterfactual; simulated devices; feed-based hourly cost estimates; persistence forecast",
        "exclusions": tariff.exclusions,
        "archive_manifest_hash": digest(
            json.loads((ROOT / "raw/manifest.json").read_text())
        ),
        "runs": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    templates = {}
    for configuration in CONFIGURATIONS:
        forecast, _, _ = inputs(
            args.start, "comed_time_of_day", configuration, prices, weather
        )
        templates[configuration] = workload(forecast, configuration).model_dump(
            mode="json", exclude={"slots"}
        )
    config = {
        "templates": templates,
        "ev_drive_kwh_at_0800": 12,
        "ev_unplugged_until": "17:30",
        "forecast": "nearest matching Chicago hour in preceding seven days, ended at least 24h before decision",
        "wear_sensitivity": [0, 0.01, 0.02],
        "export_credit_usd_per_kwh": 0,
        "battery_baseline": "self-consumption; restore opening SoC 21:00–06:00; surplus limited to remaining forecast self-consumption to satisfy terminal equality",
    }
    if not args.verify:
        (args.output / "workload.json").write_text(json.dumps(config, indent=2) + "\n")
    report["workload_hash"] = digest(config)
    for wear in (0.01, 0, 0.02):
        for profile in ("comed_time_of_day", "comed_hourly"):
            for configuration in CONFIGURATIONS:
                result = run(
                    profile, configuration, wear, prices, weather, args.start, args.end
                )
                report["runs"].append(result)
                if not args.verify:
                    publish(report, args.output)
                print(
                    json.dumps(
                        {
                            "profile": profile,
                            "configuration": configuration,
                            "wear": wear,
                            "coverage": result["metrics"]["coverage"],
                            "stopped": list(result["stopped"]),
                        }
                    ),
                    flush=True,
                )
    report["elapsed_seconds"] = perf_counter() - began
    if not args.verify:
        publish(report, args.output)
    if previous is not None:

        def stable(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    k: stable(v) for k, v in value.items() if k != "elapsed_seconds"
                }
            if isinstance(value, (list, tuple)):
                return [stable(v) for v in value]
            return value

        matched = stable(previous) == stable(report)
        print(json.dumps({"offline_reproduction_matches": matched}))
        return 0 if matched else 1
    return (
        0
        if all(
            r["metrics"]["eligible_days"] == r["metrics"]["total_days"]
            for r in report["runs"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
