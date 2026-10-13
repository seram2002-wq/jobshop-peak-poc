"""
Job-Shop 스케줄링 + 전력 피크 최소화 PoC (Google OR-Tools CP-SAT)

경진대회에서는 '피크 부하의 x%를 여유 시간으로 옮긴다'는 고정 규칙으로 일정을 조정했고,
옮기는 양이 많아지면 새 피크가 생기는 한계가 있었다.
이 PoC는 같은 질문을 제약 최적화로 다시 푼다.

  1) 기준 일정: 설비가 비면 바로 시작하는 선착순 규칙 (현장의 일반적인 방식)
  2) 최적 일정: 같은 납기 안에서 전력 피크(동시 가동 부하)를 최소화

제약
  - 설비 중복 금지: 한 설비는 한 번에 한 작업만 (AddNoOverlap)
  - 공정 선후 관계: 같은 작업의 다음 공정은 이전 공정이 끝난 뒤 (start >= end)
  - 전력: 시간별 동시 가동 전력 합 <= 피크 (AddCumulative, 용량을 변수로 두고 최소화)

단위: 1칸 = 30분
"""
import collections
from ortools.sat.python import cp_model

SLOT_MIN = 30
BASE_LOAD = 40  # 상시 부하(kW): 조명·공조 등

MACHINES = ["프레스", "용접", "도장", "검사"]

# 작업별 공정: (설비 번호, 소요 칸 수, 가동 전력 kW)
JOBS = {
    "J1": [(0, 3, 55), (1, 2, 40), (2, 3, 35), (3, 1, 10)],
    "J2": [(1, 3, 45), (0, 2, 60), (3, 2, 10), (2, 2, 30)],
    "J3": [(0, 2, 50), (2, 4, 35), (1, 2, 40), (3, 1, 10)],
    "J4": [(2, 2, 30), (1, 3, 45), (0, 3, 55), (3, 1, 10)],
    "J5": [(0, 4, 60), (1, 2, 40), (3, 2, 10), (2, 2, 30)],
    "J6": [(1, 2, 40), (2, 3, 35), (0, 2, 50), (3, 2, 10)],
}


def build_model(jobs=JOBS):
    m = cp_model.CpModel()
    ops = {}  # (job, k) -> (start, end, interval, machine, power)
    per_machine = collections.defaultdict(list)
    horizon = sum(d for ops_ in jobs.values() for _, d, _ in ops_)
    for j, route in jobs.items():
        for k, (mc, dur, pw) in enumerate(route):
            s = m.NewIntVar(0, horizon, f"s_{j}_{k}")
            e = m.NewIntVar(0, horizon, f"e_{j}_{k}")
            itv = m.NewIntervalVar(s, dur, e, f"i_{j}_{k}")
            ops[(j, k)] = (s, e, itv, mc, pw)
            per_machine[mc].append(itv)
    for itvs in per_machine.values():          # 설비 중복 금지
        m.AddNoOverlap(itvs)
    for j, route in jobs.items():              # 공정 선후 관계
        for k in range(len(route) - 1):
            m.Add(ops[(j, k + 1)][0] >= ops[(j, k)][1])
    makespan = m.NewIntVar(0, horizon, "makespan")
    m.AddMaxEquality(makespan, [ops[(j, len(r) - 1)][1] for j, r in jobs.items()])
    peak = m.NewIntVar(0, sum(p for r in jobs.values() for _, _, p in r), "peak")
    m.AddCumulative([o[2] for o in ops.values()], [o[4] for o in ops.values()], peak)
    return m, ops, makespan, peak


def solve(objective, fixed=None, seconds=20, jobs=JOBS):
    m, ops, makespan, peak = build_model(jobs)
    for name, (op, val) in (fixed or {}).items():
        var = makespan if name == "makespan" else peak
        m.Add(var <= val) if op == "<=" else m.Add(var == val)
    m.Minimize(makespan if objective == "makespan" else peak)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 8
    status = solver.Solve(m)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), "해를 찾지 못함"
    rows = []
    for (j, k), (s, e, _, mc, pw) in ops.items():
        rows.append(dict(job=j, op=k + 1, machine=MACHINES[mc],
                         start=solver.Value(s), end=solver.Value(e), power=pw))
    return dict(rows=rows, makespan=solver.Value(makespan),
                status=solver.StatusName(status))


def greedy_schedule(jobs=JOBS):
    """현장에서 흔한 방식: 설비가 비고 이전 공정이 끝나면 바로 시작 (작업 번호 순 우선)"""
    machine_free = [0] * len(MACHINES)
    job_ready = {j: 0 for j in jobs}
    next_op = {j: 0 for j in jobs}
    rows = []
    remaining = sum(len(r) for r in jobs.values())
    while remaining:
        # 지금 시작할 수 있는 가장 이른 공정을 고른다 (동률이면 작업 번호 순)
        best = None
        for j, route in jobs.items():
            k = next_op[j]
            if k == len(route):
                continue
            mc, dur, pw = route[k]
            st = max(job_ready[j], machine_free[mc])
            if best is None or st < best[0]:
                best = (st, j, k, mc, dur, pw)
        st, j, k, mc, dur, pw = best
        rows.append(dict(job=j, op=k + 1, machine=MACHINES[mc], start=st, end=st + dur, power=pw))
        machine_free[mc] = job_ready[j] = st + dur
        next_op[j] += 1
        remaining -= 1
    return dict(rows=rows, makespan=max(r["end"] for r in rows), status="GREEDY")


def load_profile(rows, length):
    prof = [BASE_LOAD] * length
    for r in rows:
        for t in range(r["start"], r["end"]):
            prof[t] += r["power"]
    return prof


if __name__ == "__main__":
    # 1) 기준 일정: 설비가 비면 바로 시작하는 선착순 규칙
    base = greedy_schedule()
    base_peak = max(load_profile(base["rows"], base["makespan"]))
    # 2) 최적 일정: 같은 납기 안에서 피크 최소화 → 그다음 그 피크 안에서 납기 최소화
    opt1 = solve("peak", {"makespan": ("<=", base["makespan"])})
    opt_peak = max(load_profile(opt1["rows"], opt1["makespan"]))
    opt = solve("makespan", {"peak": ("<=", opt_peak - BASE_LOAD)})
    opt_peak = max(load_profile(opt["rows"], opt["makespan"]))

    hours = lambda n: n * SLOT_MIN / 60
    print(f"[기준] 완료 {hours(base['makespan']):.1f}시간, 피크 {base_peak} kW ({base['status']})")
    print(f"[최적] 완료 {hours(opt['makespan']):.1f}시간, 피크 {opt_peak} kW ({opt['status']})")
    print(f"피크 감소: {base_peak - opt_peak} kW ({(base_peak - opt_peak) / base_peak:.1%})")

    import json
    json.dump({"base": base, "opt": opt, "base_peak": base_peak, "opt_peak": opt_peak,
               "slot_min": SLOT_MIN, "base_load": BASE_LOAD, "machines": MACHINES},
              open("result.json", "w"), ensure_ascii=False, indent=1)
