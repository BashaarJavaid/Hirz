"""Recorded HA boundary, transport and direct verification checks."""

import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from hirz.adapters.base import AdapterError, AdapterUnavailable
from hirz.adapters.devices.ha import HAConfig, HomeAssistant, factories, load_config
from hirz.graph.models import AssetBinding, ObservationState
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Decision, ExpectedEffect
from tests.unit.test_pipeline import AT, HOME, SEED, action, ident

STATES = json.loads(Path("tests/fixtures/ha/states.json").read_text())
MODELS = SEED.models(AT)
ASSETS = tuple(MODELS["assets"])
HOUSEHOLD = MODELS["households"][0]
BINDINGS = tuple(
    AssetBinding(
        id=uuid4(),
        household_id=HOME,
        asset_id=ident("assets", asset),
        adapter="ha",
        entity_id=entity,
    )
    for asset, entity in [
        ("hvac.living_room", "climate.demo"),
        ("light.living_room", "light.demo"),
    ]
)
CONFIG = HAConfig.model_validate(
    {
        "url": "http://ha.invalid",
        "entities": {
            "climate.demo": {"source": "real API, demo devices"},
            "light.demo": {"source": "real", "power_sensor": "sensor.power"},
        },
    }
)


def grant(a):
    return Decision.model_validate(
        dict(
            decision="execute",
            event_type="EXECUTE",
            action_id=a.action_id,
            constitution=dict(version=1, rule="test", mode="auto", conditions_met=True),
            audit_id=1,
        )
    )


def ha_action(climate=False, **changes):
    return action(
        "energy.hvac_adjust" if climate else "environment.lights",
        target={"adapter": "ha", "entity": "climate.demo" if climate else "light.demo"},
        params={"target_f": 72} if climate else {"on": True},
        **changes,
    )


class Recorded:
    def __init__(self):
        self.states = deepcopy(STATES)
        self.calls = []
        self.unit = "°F"
        self.error = None
        self.apply = True

    def __call__(self, request):
        self.calls.append(request)
        if self.error is not None:
            if isinstance(self.error, int):
                return httpx.Response(self.error, json={"secret": "withheld"})
            raise self.error
        if request.url.path == "/api/config":
            return httpx.Response(200, json={"unit_system": {"temperature": self.unit}})
        if request.method == "POST":
            data = json.loads(request.content)
            if self.apply:
                row = self.states[data["entity_id"]]
                if "temperature" in data:
                    row["attributes"]["temperature"] = data["temperature"]
                else:
                    row["state"] = (
                        "on" if request.url.path.endswith("turn_on") else "off"
                    )
            return httpx.Response(200, json=[])
        entity = request.url.path.rsplit("/", 1)[-1]
        return (
            httpx.Response(200, json=self.states[entity])
            if entity in self.states
            else httpx.Response(404)
        )


def adapter(tmp_path, recorded=None, writable=False, **changes):
    env = tmp_path / ".env"
    env.write_text("HA_TOKEN=recorded-not-a-credential\n")
    env.chmod(0o600)
    p = AsyncMock() if writable else None
    if p:
        p.household_id = HOME
        p.claim_execution.return_value = 2
    return HomeAssistant(
        HOUSEHOLD,
        **(
            dict(
                config=CONFIG,
                assets=ASSETS,
                bindings=BINDINGS,
                pipeline=p,
                env_path=env,
                transport=httpx.MockTransport(recorded or Recorded()),
            )
            | changes
        ),
    )


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        value = next(self.messages, OSError("private token upstream"))
        if isinstance(value, Exception):
            raise value
        return json.dumps(value)

    async def close(self):
        self.closed = True


HANDSHAKE = [
    {"type": "auth_required"},
    {"type": "auth_ok"},
    {"id": 1, "type": "result", "success": True},
]


def event(entity):
    return {
        "type": "event",
        "id": 1,
        "event": {"event_type": "state_changed", "data": {"entity_id": entity}},
    }


def test_reads_units_timestamps_and_missing_power(tmp_path):
    async def run():
        transport = Recorded()
        a = adapter(tmp_path, transport)
        await a.start()
        try:
            assert await a.list_entities() == ("climate.demo", "light.demo")
            light = await a.get_state("light.demo")
            assert light.state.on is False and light.state.power_kw == 0.1234
            assert (
                light.observed_at == AT - timedelta(minutes=1)
                and light.source == "real"
            )
            climate = await a.get_state("climate.demo")
            assert climate.state.target_f == 68 and climate.observed_at == AT
            transport.unit = "°C"
            transport.states["climate.demo"]["attributes"].update(
                temperature=20, current_temperature=21
            )
            assert (await a.get_state("climate.demo")).state.temp_f == 69.8
            transport.states["sensor.power"]["state"] = "unavailable"
            assert (await a.get_state("light.demo")).state == ObservationState(
                on=False, available=True
            )
            del transport.states["sensor.power"]
            assert (await a.get_state("light.demo")).state.on is False
            with pytest.raises(AdapterError):
                await a.get_state("light.unbound")
        finally:
            await a.close()
        with pytest.raises(AdapterUnavailable):
            await a.get_state("light.demo")

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.states["light.demo"].update(entity_id="light.other"),
        lambda r: r.states["light.demo"].update(last_updated="bad"),
        lambda r: r.states["light.demo"].update(
            last_updated="2036-01-01T00:00:00+00:00"
        ),
        lambda r: r.states["light.demo"].update(state="toggle"),
        lambda r: r.states["light.demo"].update(attributes=[]),
        lambda r: r.states["sensor.power"]["attributes"].update(
            unit_of_measurement="kWh"
        ),
        lambda r: r.states["sensor.power"].update(state="NaN"),
        lambda r: r.states["sensor.power"].update(state="Infinity"),
    ],
)
def test_malformed_readings_fail_closed(tmp_path, mutation):
    async def run():
        r = Recorded()
        mutation(r)
        a = adapter(tmp_path, r)
        await a.start()
        try:
            with pytest.raises(
                AdapterError, match="payload withheld|scoped|numeric value"
            ):
                await a.get_state("light.demo")
        finally:
            await a.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "error,kind",
    [
        (401, AdapterError),
        (403, AdapterError),
        (400, AdapterError),
        (404, AdapterUnavailable),
        (503, AdapterUnavailable),
        (httpx.ReadTimeout("private-token"), AdapterUnavailable),
    ],
)
def test_transport_redaction(tmp_path, error, kind):
    async def run():
        r = Recorded()
        r.error = error
        a = adapter(tmp_path, r)
        await a.start()
        try:
            with pytest.raises(kind) as exc:
                await a.get_state("light.demo")
            assert "private-token" not in str(exc.value) and "secret" not in str(
                exc.value
            )
        finally:
            await a.close()

    asyncio.run(run())


def test_subscription_ack_filter_disconnect_and_singleton(tmp_path):
    async def run():
        a = adapter(tmp_path)
        await a.start()
        socket = Socket(HANDSHAKE + [event("light.other"), event("sensor.power")])
        with patch("hirz.adapters.devices.ha.connect", return_value=socket) as connect:
            stream = a.subscribe()
            row = await anext(stream)
            assert a.subscription_ready.is_set() and row.state.power_kw == 0.1234
            assert socket.sent[-1] == {
                "id": 1,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }
            assert connect.call_args.kwargs["open_timeout"] == 10
            with pytest.raises(AdapterError):
                await anext(a.subscribe())
            with pytest.raises(AdapterUnavailable):
                await anext(stream)
            assert socket.closed and not a.subscription_ready.is_set()
        await a.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"type": "wrong"}],
        [HANDSHAKE[0], {"type": "auth_invalid", "message": "secret"}],
        HANDSHAKE[:2] + [{"id": 1, "type": "result", "success": False}],
        HANDSHAKE + [[1]],
        HANDSHAKE + [{"type": "event", "id": 2}],
    ],
)
def test_subscription_failure_closes_redacts(tmp_path, messages):
    async def run():
        a = adapter(tmp_path)
        await a.start()
        socket = Socket(messages)
        try:
            with patch("hirz.adapters.devices.ha.connect", return_value=socket):
                with pytest.raises(AdapterError) as exc:
                    await anext(a.subscribe())
                assert "secret" not in str(exc.value)
                assert socket.closed and not a.subscribing
        finally:
            await a.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "params", [{}, {"on": 1}, {"on": True, "brightness": 10}, {"toggle": True}]
)
def test_unsupported_parameters_no_claim(tmp_path, params):
    async def run():
        a = adapter(tmp_path, writable=True)
        x = ha_action()
        x = x.model_copy(update={"params": params})
        x = x.model_copy(update={"content_hash": action_hash(x)})
        with pytest.raises(AdapterError):
            await a.set_light(x, grant(x))
        a.pipeline.claim_execution.assert_not_called()

    asyncio.run(run())


def test_effects_and_read_only_refused(tmp_path):
    async def run():
        a = adapter(tmp_path, writable=True)
        x = ha_action()
        for value in (False, 1):
            y = x.model_copy(
                update={
                    "expected_effect": ExpectedEffect(
                        entity="light.demo", attr="on", value=value, by=AT
                    )
                }
            )
            with pytest.raises(AdapterError):
                await a.set_light(y, grant(y))
        a.pipeline.claim_execution.assert_not_called()
        with pytest.raises(AdapterError):
            await adapter(tmp_path).set_light(x, grant(x))
        with pytest.raises(AdapterUnavailable):
            await a.set_cover(x, grant(x))

    asyncio.run(run())


def test_single_request_direct_verification_and_celsius(tmp_path):
    async def run():
        r = Recorded()
        a = adapter(tmp_path, r, writable=True)
        await a.start()
        try:
            x = ha_action()
            await a.set_light(x, grant(x))
            assert len([q for q in r.calls if q.method == "POST"]) == 1
            assert [
                c.args[-1] for c in a.pipeline.execution_outcome.call_args_list
            ] == ["EXECUTED", "VERIFIED"]
            r.unit = "°C"
            r.states["climate.demo"]["attributes"].update(min_temp=10, max_temp=30)
            x = ha_action(True)
            await a.set_climate(x, grant(x))
            assert (
                r.states["climate.demo"]["attributes"]["temperature"]
                == (72 - 32) * 5 / 9
            )
            assert (await a.get_state("climate.demo")).state.target_f == 72
        finally:
            await a.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "attrs,mode",
    [
        ({"target_temp_step": 0.5}, "heat"),
        ({"supported_features": 2}, "heat"),
        ({}, "heat_cool"),
        ({"min_temp": 80}, "heat"),
        ({"max_temp": 60}, "heat"),
    ],
)
def test_climate_unsupported_no_dispatch(tmp_path, attrs, mode):
    async def run():
        r = Recorded()
        r.unit = "°C" if "target_temp_step" in attrs else "°F"
        r.states["climate.demo"]["attributes"].update(attrs)
        r.states["climate.demo"]["state"] = mode
        a = adapter(tmp_path, r, writable=True)
        await a.start()
        x = ha_action(True)
        try:
            with pytest.raises(AdapterError):
                await a.set_climate(x, grant(x))
            a.pipeline.claim_execution.assert_not_called()
            assert not any(q.method == "POST" for q in r.calls)
        finally:
            await a.close()

    asyncio.run(run())


def test_verification_timeout_no_resend(tmp_path):
    async def run():
        r = Recorded()
        r.apply = False
        a = adapter(tmp_path, r, writable=True)
        await a.start()
        x = ha_action()
        try:
            with patch(
                "hirz.adapters.devices.ha.asyncio.sleep", side_effect=TimeoutError
            ):
                with pytest.raises(AdapterUnavailable):
                    await a.set_light(x, grant(x))
            assert len([q for q in r.calls if q.method == "POST"]) == 1
            assert a.pipeline.execution_outcome.call_args.args[-1] == "VERIFY_FAILED"
        finally:
            await a.close()

    asyncio.run(run())


def test_config_scope_and_private_env(tmp_path):
    path = tmp_path / "ha.yaml"
    path.write_text(
        "url: http://ha.invalid\nentities:\n  light.demo:\n    source: twin\n"
    )
    with pytest.raises(AdapterError):
        load_config(path)
    with pytest.raises(AdapterError):
        adapter(tmp_path, bindings=())
    with pytest.raises(AdapterError):
        adapter(
            tmp_path,
            bindings=(
                BINDINGS[0].model_copy(update={"household_id": uuid4()}),
                BINDINGS[1],
            ),
        )
    for url in (
        "http://user:secret@ha.invalid",
        "ftp://ha.invalid",
        "http://ha.invalid?token=private",
    ):
        with pytest.raises(ValueError):
            HAConfig.model_validate(CONFIG.model_dump() | {"url": url})

    async def run():
        a = adapter(tmp_path)
        a.env_path.chmod(0o644)
        with pytest.raises(AdapterError):
            await a.start()

    asyncio.run(run())
    path.write_text(
        "url: http://ha.invalid\nentities:\n  climate.demo:\n    source: real API, demo devices\n  light.demo:\n    source: real\n"
    )
    factory = factories(config_path=path, assets=ASSETS, bindings=BINDINGS)[
        ("devices", "ha")
    ]
    assert factory(HOUSEHOLD).household_id == HOME


def test_direct_verification_preserves_precision_and_refuses_twin(tmp_path):
    async def run():
        r = Recorded()
        a = adapter(tmp_path, r, writable=True)
        await a.start()
        x = ha_action(True)
        original = r.__call__

        def rounded(request):
            response = original(request)
            if request.method == "POST":
                r.states["climate.demo"]["attributes"]["temperature"] = 72.00001
            return response

        await a.close()
        a = adapter(tmp_path, writable=True, transport=httpx.MockTransport(rounded))
        await a.start()
        try:
            with patch(
                "hirz.adapters.devices.ha.asyncio.sleep", side_effect=TimeoutError
            ):
                with pytest.raises(AdapterUnavailable):
                    await a.set_climate(x, grant(x))
            # Policy facts round to 4 decimals, but verification cannot accept them.
            assert (await a.get_state("climate.demo")).state.target_f == 72
            assert a.pipeline.execution_outcome.call_args.args[-1] == "VERIFY_FAILED"
            a.get_state = AsyncMock(
                return_value=object()
            )  # A registry/twin cannot verify.
            r.error = httpx.ReadTimeout("private")
            with pytest.raises(AdapterUnavailable):
                await a.set_light(ha_action(), grant(ha_action()))
            a.get_state.assert_not_called()
        finally:
            await a.close()

    asyncio.run(run())


def test_config_auth_and_connect_timeouts_no_fallback(tmp_path):
    async def run():
        r = Recorded()
        a = adapter(tmp_path, r)
        await a.start()
        try:
            for error in (TimeoutError("secret"), OSError("secret")):
                with patch("hirz.adapters.devices.ha.connect", side_effect=error):
                    with pytest.raises(AdapterUnavailable):
                        await anext(a.subscribe())
                assert not a.subscribing
            socket = Socket([HANDSHAKE[0], TimeoutError("secret")])
            with patch("hirz.adapters.devices.ha.connect", return_value=socket):
                with pytest.raises(AdapterUnavailable):
                    await anext(a.subscribe())
            assert socket.closed
            r.unit = "K"
            with pytest.raises(AdapterError):
                await a.get_state("climate.demo")
            r.states["climate.demo"]["attributes"]["current_temperature"] = float("nan")
            # httpx itself refuses encoding NaN; use a literal upstream response.
            await a.close()
            a = adapter(
                tmp_path,
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, content=b'{"secret":')
                ),
            )
            await a.start()
            with pytest.raises(AdapterError, match="Malformed"):
                await a.get_state("light.demo")
        finally:
            await a.close()

    asyncio.run(run())


def test_switch_power_and_shutdown(tmp_path):
    async def run():
        r = Recorded()
        r.states["switch.demo"] = r.states.pop("light.demo")
        r.states["switch.demo"]["entity_id"] = "switch.demo"
        r.states["sensor.power"]["attributes"]["unit_of_measurement"] = "kW"
        config = HAConfig.model_validate(
            CONFIG.model_dump()
            | {
                "entities": {
                    "climate.demo": CONFIG.entities["climate.demo"],
                    "switch.demo": CONFIG.entities["light.demo"],
                }
            }
        )
        bindings = tuple(
            b.model_copy(update={"entity_id": "switch.demo"})
            if b.entity_id == "light.demo"
            else b
            for b in BINDINGS
        )
        a = adapter(tmp_path, r, writable=True, config=config, bindings=bindings)
        await a.start()
        try:
            x = ha_action()
            x = x.model_copy(
                update={"target": x.target.model_copy(update={"entity": "switch.demo"})}
            )
            x = x.model_copy(update={"content_hash": action_hash(x)})
            await a.set_light(x, grant(x))
            assert any(q.url.path == "/api/services/switch/turn_on" for q in r.calls)
            assert (await a.get_state("switch.demo")).state.power_kw == 123.4
            socket = Socket(HANDSHAKE + [event("switch.demo")])
            with patch("hirz.adapters.devices.ha.connect", return_value=socket):
                stream = a.subscribe()
                await anext(stream)
                await a.close()
                assert socket.closed and a.socket is None and a.client is None
                await stream.aclose()
                assert not a.subscribing
        finally:
            await a.close()

    asyncio.run(run())


def test_unavailable_verification_does_not_consult_twin(tmp_path):
    async def run():
        def response(request):
            return (
                httpx.Response(200, json=[])
                if request.method == "POST"
                else httpx.Response(404)
            )

        a = adapter(tmp_path, writable=True, transport=httpx.MockTransport(response))
        a.get_state = AsyncMock(return_value=ObservationState(on=True, available=True))
        await a.start()
        try:
            x = ha_action()
            with pytest.raises(AdapterUnavailable):
                await a.set_light(x, grant(x))
            assert [
                c.args[-1] for c in a.pipeline.execution_outcome.call_args_list
            ] == ["EXECUTED", "VERIFY_FAILED"]
            a.get_state.assert_not_called()
        finally:
            await a.close()

    asyncio.run(run())


def test_climate_config_transport_remains_unavailable(tmp_path):
    async def run():
        r = Recorded()

        def response(request):
            if request.url.path == "/api/config":
                raise httpx.ReadTimeout("private")
            return r(request)

        a = adapter(tmp_path, transport=httpx.MockTransport(response))
        await a.start()
        try:
            with pytest.raises(AdapterUnavailable):
                await a.get_state("climate.demo")
        finally:
            await a.close()

    asyncio.run(run())


def test_cleanup_failure_redacted_and_client_closed(tmp_path):
    async def run():
        a = adapter(tmp_path)
        await a.start()
        client = a.client
        a.socket = AsyncMock()
        a.socket.close.side_effect = OSError("private upstream payload")
        with pytest.raises(AdapterError, match="cleanup failed") as exc:
            await a.close()
        assert "private" not in str(exc.value) and client.is_closed
        assert a.socket is None and a.client is None and not a._token

    asyncio.run(run())
