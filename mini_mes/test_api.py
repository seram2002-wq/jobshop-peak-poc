"""API 동작 확인 (pytest 없이도 실행 가능: python test_api.py)"""
import os
os.environ["MES_DB"] = os.path.join(os.path.dirname(__file__), "test_mes.db")
if os.path.exists(os.environ["MES_DB"]):
    os.remove(os.environ["MES_DB"])
from fastapi.testclient import TestClient  # noqa: E402
from api import app  # noqa: E402

c = TestClient(app)


def test_flow():
    assert c.get("/health").json() == {"status": "ok"}
    assert len(c.get("/orders").json()) == 6
    r = c.post("/optimize_schedule", json={"objective": "peak"}).json()
    assert r["baseline"]["peak_kw"] == 180 and r["optimized"]["peak_kw"] == 165
    assert r["optimized"]["makespan_min"] <= r["baseline"]["makespan_min"]
    # 같은 설비에 공정이 겹치지 않는지
    by_m = {}
    for it in r["optimized"]["items"]:
        by_m.setdefault(it["machine"], []).append((it["start_min"], it["end_min"]))
    for spans in by_m.values():
        spans.sort()
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    # 작업 추가 → 다시 최적화
    new = {"job_id": "J7", "product": "샤프트 G", "operations": [
        {"machine": "프레스", "duration_min": 60, "power_kw": 55},
        {"machine": "검사", "duration_min": 30, "power_kw": 10}]}
    assert c.post("/orders", json=new).status_code == 201
    assert c.post("/orders", json=new).status_code == 409
    assert c.post("/optimize_schedule", json={"objective": "peak"}).status_code == 200
    # 점검 중 설비가 있으면 최적화 거부
    c.patch("/machines/2", json={"status": "점검 중"})
    assert c.post("/optimize_schedule", json={}).status_code == 409
    c.patch("/machines/2", json={"status": "가동 가능"})
    assert len(c.get("/schedules").json()) == 4
    assert c.delete("/orders/J7").status_code == 200


if __name__ == "__main__":
    test_flow()
    print("모든 테스트 통과")
