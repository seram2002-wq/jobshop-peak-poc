"""
같은 문제를 두 가지로 풀어 비교: CP-SAT(제약 프로그래밍) vs MIP(혼합정수계획, SCIP)

문제: 완료 시간 상한 안에서 전력 피크 최소화 (jobshop_peak.py와 동일)

MIP 정식화 (시간 구간별 0/1 변수, time-indexed)
  x[o, t] ∈ {0, 1}   공정 o가 t칸에 시작하면 1
  P ≥ 0 (연속)        전력 피크 (상시 부하 제외)

  최소화  P
  제약
   (1) 공정마다 시작은 한 번             Σ_t x[o, t] = 1
   (2) 공정 선후 관계                    S[다음] ≥ S[o] + d[o],  S[o] = Σ_t t·x[o, t]
   (3) 설비 중복 금지 (칸마다)           Σ_{o∈설비 m} Σ_{t=τ-d[o]+1..τ} x[o, t] ≤ 1
   (4) 전력 (칸마다)                     Σ_o p[o] · Σ_{t=τ-d[o]+1..τ} x[o, t] ≤ P
   (5) 완료 시간 상한                    시작 가능 칸을 t ≤ H - d[o] 로 제한

CP-SAT은 (3)을 AddNoOverlap, (4)를 AddCumulative 한 줄로 표현하지만,
MIP는 시간 칸마다 제약식을 하나씩 만들어야 한다. 그 차이가 문제 크기와 계산 시간에 어떻게 나타나는지 본다.
"""
import random
import statistics
import time

from ortools.linear_solver import pywraplp

from jobshop_peak import JOBS, BASE_LOAD, SLOT_MIN, solve, greedy_schedule, load_profile
from experiments import random_instance


def solve_mip(jobs, horizon, seconds=60):
    s = pywraplp.Solver.CreateSolver("SCIP")
    s.SetTimeLimit(seconds * 1000)
    ops = [(j, k, m, d, p) for j, route in jobs.items() for k, (m, d, p) in enumerate(route)]
    x = {}
    for (j, k, m, d, p) in ops:
        for t in range(horizon - d + 1):
            x[j, k, t] = s.BoolVar(f"x_{j}_{k}_{t}")
    P = s.NumVar(0, s.infinity(), "P")
    start = {}
    for (j, k, m, d, p) in ops:                                     # (1)
        ts = range(horizon - d + 1)
        s.Add(sum(x[j, k, t] for t in ts) == 1)
        start[j, k] = sum(t * x[j, k, t] for t in ts)
    for j, route in jobs.items():                                   # (2)
        for k in range(len(route) - 1):
            s.Add(start[j, k + 1] >= start[j, k] + route[k][1])

    def active(j, k, d, tau):                                       # τ칸에 가동 중이면 1
        return [x[j, k, t] for t in range(max(0, tau - d + 1), min(tau, horizon - d) + 1)]

    machines = {m for (_, _, m, _, _) in ops}
    for tau in range(horizon):
        for mc in machines:                                         # (3)
            terms = [v for (j, k, m, d, p) in ops if m == mc for v in active(j, k, d, tau)]
            if len(terms) > 1:
                s.Add(sum(terms) <= 1)
        s.Add(sum(p * v for (j, k, m, d, p) in ops for v in active(j, k, d, tau)) <= P)   # (4)
    s.Minimize(P)
    t0 = time.perf_counter()
    status = s.Solve()
    elapsed = time.perf_counter() - t0
    ok = status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)
    return dict(peak=round(P.solution_value()) + BASE_LOAD if ok else None,
                status={pywraplp.Solver.OPTIMAL: "OPTIMAL", pywraplp.Solver.FEASIBLE: "FEASIBLE"}.get(status, "NONE"),
                seconds=elapsed, n_vars=s.NumVariables(), n_cons=s.NumConstraints())


def solve_cp(jobs, horizon, seconds=60):
    t0 = time.perf_counter()
    r = solve("peak", {"makespan": ("<=", horizon)}, seconds=seconds, jobs=jobs)
    elapsed = time.perf_counter() - t0
    return dict(peak=max(load_profile(r["rows"], r["makespan"])), status=r["status"], seconds=elapsed)


def compare(jobs, seconds=60):
    horizon = greedy_schedule(jobs)["makespan"]          # 선착순 규칙과 같은 완료 시간 상한
    cp, mip = solve_cp(jobs, horizon, seconds), solve_mip(jobs, horizon, seconds)
    return dict(horizon=horizon, cp=cp, mip=mip)


def plot(base, rand, scale):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in font_manager.findSystemFonts():
        if "NotoSansCJK-Regular" in f or "malgun" in f.lower() or "AppleGothic" in f:
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    ax = axes[0]
    ax.scatter([r["cp"]["peak"] for r in rand], [r["mip"]["peak"] for r in rand], color="#2b5f9e", s=40)
    lo = min(r["cp"]["peak"] for r in rand) - 5
    hi = max(r["cp"]["peak"] for r in rand) + 5
    ax.plot([lo, hi], [lo, hi], color="#d9622b", ls="--", lw=1.5, label="같은 값")
    ax.set_xlabel("CP-SAT 최소 피크 (kW)")
    ax.set_ylabel("MIP 최소 피크 (kW)")
    ax.set_title(f"무작위 예제 {len(rand)}개 · 두 방법의 최적값", loc="left", fontweight="bold")
    ax.legend(frameon=False)
    ax = axes[1]
    ns = [r["n_jobs"] for r in scale]
    for key, name, color in (("cp", "CP-SAT", "#18212b"), ("mip", "MIP (SCIP)", "#d9622b")):
        ts = [r[key]["seconds"] for r in scale]
        ax.plot(ns, ts, lw=2.5, color=color, label=name)
        for n, t, r in zip(ns, ts, scale):        # 채운 점 = 최적 증명, 빈 점 = 시간 안에 증명 못 함
            proved = r[key]["status"] == "OPTIMAL"
            ax.scatter([n], [t], s=70, color=color if proved else "white", edgecolor=color, lw=2, zorder=5)
    limit = max(r["mip"]["seconds"] for r in scale)
    ax.axhline(limit, color="#b3bdcc", ls="--", lw=1)
    ax.text(ns[0], limit * 1.15, f"계산 시간 상한 {limit:.0f}초", color="#5b6570", fontsize=9)
    ax.set_yscale("log")
    ax.set_xlabel("작업 수")
    ax.set_ylabel("계산 시간 (초, 로그)")
    ax.set_title("문제 크기에 따른 계산 시간 (빈 점 = 최적 증명 못 함)", loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="lower right")
    for a in axes:
        a.grid(alpha=0.3)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig("mip_compare.png", dpi=160)


if __name__ == "__main__":
    import json
    LIMIT = 30   # 방법마다 문제당 계산 시간 상한 (초)
    print("[기본 예제]")
    base = compare(JOBS, seconds=LIMIT)
    print(f"  CP-SAT {base['cp']['peak']} kW ({base['cp']['seconds']:.2f}s) | "
          f"MIP {base['mip']['peak']} kW ({base['mip']['seconds']:.2f}s, 변수 {base['mip']['n_vars']}, 제약 {base['mip']['n_cons']})")

    print("[무작위 예제 10개]")
    rng = random.Random(7)
    rand = []
    for i in range(10):
        r = compare(random_instance(rng), seconds=LIMIT)
        rand.append(r)
        print(f"  {i + 1:2d} CP {r['cp']['peak']} ({r['cp']['seconds']:.2f}s) | MIP {r['mip']['peak']} ({r['mip']['seconds']:.2f}s) {r['mip']['status']}")

    print("[문제 크기 늘리기]")
    scale = []
    for n in (3, 4, 6, 8, 10):
        jobs = random_instance(random.Random(100 + n), n_jobs=n)
        r = compare(jobs, seconds=LIMIT)
        r["n_jobs"] = n
        scale.append(r)
        print(f"  작업 {n:2d}개: CP {r['cp']['peak']} {r['cp']['status']} ({r['cp']['seconds']:.2f}s) | "
              f"MIP {r['mip']['peak']} {r['mip']['status']} ({r['mip']['seconds']:.2f}s, 변수 {r['mip']['n_vars']})")

    same = sum(1 for r in rand if r["cp"]["peak"] == r["mip"]["peak"])
    summary = dict(time_limit_s=LIMIT, same_optimum=f"{same}/{len(rand)}",
                   cp_proved=sum(r["cp"]["status"] == "OPTIMAL" for r in rand),
                   mip_proved=sum(r["mip"]["status"] == "OPTIMAL" for r in rand),
                   cp_median_s=statistics.median(r["cp"]["seconds"] for r in rand),
                   mip_median_s=statistics.median(r["mip"]["seconds"] for r in rand))
    print("\n[요약]", summary)
    json.dump(dict(summary=summary, base=base, random=rand, scale=scale),
              open("mip_compare.json", "w"), ensure_ascii=False, indent=1, default=str)
    plot(base, rand, scale)
