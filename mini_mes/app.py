"""
미니 MES 관리자 화면 (Streamlit)

실행:  streamlit run app.py          (mini_mes 폴더, API 서버를 먼저 켜 두기)
"""
import datetime as dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="Mini MES · 전력 피크 스케줄링", layout="wide")
COLORS = px.colors.qualitative.Bold
T0 = dt.datetime(2026, 1, 5, 8, 0)   # 간트 차트 기준 시각 (08:00 시작)

api = st.sidebar.text_input("API 주소", "http://127.0.0.1:8000")


def call(method, path, **kw):
    try:
        r = requests.request(method, api + path, timeout=90, **kw)
    except requests.ConnectionError:
        st.error("API 서버에 연결할 수 없습니다. `uvicorn api:app --reload`로 먼저 켜 주세요.")
        st.stop()
    if r.status_code >= 400:
        st.error(r.json().get("detail", r.text))
        return None
    return r.json()


st.sidebar.success("API 연결됨") if call("GET", "/health") else None
st.title("Mini MES · 전력 피크를 고려한 생산 스케줄링")
st.caption("DB의 작업 지시 → OR-Tools 최적화 API → 관리자 화면. 가상 공장 예제입니다.")


def gantt(items, title):
    df = pd.DataFrame(items)
    df["시작"] = df["start_min"].apply(lambda m: T0 + dt.timedelta(minutes=m))
    df["종료"] = df["end_min"].apply(lambda m: T0 + dt.timedelta(minutes=m))
    fig = px.timeline(df, x_start="시작", x_end="종료", y="machine", color="job_id", text="job_id",
                      hover_data={"power_kw": True}, color_discrete_sequence=COLORS, title=title)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="작업")
    return fig


def profile(items, base):
    end = max(i["end_min"] for i in items)
    ts = list(range(0, end, 30))
    load = [base + sum(i["power_kw"] for i in items if i["start_min"] <= t < i["end_min"]) for t in ts]
    return [T0 + dt.timedelta(minutes=t) for t in ts], load


tab1, tab2, tab3 = st.tabs(["작업 지시", "스케줄 최적화", "실행 기록"])

# ---------------- 작업 지시 ----------------
with tab1:
    left, right = st.columns([3, 2])
    orders = call("GET", "/orders") or []
    with left:
        st.subheader("작업 지시와 공정")
        flat = [{"작업": o["job_id"], "제품": o["product"], "순서": p["seq"], "설비": p["machine"],
                 "소요(분)": p["duration_min"], "전력(kW)": p["power_kw"]}
                for o in orders for p in o["operations"]]
        st.dataframe(pd.DataFrame(flat), hide_index=True, width="stretch", height=360)
        if orders:
            target = st.selectbox("삭제할 작업", [o["job_id"] for o in orders])
            if st.button("작업 삭제"):
                if call("DELETE", f"/orders/{target}"):
                    st.rerun()
    with right:
        st.subheader("설비 상태")
        machines = call("GET", "/machines") or []
        for m in machines:
            c1, c2 = st.columns([2, 2])
            c1.write(f"**{m['name']}**")
            new = c2.selectbox("상태", ["가동 가능", "점검 중"], index=0 if m["status"] == "가동 가능" else 1,
                               key=f"m{m['id']}", label_visibility="collapsed")
            if new != m["status"]:
                call("PATCH", f"/machines/{m['id']}", json={"status": new})
                st.rerun()
        st.subheader("작업 지시 추가")
        with st.form("new_order", clear_on_submit=True):
            job_id = st.text_input("작업 번호", placeholder="예: J7")
            product = st.text_input("제품명", placeholder="예: 샤프트 G")
            ops = st.data_editor(
                pd.DataFrame([{"설비": "프레스", "소요(분)": 60, "전력(kW)": 55},
                              {"설비": "검사", "소요(분)": 30, "전력(kW)": 10}]),
                num_rows="dynamic", hide_index=True,
                column_config={"설비": st.column_config.SelectboxColumn(options=[m["name"] for m in machines]),
                               "소요(분)": st.column_config.NumberColumn(min_value=30, step=30)})
            if st.form_submit_button("등록"):
                body = {"job_id": job_id, "product": product,
                        "operations": [{"machine": r["설비"], "duration_min": int(r["소요(분)"]),
                                        "power_kw": int(r["전력(kW)"])} for _, r in ops.dropna().iterrows()]}
                if call("POST", "/orders", json=body):
                    st.success(f"{job_id} 등록 완료")
                    st.rerun()

# ---------------- 스케줄 최적화 ----------------
with tab2:
    c1, c2, c3 = st.columns([2, 2, 1])
    objective = c1.radio("목표", ["peak", "makespan"], horizontal=True,
                         format_func=lambda x: "전력 피크 최소화" if x == "peak" else "완료 시간 최소화")
    extra = c2.slider("선착순 규칙 대비 허용할 추가 완료 시간(분)", 0, 180, 0, 30, disabled=objective != "peak")
    if c3.button("스케줄 최적화 실행", type="primary", width="stretch"):
        with st.spinner("OR-Tools CP-SAT으로 계산 중..."):
            st.session_state["result"] = call("POST", "/optimize_schedule",
                                              json={"objective": objective, "extra_minutes": extra})
    res = st.session_state.get("result")
    if res:
        b, o = res["baseline"], res["optimized"]
        m1, m2, m3 = st.columns(3)
        m1.metric("전력 피크", f"{o['peak_kw']} kW", f"{o['peak_kw'] - b['peak_kw']} kW", delta_color="inverse")
        m2.metric("완료 시간", f"{o['makespan_min'] / 60:.1f} 시간",
                  f"{(o['makespan_min'] - b['makespan_min']) / 60:+.1f} 시간", delta_color="inverse")
        m3.metric("최적화 상태", o["status"])
        st.plotly_chart(gantt(b["items"], f"선착순 규칙 · 피크 {b['peak_kw']} kW"), width="stretch")
        st.plotly_chart(gantt(o["items"], f"CP-SAT 최적 일정 · 피크 {o['peak_kw']} kW"), width="stretch")
        fig = go.Figure()
        for name, s, color in [("선착순 규칙", b, "#b3bdcc"), ("최적 일정", o, "#18212b")]:
            x, y = profile(s["items"], res["base_load_kw"])
            fig.add_trace(go.Scatter(x=x, y=y, name=name, line_shape="hv", line=dict(color=color, width=3)))
        fig.update_layout(title="시간별 전력 부하 (kW)", height=320, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")

# ---------------- 실행 기록 ----------------
with tab3:
    runs = call("GET", "/schedules") or []
    if runs:
        st.dataframe(pd.DataFrame(runs).rename(columns={
            "run_id": "실행", "created_at": "시각", "method": "방식", "makespan_min": "완료(분)",
            "peak_kw": "피크(kW)", "status": "상태"}), hide_index=True, width="stretch")
        rid = st.selectbox("일정 보기", [r["run_id"] for r in runs])
        run = call("GET", f"/schedules/{rid}")
        if run:
            st.plotly_chart(gantt(run["items"], f"실행 {rid} · {run['method']} · 피크 {run['peak_kw']} kW"),
                            width="stretch")
    else:
        st.info("아직 실행 기록이 없습니다. '스케줄 최적화' 탭에서 실행해 보세요.")
