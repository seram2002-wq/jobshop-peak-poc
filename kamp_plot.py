"""kamp_reschedule_summary.csv로 규칙 vs LP 비교 그림을 그린다."""
import pandas as pd
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

r = pd.read_csv("kamp_reschedule_summary.csv")
get = lambda p, m, x: r[(r.period == p) & (r.method == m) & (r.x == x)]["max_after"].iloc[0]
periods = [("2021-07", "7월 (검증)"), ("2021-08", "8월 (검증)"), ("test", "9/1~14 (test)")]
series = [("조정 전", 0, "#c9cfd6"), ("규칙 (M3 예측)", 0.2, "#d9622b"),
          ("LP (M3 예측)", 0.2, "#18212b"), ("LP (완벽 예측)", 0.2, "#2b5f9e")]

fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))
ax = axes[0]
w = 0.2
for i, (m, x, c) in enumerate(series):
    vals = [get(p, m, x) for p, _ in periods]
    xs = [k + (i - 1.5) * w for k in range(len(periods))]
    ax.bar(xs, vals, w, color=c, label=m if m == "조정 전" else f"{m}")
    for xx, v in zip(xs, vals):
        ax.text(xx, v + 1, f"{v:.0f}", ha="center", fontsize=8)
ax.set_xticks(range(len(periods)), [l for _, l in periods])
ax.set_ylim(150, 240)
ax.axhline(179, color="#5b6570", ls="--", lw=1)
ax.set_title("부하 20% 이동 시 최대수요 (kW)", loc="left", fontweight="bold")
ax.legend(frameon=False, fontsize=9, ncol=2, loc="upper right")

ax = axes[1]
xs = [5, 10, 20]
for m, c, ls in [("규칙 (M3 예측)", "#d9622b", "-"), ("LP (M3 예측)", "#18212b", "-"),
                 ("규칙 (완벽 예측)", "#d9622b", ":"), ("LP (완벽 예측)", "#2b5f9e", ":")]:
    ax.plot(xs, [get("test", m, x / 100) for x in xs], color=c, ls=ls, marker="o", lw=2.2, label=m)
ax.axhline(204, color="#c9cfd6", lw=1.5, label="조정 전 204")
ax.axhline(179, color="#5b6570", ls="--", lw=1)
ax.set_xticks(xs, [f"{x}%" for x in xs])
ax.set_xlabel("이동 비율")
ax.set_title("test 기간 · 이동 비율별 최대수요 (kW)", loc="left", fontweight="bold")
ax.legend(frameon=False, fontsize=9)
for a in axes:
    a.grid(alpha=0.3, axis="y")
    a.set_axisbelow(True)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig("kamp_reschedule.png", dpi=160)
print("saved")
