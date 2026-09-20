"""Local Home Assistant reads and single-attempt, pipeline-authorized writes."""

import asyncio
import json
import math
import re
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import yaml
from pydantic import Field, field_validator
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from hirz.adapters.base import AdapterError, AdapterUnavailable
from hirz.adapters.registry import Factory, Key
from hirz.graph.models import (
    Asset,
    AssetBinding,
    Household,
    Model,
    Observation,
    ObservationState,
    now,
    utc,
)
from hirz.graph.seeds import UniqueLoader
from hirz.local import LocalError, read_env
from hirz.pipeline.hashing import ingest
from hirz.pipeline.models import Action, Decision, EventType
from hirz.pipeline.service import Pipeline

UNAVAILABLE = "Home Assistant unavailable; actual state unknown."


class EntityConfig(Model):
    source: Literal["real", "real API, demo devices"]
    power_sensor: str | None = None

    @field_validator("power_sensor")
    @classmethod
    def sensor(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"sensor\.[a-z0-9_]+", value):
            raise ValueError("Invalid power sensor")
        return value


class HAConfig(Model):
    url: str
    entities: dict[str, EntityConfig] = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def endpoint(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("HA requires an origin URL without credentials")
        _ = url.port
        return value.rstrip("/")

    @field_validator("entities")
    @classmethod
    def controls(cls, value: dict[str, EntityConfig]) -> dict[str, EntityConfig]:
        if any(
            not re.fullmatch(r"(?:climate|light|switch)\.[a-z0-9_]+", e) for e in value
        ):
            raise ValueError("Unsupported HA control entity")
        return value


def load_config(path: Path) -> HAConfig:
    try:
        return HAConfig.model_validate(yaml.load(path.read_text(), Loader=UniqueLoader))
    except (OSError, ValueError, yaml.YAMLError):
        raise AdapterError("Invalid non-secret Home Assistant configuration.") from None


def numeric(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise AdapterError("Invalid Home Assistant numeric value.")
    return float(value)


def fahrenheit(value: Any, unit: Any) -> float:
    result = numeric(value)
    if unit == "°C":
        return result * 9 / 5 + 32
    if unit != "°F":
        raise AdapterError("Unsupported Home Assistant temperature unit.")
    return result


class HomeAssistant:
    def __init__(
        self,
        household: Household,
        *,
        config: HAConfig,
        assets: tuple[Asset, ...],
        bindings: tuple[AssetBinding, ...],
        pipeline: Pipeline | None = None,
        env_path: Path = Path(".env"),
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.household_id = household.id
        self.config = HAConfig.model_validate(config.model_dump())
        self.pipeline, self.env_path, self.transport = pipeline, env_path, transport
        self.assets = {a.id: Asset.model_validate(a.model_dump()) for a in assets}
        self.bindings = {
            b.entity_id: AssetBinding.model_validate(b.model_dump())
            for b in bindings
            if b.adapter == "ha"
        }
        if (
            len(self.assets) != len(assets)
            or len(self.bindings) != sum(b.adapter == "ha" for b in bindings)
            or len({b.asset_id for b in self.bindings.values()}) != len(self.bindings)
            or set(self.bindings) != set(self.config.entities)
            or any(a.household_id != self.household_id for a in self.assets.values())
            or any(b.household_id != self.household_id for b in bindings)
            or pipeline is not None
            and pipeline.household_id != self.household_id
        ):
            raise AdapterError("Invalid Home Assistant household bindings.")
        for entity, binding in self.bindings.items():
            asset = self.assets.get(binding.asset_id)
            if asset is None or asset.kind != (
                "hvac_zone" if entity.startswith("climate.") else "light"
            ):
                raise AdapterError("Unsupported Home Assistant asset binding.")
        self.client: httpx.AsyncClient | None = None
        self.socket: ClientConnection | None = None
        self.subscribing = False
        self.subscription_ready = asyncio.Event()
        self._token = ""
        self.capabilities = frozenset({"list_entities", "get_state", "subscribe"})
        if pipeline is not None:
            self.capabilities |= {"set_light", "set_climate"}

    async def start(self) -> None:
        if self.client is not None:
            raise AdapterError("Home Assistant adapter already started.")
        try:
            self._token = read_env(self.env_path).get("HA_TOKEN", "")
            if not self._token:
                raise LocalError("Missing token")
            self.client = httpx.AsyncClient(
                base_url=self.config.url,
                timeout=10,
                transport=self.transport,
                headers={"Authorization": "Bearer " + self._token},
            )
        except (LocalError, ValueError):
            raise AdapterError(
                "Home Assistant requires HA_TOKEN in private .env."
            ) from None

    async def close(self) -> None:
        socket, self.socket = self.socket, None
        client, self.client = self.client, None
        self._token = ""
        self.subscription_ready.clear()
        try:
            try:
                if socket is not None:
                    await socket.close()
            finally:
                if client is not None:
                    await client.aclose()
        except Exception:
            raise AdapterError("Home Assistant cleanup failed.") from None

    def ready(self) -> httpx.AsyncClient:
        if self.client is None:
            raise AdapterUnavailable(UNAVAILABLE)
        return self.client

    async def request(
        self, method: str, path: str, data: dict[str, Any] | None = None
    ) -> Any:
        try:
            response = await self.ready().request(method, path, json=data)
        except httpx.TransportError:
            raise AdapterUnavailable(UNAVAILABLE) from None
        if response.status_code in {401, 403}:
            raise AdapterError("Home Assistant authentication refused.")
        if response.status_code == 404 or response.status_code >= 500:
            raise AdapterUnavailable(UNAVAILABLE)
        if response.status_code != 200:
            raise AdapterError("Home Assistant request refused.")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("Malformed Home Assistant response.") from None

    async def raw_state(self, entity: str) -> dict[str, Any]:
        data = await self.request("GET", "/api/states/" + entity)
        try:
            if (
                not isinstance(data, dict)
                or data["entity_id"] != entity
                or not isinstance(data["state"], str)
                or not isinstance(data["attributes"], dict)
                or not isinstance(data["last_updated"], str)
            ):
                raise ValueError
            at = utc(datetime.fromisoformat(data["last_updated"]))
            if at > now():
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise AdapterError(
                "Malformed or incorrectly scoped Home Assistant state."
            ) from None
        if data["state"] in {"unknown", "unavailable"}:
            raise AdapterUnavailable(UNAVAILABLE)
        return data

    async def temperature_unit(self) -> str:
        # HA state attributes use the instance unit system (/api/config).
        config = await self.request("GET", "/api/config")
        try:
            unit = config["unit_system"]["temperature"]
            if unit not in {"°C", "°F"}:
                raise ValueError
            return str(unit)
        except (KeyError, TypeError, ValueError):
            raise AdapterError("Invalid Home Assistant temperature unit.") from None

    def binding(self, entity: str) -> AssetBinding:
        if entity not in self.bindings:
            raise AdapterError("Entity is not bound to this household.")
        return self.bindings[entity]

    async def list_entities(self) -> tuple[str, ...]:
        # Discovery never widens the explicit binding allowlist.
        found = []
        for entity in sorted(self.bindings):
            try:
                await self.get_state(entity)
            except AdapterUnavailable:
                continue
            found.append(entity)
        return tuple(found)

    async def get_state(self, entity_id: str) -> Observation:
        binding = self.binding(entity_id)
        data = await self.raw_state(entity_id)
        at = utc(datetime.fromisoformat(data["last_updated"]))
        config = self.config.entities[entity_id]
        try:
            if entity_id.startswith("climate."):
                attrs = data["attributes"]
                unit = await self.temperature_unit()
                if data["state"] not in {
                    "off",
                    "heat",
                    "cool",
                    "heat_cool",
                    "auto",
                    "dry",
                    "fan_only",
                }:
                    raise ValueError
                state = ObservationState(
                    available=True,
                    temp_f=fahrenheit(attrs["current_temperature"], unit),
                    target_f=fahrenheit(attrs["temperature"], unit)
                    if attrs.get("temperature") is not None
                    else None,
                )
            else:
                if data["state"] not in {"on", "off"}:
                    raise ValueError
                state = ObservationState(available=True, on=data["state"] == "on")
            if config.power_sensor:
                try:
                    power = await self.raw_state(config.power_sensor)
                except AdapterUnavailable:
                    power = None
                if power is not None:
                    unit = power["attributes"].get("unit_of_measurement")
                    if unit not in {"W", "kW"}:
                        raise ValueError
                    value = numeric(float(power["state"])) / (
                        1000 if unit == "W" else 1
                    )
                    at = min(at, utc(datetime.fromisoformat(power["last_updated"])))
                    state = ObservationState.model_validate(
                        state.model_dump() | {"power_kw": value}
                    )
            return Observation(
                id=uuid4(),
                household_id=self.household_id,
                asset_id=binding.asset_id,
                domain="devices",
                source=config.source,
                observed_at=at,
                state=state,
            )
        except AdapterError:
            raise
        except (ValueError, KeyError, TypeError, OverflowError):
            raise AdapterError(
                "Malformed Home Assistant reading; payload withheld."
            ) from None

    async def subscribe(self) -> AsyncGenerator[Observation, None]:
        self.ready()
        if self.subscribing:
            raise AdapterError("Only one Home Assistant subscription is allowed.")
        self.subscribing = True
        try:
            # https://developers.home-assistant.io/docs/api/websocket/
            url = self.config.url.replace("http", "ws", 1) + "/api/websocket"
            async with connect(
                url, open_timeout=10, close_timeout=10, proxy=None
            ) as socket:
                self.socket = socket
                async with asyncio.timeout(10):
                    hello = json.loads(await socket.recv())
                    if hello.get("type") != "auth_required":
                        raise AdapterError(
                            "Invalid Home Assistant authentication handshake."
                        )
                    await socket.send(
                        json.dumps({"type": "auth", "access_token": self._token})
                    )
                    auth = json.loads(await socket.recv())
                    if auth.get("type") != "auth_ok":
                        raise AdapterError("Home Assistant authentication refused.")
                    await socket.send(
                        json.dumps(
                            {
                                "id": 1,
                                "type": "subscribe_events",
                                "event_type": "state_changed",
                            }
                        )
                    )
                    ack = json.loads(await socket.recv())
                    if (
                        ack.get("type") != "result"
                        or ack.get("id") != 1
                        or ack.get("success") is not True
                    ):
                        raise AdapterError("Home Assistant subscription refused.")
                self.subscription_ready.set()
                while True:
                    msg = json.loads(await socket.recv())
                    if msg.get("type") != "event" or msg.get("id") != 1:
                        raise AdapterError(
                            "Invalid Home Assistant subscription message."
                        )
                    event = msg["event"]
                    if event["event_type"] != "state_changed":
                        raise AdapterError("Invalid Home Assistant event type.")
                    entity = event["data"]["entity_id"]
                    if not isinstance(entity, str):
                        raise AdapterError("Invalid Home Assistant event entity.")
                    for control, config in self.config.entities.items():
                        if entity in {control, config.power_sensor}:
                            yield await self.get_state(control)
        except (OSError, TimeoutError, WebSocketException):
            raise AdapterUnavailable(UNAVAILABLE) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AdapterError(
                "Invalid Home Assistant subscription; payload withheld."
            ) from None
        finally:
            self.socket = None
            self.subscribing = False
            self.subscription_ready.clear()

    def write_action(self, action: Action, kind: str) -> Action:
        try:
            action = ingest(action)
            binding = self.binding(action.target.entity)
            expected_class = (
                "energy.hvac_adjust" if kind == "climate" else "environment.lights"
            )
            attr = "target_f" if kind == "climate" else "on"
            if (
                self.pipeline is None
                or action.target.adapter != "ha"
                or action.action_class != expected_class
                or set(action.params) != {attr}
                or action.scheduled_for is not None
                or action.target.entity.split(".")[0]
                not in ({"climate"} if kind == "climate" else {"light", "switch"})
                or action.target.zone is not None
                and action.target.zone != str(binding.asset_id)
            ):
                raise ValueError
            value = action.params[attr]
            if kind == "climate":
                numeric(value)
            elif type(value) is not bool:
                raise ValueError
            effect = action.expected_effect
            if effect is not None and (
                effect.entity != action.target.entity
                or effect.attr != attr
                or type(effect.value) is bool
                and kind == "climate"
                or kind == "light"
                and type(effect.value) is not bool
                or effect.value != value
                or effect.by.utcoffset() is None
            ):
                raise ValueError
            return action
        except (ValueError, TypeError):
            raise AdapterError(
                "Unsupported or inconsistent Home Assistant action."
            ) from None

    async def set_light(self, action: Action, decision: Decision) -> None:
        action = self.write_action(action, "light")
        await self.execute(action, decision)

    async def set_climate(self, action: Action, decision: Decision) -> None:
        action = self.write_action(action, "climate")
        await self.execute(action, decision)

    async def climate_params(self, action: Action) -> dict[str, Any]:
        data = await self.raw_state(action.target.entity)
        try:
            attrs = data["attributes"]
            unit = await self.temperature_unit()
            target_f = numeric(action.params["target_f"])
            low, high = (
                fahrenheit(attrs["min_temp"], unit),
                fahrenheit(attrs["max_temp"], unit),
            )
            if data["state"] not in {"heat", "cool"} or not low <= target_f <= high:
                raise ValueError
            if (
                type(attrs["supported_features"]) is not int
                or not attrs["supported_features"] & 1
            ):
                raise ValueError
            target = (target_f - 32) * 5 / 9 if unit == "°C" else target_f
            if "target_temp_step" in attrs:
                step = numeric(attrs["target_temp_step"])
                if step <= 0 or not math.isclose(
                    target / step, round(target / step), abs_tol=1e-8, rel_tol=0
                ):
                    raise ValueError
        except (ValueError, TypeError, KeyError):
            raise AdapterError(
                "Unsupported Home Assistant climate setpoint or mode."
            ) from None
        return {"temperature": target}

    async def execute(self, action: Action, decision: Decision) -> None:
        kind = "climate" if action.action_class == "energy.hvac_adjust" else "light"
        action = self.write_action(action, kind)
        params = await self.climate_params(action) if kind == "climate" else {}
        service = (
            "set_temperature"
            if kind == "climate"
            else "turn_on"
            if action.params["on"]
            else "turn_off"
        )
        assert self.pipeline is not None
        attempt = await self.pipeline.claim_execution(action, decision)
        domain = action.target.entity.split(".")[0]
        # REST services actuate devices; /api/states writes would only fabricate state.
        # https://developers.home-assistant.io/docs/api/rest/#post-apiservicesdomainservice
        await self.request(
            "POST",
            f"/api/services/{domain}/{service}",
            {"entity_id": action.target.entity, **params},
        )
        await self.pipeline.execution_outcome(action, attempt, EventType.EXECUTED)
        matched = False
        try:
            async with asyncio.timeout(10):
                while True:
                    # Direct HA read, never registry fallback or rounded policy facts.
                    data = await self.raw_state(action.target.entity)
                    if domain == "climate":
                        attrs = data["attributes"]
                        actual = fahrenheit(
                            attrs["temperature"], await self.temperature_unit()
                        )
                        matched = (
                            abs(actual - numeric(action.params["target_f"])) <= 0.000001
                        )
                    else:
                        matched = data["state"] == (
                            "on" if action.params["on"] else "off"
                        )
                    if matched:
                        break
                    await asyncio.sleep(1)
        except (TimeoutError, AdapterError, KeyError, TypeError):
            pass
        await self.pipeline.execution_outcome(
            action, attempt, EventType.VERIFIED if matched else EventType.VERIFY_FAILED
        )
        if not matched:
            raise AdapterUnavailable(
                "Home Assistant verification failed; actual effect unknown."
            )

    async def set_cover(self, action: Action, decision: Decision) -> None:
        raise AdapterUnavailable(
            "Home Assistant cover and security writes are unavailable."
        )


def factories(
    *,
    config_path: Path,
    assets: tuple[Asset, ...],
    bindings: tuple[AssetBinding, ...],
    pipeline: Pipeline | None = None,
    env_path: Path = Path(".env"),
) -> dict[Key, Factory]:
    config = load_config(config_path)
    return {
        ("devices", "ha"): lambda household: HomeAssistant(
            household,
            config=config,
            assets=assets,
            bindings=bindings,
            pipeline=pipeline,
            env_path=env_path,
        )
    }
