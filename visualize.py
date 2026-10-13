"""result.json을 읽어 간트 차트와 전력 부하 그래프를 그린다."""
import json, datetime as dt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for f in font_manager.findSystemFonts():
    if "NotoSansCJK-Regular" in f:
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

R = json.load(open("result.json"))
SLOT, BASE, MACH = R["slot_min"], R["base_load"], R["machines"]
COLORS = {"J1": "#2b5f9e", "J2": "#d9622b", "J3": "#0f9488", "J4": "#7a5195", "J5": "#c9a227", "J6": "#5b6570"}
h = lambda t: t * SLOT / 60


def profile(rows, n):
    p = [BASE] * n
    for r in rows:
        for t in range(r["start"], r["end"]):
            p[t] += r["power"]
    return p


def gantt(ax, sched, title):
    for r in sched["rows"]:
        y = MACH.index(r["machine"])
        ax.barh(y, h(r["end"] - r["start"]), left=h(r["start"]), height=0.6,
                color=COLORS[r["job"]], edgecolor="white")
        ax.text(h(r["start"] + r["end"]) / 2, y, f'{r["job"]}', ha="center", va="center",
                color="white", fontsize=9, fontweight="bold")
    ax.set_yticks(range(len(MACH)), MACH)
    ax.invert_yaxis()
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)


n = max(R["base"]["makespan"], R["opt"]["makespan"])
fig, axes = plt.subplots(3, 1, figsize=(11, 8.5), sharex=True,
                         gridspec_kw={"height_ratios": [1, 1, 1.1]})
gantt(axes[0], R["base"], f'기준 일정 (선착순 규칙) · 피크 {R["base_peak"]} kW')
gantt(axes[1], R["opt"], f'최적 일정 (CP-SAT) · 피크 {R["opt_peak"]} kW')
pb, po = profile(R["base"]["rows"], n), profile(R["opt"]["rows"], n)
xs = [h(t) for t in range(n + 1)]
axes[2].step(xs, pb + [pb[-1]], where="post", color="#b3bdcc", lw=2.5, label="기준 일정")
axes[2].step(xs, po + [po[-1]], where="post", color="#18212b", lw=2.5, label="최적 일정")
axes[2].axhline(R["base_peak"], color="#b3bdcc", ls="--", lw=1)
axes[2].axhline(R["opt_peak"], color="#d9622b", ls="--", lw=1)
axes[2].set_title("시간별 전력 부하 (kW)", loc="left", fontsize=12, fontweight="bold")
axes[2].set_xlabel("시간 (h)")
axes[2].legend(loc="upper right", frameon=False)
axes[2].grid(alpha=0.3)
for a in axes:
    for s in ("top", "right"):
        a.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig("schedule_comparison.png", dpi=160)

# Plotly 인터랙티브 간트 (README·면접 시연용)
try:
    import plotly.express as px
    t0 = dt.datetime(2026, 1, 5, 8, 0)
    recs = []
    for label, key in (("기준", "base"), ("최적", "opt")):
        for r in R[key]["rows"]:
            recs.append(dict(일정=label, 설비=f'{label} · {r["machine"]}', 작업=r["job"],
                             시작=t0 + dt.timedelta(minutes=r["start"] * SLOT),
                             종료=t0 + dt.timedelta(minutes=r["end"] * SLOT), 전력kW=r["power"]))
    figp = px.timeline(recs, x_start="시작", x_end="종료", y="설비", color="작업",
                       hover_data=["전력kW"], color_discrete_map=COLORS,
                       title=f'Job-Shop 일정 비교 · 피크 {R["base_peak"]} → {R["opt_peak"]} kW')
    figp.update_yaxes(autorange="reversed")
    figp.write_html("gantt_interactive.html")
except ImportError:
    pass
print("saved")
