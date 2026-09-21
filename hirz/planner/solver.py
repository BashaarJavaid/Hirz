"""Sparse cost MILP. Solver output is untrusted until constraints and replay pass."""

import math
from time import perf_counter
from typing import Any

import numpy as np
from scipy.optimize import (  # type: ignore[import-untyped]
    Bounds,
    LinearConstraint,
    milp,
)
from scipy.sparse import coo_matrix  # type: ignore[import-untyped]

from hirz.planner.feedback import battery_envelope, comfort_envelope
from hirz.planner.heuristic import appliance_windows
from hirz.planner.models import Control, PlannerInput, Schedule, SolverDiagnostics
from hirz.planner.replay import effective


class Matrix:
    def __init__(self) -> None:
        self.cost: list[float] = []
        self.lower: list[float] = []
        self.upper: list[float] = []
        self.integer: list[int] = []
        self.rows: list[dict[int, float]] = []
        self.lo: list[float] = []
        self.hi: list[float] = []
        self.names: list[str] = []

    def var(
        self, n: int, low: float = 0, high: float = math.inf, integer: bool = False
    ) -> list[int]:
        result = list(range(len(self.cost), len(self.cost) + n))
        self.cost.extend([0.0] * n)
        self.lower.extend([low] * n)
        self.upper.extend([high] * n)
        self.integer.extend([int(integer)] * n)
        return result

    def row(self, terms: dict[int, float], low: float, high: float, name: str) -> None:
        self.rows.append(terms)
        self.lo.append(low)
        self.hi.append(high)
        self.names.append(name)


def solve(p: PlannerInput) -> tuple[Schedule | None, SolverDiagnostics]:
    began = perf_counter()
    n = len(p.slots)
    m = Matrix()
    g, export = m.var(n), m.var(n)
    grid_direction = m.var(n, high=1, integer=True)
    ev = m.var(n)
    charge, discharge = m.var(n), m.var(n)
    direction = m.var(n, high=1, integer=True)
    energy = m.var(n + 1)
    target, ev_start, _ = effective(p)
    windows = appliance_windows(p)
    starts = {i: m.var(1, high=1, integer=True)[0] for i in windows}
    if p.appliance is not None:
        m.row(
            dict.fromkeys(starts.values(), 1.0),
            1,
            1,
            "appliance contiguous cycle and deadline",
        )
    required = (
        0 if p.ev is None else (target - p.ev.soc) * p.ev.capacity_kwh / p.ev.efficiency
    )
    m.row(dict.fromkeys(ev, 1.0), required, required, "equal EV delivery by deadline")
    for c in p.constraints:
        if c.kind == "ev_target" and p.ev is not None:
            assert c.value is not None
            amount = (c.value - p.ev.soc) * p.ev.capacity_kwh / p.ev.efficiency
            m.row(dict.fromkeys(ev, 1.0), amount, amount, c.provenance.text)
    battery_power = 0 if p.battery is None else p.battery.power_kw
    eta = 1 if p.battery is None else math.sqrt(p.battery.efficiency)
    opening = 0 if p.battery is None else p.battery.soc * p.battery.capacity_kwh
    for v in energy:
        m.lower[v] = (
            0 if p.battery is None else p.battery.reserve_soc * p.battery.capacity_kwh
        )
        m.upper[v] = 0 if p.battery is None else p.battery.capacity_kwh
    if p.causal_controls:
        lower, upper = battery_envelope(p)
        for i, v in enumerate(energy):
            m.lower[v], m.upper[v] = lower[i], upper[i]
    m.lower[energy[0]] = m.upper[energy[0]] = opening
    m.lower[energy[-1]] = m.upper[energy[-1]] = opening
    temperatures, heating, cooling = [], [], []
    for spec in p.zones:
        temp, heat, cool, mode = (
            m.var(n + 1),
            m.var(n),
            m.var(n),
            m.var(n, high=1, integer=True),
        )
        temperatures.append(temp)
        heating.append(heat)
        cooling.append(cool)
        z = spec.physical
        reachable = comfort_envelope(spec, p.slots) if p.causal_controls else None
        m.lower[temp[0]] = m.upper[temp[0]] = z.temp_f
        for i, s in enumerate(p.slots):
            lo = max(spec.lower[i], spec.lower[i + 1] if i + 1 < n else spec.end_lower)
            hi = min(spec.upper[i], spec.upper[i + 1] if i + 1 < n else spec.end_upper)
            if reachable is not None:
                lo, hi = max(lo, reachable[0][i + 1]), min(hi, reachable[1][i + 1])
            m.row({temp[i + 1]: 1}, lo, hi, f"{spec.entity} comfort {i}")
            m.row(
                {temp[i]: 1},
                spec.lower[i],
                spec.upper[i],
                f"{spec.entity} opening comfort {i}",
            )
            dt = s.hours
            passive = (
                s.outdoor_f / z.resistance_f_per_kw
                + spec.occupants[i] * z.occupant_kw
                + s.irradiance * z.solar_gain_area_m2
            )
            rhs = dt * passive / z.thermal_mass_kwh_per_f
            m.row(
                {
                    temp[i + 1]: 1,
                    temp[i]: -1 + dt / z.resistance_f_per_kw / z.thermal_mass_kwh_per_f,
                    heat[i]: -1 / z.thermal_mass_kwh_per_f,
                    cool[i]: 1 / z.thermal_mass_kwh_per_f,
                },
                rhs,
                rhs,
                f"{spec.entity} thermal balance",
            )
            m.row({heat[i]: 1, mode[i]: -z.hvac_kw * dt}, -math.inf, 0, "heating power")
            m.row(
                {cool[i]: 1, mode[i]: z.hvac_kw * dt},
                -math.inf,
                z.hvac_kw * dt,
                "cooling power",
            )
    for i, s in enumerate(p.slots):
        dt = s.hours
        m.upper[ev[i]] = (
            0
            if p.ev is None or s.start < ev_start or s.end > p.ev_deadline
            else p.ev.charger_kw * dt
        )
        m.cost[g[i]] = s.price
        m.cost[charge[i]] = p.wear_per_kwh * eta
        m.cost[discharge[i]] = p.wear_per_kwh / eta
        m.row(
            {energy[i + 1]: 1, energy[i]: -1, charge[i]: -eta, discharge[i]: 1 / eta},
            0,
            0,
            "battery conservation",
        )
        m.row(
            {charge[i]: 1, direction[i]: battery_power * dt},
            -math.inf,
            battery_power * dt,
            "battery charge exclusivity",
        )
        m.row(
            {discharge[i]: 1, direction[i]: -battery_power * dt},
            -math.inf,
            0,
            "battery discharge exclusivity",
        )
        # Big M is derived from installed power, never an arbitrary huge constant.
        maximum = (
            p.base_load_kw
            + (p.ev.charger_kw if p.ev else 0)
            + battery_power
            + sum(z.physical.hvac_kw / z.physical.cop for z in p.zones)
            + (
                p.appliance.cycle_kwh / (p.appliance.cycle_minutes / 60)
                if p.appliance
                else 0
            )
        ) * dt
        m.row(
            {g[i]: 1, grid_direction[i]: -maximum},
            -math.inf,
            0,
            "grid import exclusivity",
        )
        m.row(
            {export[i]: 1, grid_direction[i]: s.solar_kw * dt},
            -math.inf,
            s.solar_kw * dt,
            "solar export only",
        )
        m.row(
            {export[i]: 1, direction[i]: s.solar_kw * dt},
            -math.inf,
            s.solar_kw * dt,
            "no battery to grid",
        )
        balance: dict[int, float] = {
            g[i]: 1,
            export[i]: -1,
            discharge[i]: 1,
            charge[i]: -1,
            ev[i]: -1,
        }
        for j, spec in enumerate(p.zones):
            balance[heating[j][i]] = balance[cooling[j][i]] = -1 / spec.physical.cop
        for start, v in starts.items():
            balance[v] = -windows[start][i]
        rhs = (p.base_load_kw - s.solar_kw) * dt
        m.row(balance, rhs, rhs, "household energy balance")
    row, col, data = [], [], []
    for i, terms in enumerate(m.rows):
        for v, coefficient in terms.items():
            row.append(i)
            col.append(v)
            data.append(coefficient)
    matrix = coo_matrix((data, (row, col)), shape=(len(m.rows), len(m.cost))).tocsc()
    result: Any = milp(
        np.array(m.cost),
        integrality=np.array(m.integer),
        bounds=Bounds(m.lower, m.upper),
        constraints=LinearConstraint(matrix, m.lo, m.hi),
        options={"time_limit": 5.0, "mip_rel_gap": 0.001},
    )
    elapsed = perf_counter() - began
    gap = getattr(result, "mip_gap", None)
    gap = None if gap is None or not math.isfinite(gap) else float(gap)
    status = {
        0: "optimal",
        1: "timeout",
        2: "infeasible",
        3: "unbounded",
        4: "error",
    }.get(result.status, "error")
    diag = SolverDiagnostics(
        status=status, elapsed_seconds=elapsed, gap=gap, message=str(result.message)
    )
    if result.status not in (0, 1) or result.x is None:
        return None, diag
    x = result.x
    lhs = matrix @ x
    if (
        not np.all(np.isfinite(x))
        or np.any(x < np.array(m.lower) - 1e-7)
        or np.any(x > np.array(m.upper) + 1e-7)
        or np.any(lhs < np.array(m.lo) - 1e-7)
        or np.any(lhs > np.array(m.hi) + 1e-7)
        or any(
            abs(x[v] - round(x[v])) > 1e-7
            for v, integer in enumerate(m.integer)
            if integer
        )
    ):
        return None, diag.model_copy(update={"status": "invalid_incumbent"})
    binding = tuple(
        dict.fromkeys(
            name
            for i, name in enumerate(m.names)
            if abs(lhs[i] - m.lo[i]) <= 1e-6 or abs(lhs[i] - m.hi[i]) <= 1e-6
        )
    )
    controls = []
    for i, s in enumerate(p.slots):
        controls.append(
            Control(
                ev_kwh=max(0, float(x[ev[i]])),
                battery_kw=float((x[discharge[i]] - x[charge[i]]) / s.hours),
                targets=tuple(float(x[t[i + 1]]) for t in temperatures),
                modes=tuple(
                    "heat"
                    if x[h[i]] > 1e-8
                    else "cool"
                    if x[c[i]] > 1e-8
                    else "heat"
                    if s.outdoor_f < x[temperatures[j][i + 1]]
                    else "cool"
                    for j, (h, c) in enumerate(zip(heating, cooling, strict=True))
                ),
                appliance_start=i in starts and x[starts[i]] > 0.5,
            )
        )
    return Schedule(
        controls=tuple(controls),
        method="milp" if result.status == 0 else "timeout_incumbent",
    ), diag.model_copy(update={"binding": binding})
