"""
추가 검증 실험 (jobshop_peak.py의 모델을 그대로 사용)

1) 무작위 예제 50개: 예제 하나의 결과가 우연이 아닌지 확인
   - 설비 4대, 작업 6개, 작업마다 3~4개 공정
   - 공정 소요 시간 1~4칸(30분 단위), 설비별 전력 범위에서 무작위 추출
   - 선착순 규칙 vs CP-SAT 피크 최소화 (완료 시간은 선착순 규칙 이하로 제한)
2) 트레이드오프 곡선: 기본 예제에서 허용 완료 시간을 늘려 갈 때 최소 피크가 어떻게 바뀌는지
"""
import json, random, statistics
from jobshop_peak import (JOBS, MACHINES, BASE_LOAD, SLOT_MIN,
                          solve, greedy_schedule, load_profile)

# 설비별 가동 전력 범위 (kW)
POWER_RANGE = {0: (50, 65), 1: (35, 50), 2: (25, 40), 3: (8, 15)}


def random_instance(rng, n_jobs=6):
    jobs = {}
    for j in range(n_jobs):
        n_ops = rng.choice([3, 4])
        machines = rng.sample(range(len(MACHINES)), n_ops)   # 작업마다 공정 순서가 다름
        jobs[f"J{j + 1}"] = [(m, rng.randint(1, 4), rng.randint(*POWER_RANGE[m])) for m in machines]
    return jobs


def peak_of(sched):
    return max(load_profile(sched["rows"], sched["makespan"]))


def random_experiment(n=50, seed=42, seconds=10):
    rng = random.Random(seed)
    results = []
    for i in range(n):
        jobs = random_instance(rng)
        g = greedy_schedule(jobs)
        o = solve("peak", {"makespan": ("<=", g["makespan"])}, seconds=seconds, jobs=jobs)
        gp, op = peak_of(g), peak_of(o)
        results.append(dict(id=i, greedy_peak=gp, opt_peak=op,
                            reduction_kw=gp - op, reduction_pct=(gp - op) / gp * 100,
                            makespan=g["makespan"], status=o["status"]))
        print(f"[{i + 1:2d}/{n}] 피크 {gp} → {op} kW ({(gp - op) / gp:.1%}) {o['status']}")
    return results


def tradeoff_curve(seconds=20):
    fastest = solve("makespan", seconds=seconds)              # 가장 빠른 완료 시간
    greedy = greedy_schedule()
    points = []
    for limit in range(fastest["makespan"], fastest["makespan"] + 11):   # +5시간까지
        o = solve("peak", {"makespan": ("<=", limit)}, seconds=seconds)
        points.append(dict(limit_h=limit * SLOT_MIN / 60, peak=peak_of(o), status=o["status"]))
        print(f"완료 시간 ≤ {limit * SLOT_MIN / 60:.1f}h → 최소 피크 {points[-1]['peak']} kW")
    return dict(points=points,
                greedy=dict(makespan_h=greedy["makespan"] * SLOT_MIN / 60, peak=peak_of(greedy)))


def plot(rand, curve):
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

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    pct = [r["reduction_pct"] for r in rand]
    ax = axes[0]
    ax.hist(pct, bins=range(0, int(max(pct)) + 3, 2), color="#2b5f9e", edgecolor="white")
    ax.axvline(statistics.mean(pct), color="#d9622b", lw=2, label=f"평균 {statistics.mean(pct):.1f}%")
    ax.set_title(f"무작위 예제 {len(rand)}개 · 선착순 규칙 대비 피크 감소율", loc="left", fontweight="bold")
    ax.set_xlabel("피크 감소율 (%)")
    ax.set_ylabel("예제 수")
    ax.legend(frameon=False)

    ax = axes[1]
    xs = [p["limit_h"] for p in curve["points"]]
    ys = [p["peak"] for p in curve["points"]]
    ax.step(xs, ys, where="post", color="#18212b", lw=2.5, marker="o", label="CP-SAT 최소 피크")
    g = curve["greedy"]
    ax.scatter([g["makespan_h"]], [g["peak"]], s=120, color="#d9622b", zorder=5, label="선착순 규칙")
    ax.set_title("허용 완료 시간과 최소 피크의 트레이드오프", loc="left", fontweight="bold")
    ax.set_xlabel("허용 완료 시간 (h)")
    ax.set_ylabel("전력 피크 (kW)")
    ax.legend(frameon=False)
    for a in axes:
        a.grid(alpha=0.3)
        a.set_axisbelow(True)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig("experiments.png", dpi=160)


if __name__ == "__main__":
    rand = random_experiment()
    curve = tradeoff_curve()
    pct = [r["reduction_pct"] for r in rand]
    summary = dict(n=len(rand), mean_pct=statistics.mean(pct), median_pct=statistics.median(pct),
                   min_pct=min(pct), max_pct=max(pct),
                   improved=sum(1 for r in rand if r["reduction_kw"] > 0),
                   optimal=sum(1 for r in rand if r["status"] == "OPTIMAL"))
    print("\n[요약]", json.dumps(summary, ensure_ascii=False))
    json.dump(dict(summary=summary, random=rand, tradeoff=curve),
              open("experiments.json", "w"), ensure_ascii=False, indent=1)
    plot(rand, curve)
