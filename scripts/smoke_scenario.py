"""Current-time HA lamp scenario with a Pipeline-authorized bounded restoration."""

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from hirz.adapters.devices.ha import HomeAssistant, load_config
from hirz.graph.models import now
from hirz.twin.scenario import LoadedScenario, run_scenario
from scripts.smoke_ha import inputs


async def live(folder: Path) -> None:
    config_path = Path("config/homeassistant/adapter-demo.yaml").resolve()
    config = load_config(config_path)
    home, assets, bindings, _ = inputs(config)
    adapter = HomeAssistant(home, config=config, assets=assets, bindings=bindings)
    await adapter.start()
    try:
        original = (await adapter.get_state("light.bed_light")).state.on
        if original is None:
            raise ValueError(
                "Original lamp state is unknown; restoration cannot be verified"
            )
        at = now().astimezone(ZoneInfo("America/Chicago"))
        opening = (at + timedelta(minutes=1)).replace(second=0, microsecond=0)
        end = opening + timedelta(minutes=1)
        raw = yaml.safe_load(Path("scenarios/demo-evening.yaml").read_text())
        base = raw["clock"]["start"]
        from datetime import datetime

        shift = at - datetime.fromisoformat(base)

        def dates(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: dates(v) for k, v in value.items()}
            if isinstance(value, list):
                return [dates(v) for v in value]
            if isinstance(value, str) and value.startswith(
                ("2026-10-13T", "2026-10-14T")
            ):
                return (datetime.fromisoformat(value) + shift).isoformat()
            return value

        raw = dates(raw)
        raw.update(
            id="ha-lamp-smoke",
            household=str(Path("constitutions/quinn-home.yaml").resolve()),
            rate_plan="twin",
            clock=dict(start=at.isoformat(), end=end.isoformat(), speed=1),
            execution=dict(member="malik", rooms={"light.living_room": "other"}),
            bindings={
                "light.living_room": {"adapter": "ha", "entity": "light.bed_light"}
            },
        )
        raw["adapters"]["energy"] = "twin"
        raw["timeline"] = [
            dict(
                at=opening.strftime("%H:%M"),
                event="voice",
                member="malik",
                text="Toggle the demo lamp briefly and restore it.",
                script=[
                    dict(
                        tool="execute_household_action",
                        arguments={
                            "asset": "light.living_room",
                            "on": not original,
                            "duration_s": 2,
                        },
                    )
                ],
            )
        ]
        raw["assert"] = dict(
            checks=[
                dict(
                    at=end.strftime("%H:%M"),
                    kind="observation",
                    domain="devices",
                    subject="light.living_room",
                    equals={"on": original},
                )
            ],
            deferred=[],
            audit_sequence_includes=[
                "VERIFIED:environment.lights",
                "VERIFIED:environment.lights",
            ],
        )
        with TemporaryDirectory() as temp:
            ha_path = Path(temp) / "ha.yaml"
            ha_raw = config.model_dump(mode="json")
            ha_raw["entities"] = {
                "light.bed_light": ha_raw["entities"]["light.bed_light"]
            }
            ha_path.write_text(yaml.safe_dump(ha_raw))
            path = Path(temp) / "lamp.yaml"
            path.write_text(yaml.safe_dump(raw))
            loaded = LoadedScenario(path)
            report = await run_scenario(
                loaded, assertions=True, artifacts_dir=folder, ha_config=ha_path
            )
        restored = (await adapter.get_state("light.bed_light")).state.on == original
        print(
            json.dumps(
                dict(
                    status=report["status"],
                    restored=restored,
                    source="real API, demo devices",
                    artifacts_dir=str(folder),
                    error=report.get("error"),
                    unsuccessful_checks=[
                        check
                        for check in report["checks"]
                        if check["status"] in {"failed", "not_reached"}
                    ],
                )
            )
        )
        if report["status"] != "execution_checks_passed" or not restored:
            raise ValueError(
                "HA lamp scenario or restoration failed; retained evidence requires review"
            )
    finally:
        await adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-demo", action="store_true", required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(live(args.artifacts_dir))


if __name__ == "__main__":
    main()
