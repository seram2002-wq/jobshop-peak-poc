"""
경진대회 실제 데이터에 적용: 하루 전 일정 조정을 '고정 비율 규칙' 대신 '선형계획(LP)'으로

데이터: data/kamp_dayahead.csv
  경진대회(KAMP 자원 최적화 데이터) 결과에서 하루 전 예측(M3, LightGBM + 가동 계획)과
  실제 전력, 가동 계획, 받는 시간의 예상 부하를 시간 단위로 가져온 표
  (원본: github.com/SeoHyun1024/kamp-resource-optimization-benchmark, 11_schedule_simulation.py 입력과 동일)
  - 7·8월: 교차검증(OOF) 예측, test: 2021-09-01~09-14

비교
  [규칙] 경진대회 방식 그대로: M3 예측이 168kW 이상인 시간(경보)의 부하 x%를
         같은 날 경보가 없는 가동 시간 중 예상 부하가 낮은 순으로 옮김
  [LP]   같은 정보(하루 전 예측)와 같은 한도 안에서, '그날의 예상 최대 부하'를 최소화하도록
         어느 시간에서 얼마를 빼고 어디에 넣을지를 한꺼번에 결정

두 방법 모두 하루 전 예측으로 이동량을 정하고, 같은 이동량을 실제 전력에 적용해 평가한다.
같은 날 안에서만 옮기므로 하루 총부하는 그대로다.
"""
import numpy as np
import pandas as pd
from ortools.linear_solver import pywraplp

PEAK = 179.0          # 피크 기준 (kW)
CAP = PEAK - 1.0      # 받는 시간은 피크 기준보다 한 단위 아래까지만 채움 (경진대회 규칙과 동일)
X_GRID = [0.05, 0.10, 0.20]


# ---------------- 경진대회 규칙 (11_schedule_simulation.py의 하루 전 규칙을 옮김) ----------------
def rule_day(actual, expected, on, alert, x):
    adj = actual.astype(float).copy()
    received = np.zeros(len(adj))
    moves = np.zeros(len(adj))
    for h in np.flatnonzero(alert):
        left = x * adj[h]
        cand = [j for j in range(len(adj)) if on[j] and not alert[j]]
        for j in sorted(cand, key=lambda j: (expected[j], j)):
            if left <= 1e-9:
                break
            room = min(CAP - (expected[j] + received[j]), x * expected[j] - received[j])
            if room <= 1e-9:
                continue
            amt = min(left, room)
            adj[h] -= amt; adj[j] += amt; received[j] += amt; left -= amt
            moves[h] += amt
    return adj, moves.sum()


# ---------------- 선형계획 ----------------
def lp_day(forecast, expected, on, x, eps=1e-3):
    """하루 24시간. out[h]: h에서 빼는 양, inn[h]: h에 넣는 양 (kW).
    최소화: 그날 계획상 최대 부하 M  (+ 불필요한 이동을 막는 작은 비용)
    제약:
      out[h] <= x * 예측[h]                       (한 시간에서 뺄 수 있는 양, 가동 시간만)
      inn[h] <= x * 예상[h],  예상[h] + inn[h] <= CAP  (받는 한도, 경진대회 규칙과 동일)
      sum(out) == sum(inn)                         (같은 날 안에서 옮기기만 함)
      예상[h] - out[h] + inn[h] <= M               (계획상 부하)
    """
    s = pywraplp.Solver.CreateSolver("GLOP")
    n = len(forecast)
    out = [s.NumVar(0, x * forecast[h] if on[h] else 0, f"out{h}") for h in range(n)]
    inn = [s.NumVar(0, max(0.0, min(x * expected[h], CAP - expected[h])) if on[h] else 0, f"in{h}")
           for h in range(n)]
    M = s.NumVar(0, s.infinity(), "M")
    s.Add(sum(out) == sum(inn))
    for h in range(n):
        s.Add(expected[h] - out[h] + inn[h] <= M)
    s.Minimize(M + eps * sum(out))
    assert s.Solve() == pywraplp.Solver.OPTIMAL
    return np.array([out[h].solution_value() for h in range(n)]), np.array([inn[h].solution_value() for h in range(n)])


def run(df, method, x, perfect=False):
    after = []
    moved = 0.0
    for _, g in df.groupby(df["Date"].dt.normalize()):
        a = g["power"].to_numpy(float)
        on = g["planned_on"].to_numpy(bool)
        # 완벽 예측(상한): 예측 대신 실제 전력을 안다고 가정
        fc = a if perfect else g["m3_forecast"].to_numpy(float)
        ex = a if perfect else g["expected"].to_numpy(float)
        if method == "rule":
            alert = (a >= PEAK) if perfect else g["m3_alert"].to_numpy(bool)
            adj, mv = rule_day(a, ex, on, alert, x)
        else:
            o, i = lp_day(fc, ex, on, x)
            adj, mv = a - o + i, o.sum()
        after.append(adj)
        moved += mv
    after = np.concatenate(after)
    before = df["power"].to_numpy(float)
    return dict(max_after=after.max(), peaks_after=int((after >= PEAK).sum()),
                new_peaks=int(((after >= PEAK) & (before < PEAK)).sum()), moved_kw=moved), after


if __name__ == "__main__":
    data = pd.read_csv("data/kamp_dayahead.csv", parse_dates=["Date"])
    rows, hourly = [], []
    for period, df in data.groupby("period", sort=False):
        df = df.sort_values("Date").reset_index(drop=True)
        base = dict(max_after=df["power"].max(), peaks_after=int((df["power"] >= PEAK).sum()), new_peaks=0, moved_kw=0.0)
        rows.append(dict(period=period, method="조정 전", x=0, **base))
        for x in X_GRID:
            for method, label, perfect in [("rule", "규칙 (M3 예측)", False), ("lp", "LP (M3 예측)", False),
                                           ("rule", "규칙 (완벽 예측)", True), ("lp", "LP (완벽 예측)", True)]:
                m, after = run(df, method, x, perfect)
                rows.append(dict(period=period, method=label, x=x, **m))
                if period == "test" and x == 0.10 and not perfect:
                    hourly.append(pd.DataFrame({"Date": df["Date"], "method": label, "before": df["power"], "after": after}))
    res = pd.DataFrame(rows)
    res.to_csv("kamp_reschedule_summary.csv", index=False, encoding="utf-8-sig")
    pd.concat(hourly).to_csv("kamp_reschedule_hourly_test.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 160)
    print(res.round(1).to_string(index=False))
