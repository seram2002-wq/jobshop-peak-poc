"""
미니 MES 최적화 API 서버 (FastAPI)

실행:  uvicorn api:app --reload        (mini_mes 폴더에서)
문서:  http://127.0.0.1:8000/docs

흐름:  DB의 작업 지시·공정 → OR-Tools 최적화(jobshop_peak.py) → 일정 저장 → JSON 반환
"""
import os
import sys
from typing import List, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jobshop_peak as jp   # noqa: E402  (상위 폴더의 최적화 모델 재사용)
from db import connect, init_db   # noqa: E402

SLOT = jp.SLOT_MIN   # 30분
app = FastAPI(title="Mini MES · Peak-aware Scheduling API", version="0.1.0")
init_db()


# ---------------- 요청·응답 형식 ----------------
class OperationIn(BaseModel):
    machine: str
    duration_min: int = Field(gt=0, multiple_of=30, description="30분 단위")
    power_kw: int = Field(ge=0)


class OrderIn(BaseModel):
    job_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,10}$")
    product: str
    operations: List[OperationIn] = Field(min_length=1)


class OptimizeIn(BaseModel):
    objective: Literal["peak", "makespan"] = "peak"
    extra_minutes: int = Field(0, ge=0, multiple_of=30, description="피크 최소화 시 선착순 규칙 대비 허용할 추가 완료 시간")
    time_limit_s: int = Field(10, ge=1, le=60)


class MachineStatusIn(BaseModel):
    status: Literal["가동 가능", "점검 중"]


# ---------------- 조회 ----------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/machines")
def list_machines():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT id, name, status FROM machines ORDER BY id")]


@app.patch("/machines/{machine_id}")
def update_machine(machine_id: int, body: MachineStatusIn):
    with connect() as con:
        cur = con.execute("UPDATE machines SET status = ? WHERE id = ?", (body.status, machine_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "설비가 없습니다")
    return {"id": machine_id, "status": body.status}


@app.get("/orders")
def list_orders():
    with connect() as con:
        rows = con.execute("""
            SELECT o.job_id, o.product, p.seq, m.name AS machine, p.duration_min, p.power_kw
            FROM orders o JOIN operations p ON o.job_id = p.job_id JOIN machines m ON m.id = p.machine_id
            ORDER BY o.job_id, p.seq""").fetchall()
    orders = {}
    for r in rows:
        o = orders.setdefault(r["job_id"], {"job_id": r["job_id"], "product": r["product"], "operations": []})
        o["operations"].append({"seq": r["seq"], "machine": r["machine"],
                                "duration_min": r["duration_min"], "power_kw": r["power_kw"]})
    return list(orders.values())


# ---------------- 작업 지시 등록·삭제 ----------------
@app.post("/orders", status_code=201)
def create_order(order: OrderIn):
    with connect() as con:
        mid = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM machines")}
        unknown = [op.machine for op in order.operations if op.machine not in mid]
        if unknown:
            raise HTTPException(400, f"없는 설비: {unknown}. 가능한 설비: {list(mid)}")
        if con.execute("SELECT 1 FROM orders WHERE job_id = ?", (order.job_id,)).fetchone():
            raise HTTPException(409, f"이미 있는 작업 번호: {order.job_id}")
        con.execute("INSERT INTO orders (job_id, product) VALUES (?, ?)", (order.job_id, order.product))
        con.executemany(
            "INSERT INTO operations (job_id, seq, machine_id, duration_min, power_kw) VALUES (?, ?, ?, ?, ?)",
            [(order.job_id, k + 1, mid[op.machine], op.duration_min, op.power_kw)
             for k, op in enumerate(order.operations)])
    return {"job_id": order.job_id}


@app.delete("/orders/{job_id}")
def delete_order(job_id: str):
    with connect() as con:
        cur = con.execute("DELETE FROM orders WHERE job_id = ?", (job_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "작업이 없습니다")
    return {"deleted": job_id}


# ---------------- 최적화 ----------------
def _load_jobs():
    """DB → jobshop_peak 형식 {job: [(설비 번호, 칸 수, kW), ...]}"""
    with connect() as con:
        down = [r["name"] for r in con.execute("SELECT name FROM machines WHERE status = '점검 중'")]
        rows = con.execute("""SELECT p.job_id, p.seq, p.machine_id, m.name, p.duration_min, p.power_kw
                              FROM operations p JOIN machines m ON m.id = p.machine_id
                              ORDER BY p.job_id, p.seq""").fetchall()
    if not rows:
        raise HTTPException(400, "등록된 작업 지시가 없습니다")
    blocked = sorted({r["job_id"] for r in rows if r["name"] in down})
    if blocked:
        raise HTTPException(409, f"점검 중인 설비({', '.join(down)})를 쓰는 작업이 있습니다: {blocked}")
    jobs = {}
    for r in rows:
        jobs.setdefault(r["job_id"], []).append((r["machine_id"], r["duration_min"] // SLOT, r["power_kw"]))
    return jobs


def _summary(sched):
    peak = max(jp.load_profile(sched["rows"], sched["makespan"]))
    return {"makespan_min": sched["makespan"] * SLOT, "peak_kw": int(peak), "status": sched["status"],
            "items": [{"job_id": r["job"], "seq": r["op"], "machine": r["machine"],
                       "start_min": r["start"] * SLOT, "end_min": r["end"] * SLOT, "power_kw": r["power"]}
                      for r in sorted(sched["rows"], key=lambda r: (r["machine"], r["start"]))]}


def _save(method, s):
    with connect() as con:
        cur = con.execute("INSERT INTO schedule_runs (method, makespan_min, peak_kw, status) VALUES (?, ?, ?, ?)",
                          (method, s["makespan_min"], s["peak_kw"], s["status"]))
        run_id = cur.lastrowid
        con.executemany("""INSERT INTO schedule_items (run_id, job_id, seq, machine, start_min, end_min, power_kw)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        [(run_id, i["job_id"], i["seq"], i["machine"], i["start_min"], i["end_min"], i["power_kw"])
                         for i in s["items"]])
    return run_id


@app.post("/optimize_schedule")
def optimize_schedule(req: OptimizeIn):
    jobs = _load_jobs()
    greedy = jp.greedy_schedule(jobs)
    if req.objective == "peak":
        limit = greedy["makespan"] + req.extra_minutes // SLOT
        step1 = jp.solve("peak", {"makespan": ("<=", limit)}, seconds=req.time_limit_s, jobs=jobs)
        peak = max(jp.load_profile(step1["rows"], step1["makespan"])) - jp.BASE_LOAD
        opt = jp.solve("makespan", {"peak": ("<=", peak)}, seconds=req.time_limit_s, jobs=jobs)
    else:
        opt = jp.solve("makespan", seconds=req.time_limit_s, jobs=jobs)
    base_s, opt_s = _summary(greedy), _summary(opt)
    base_s["run_id"] = _save("선착순 규칙", base_s)
    opt_s["run_id"] = _save(f"CP-SAT ({'피크 최소화' if req.objective == 'peak' else '완료 시간 최소화'})", opt_s)
    return {"objective": req.objective, "base_load_kw": jp.BASE_LOAD, "baseline": base_s, "optimized": opt_s,
            "peak_reduction_kw": base_s["peak_kw"] - opt_s["peak_kw"]}


@app.get("/schedules")
def list_runs(limit: int = 20):
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM schedule_runs ORDER BY run_id DESC LIMIT ?", (limit,))]


@app.get("/schedules/{run_id}")
def get_run(run_id: int):
    with connect() as con:
        run = con.execute("SELECT * FROM schedule_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "실행 기록이 없습니다")
        items = [dict(r) for r in con.execute(
            "SELECT * FROM schedule_items WHERE run_id = ? ORDER BY machine, start_min", (run_id,))]
    return {**dict(run), "items": items}
