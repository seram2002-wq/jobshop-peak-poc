"""
미니 MES 데이터베이스 (SQLite)

테이블
  machines        설비 (이름, 상태)
  orders          작업 지시 (작업 번호, 제품, 납기 메모)
  operations      작업별 공정 (순서, 설비, 소요 시간, 가동 전력)
  schedule_runs   최적화 실행 기록 (방식, 완료 시간, 피크, 실행 시각)
  schedule_items  실행별 공정 일정 (시작, 종료)
"""
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("MES_DB", os.path.join(os.path.dirname(__file__), "mes.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT '가동 가능'
);
CREATE TABLE IF NOT EXISTS orders (
    job_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS operations (
    job_id TEXT NOT NULL REFERENCES orders(job_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    duration_min INTEGER NOT NULL CHECK (duration_min > 0 AND duration_min % 30 = 0),
    power_kw INTEGER NOT NULL CHECK (power_kw >= 0),
    PRIMARY KEY (job_id, seq)
);
CREATE TABLE IF NOT EXISTS schedule_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    method TEXT NOT NULL,
    makespan_min INTEGER NOT NULL,
    peak_kw INTEGER NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_items (
    run_id INTEGER NOT NULL REFERENCES schedule_runs(run_id) ON DELETE CASCADE,
    job_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    machine TEXT NOT NULL,
    start_min INTEGER NOT NULL,
    end_min INTEGER NOT NULL,
    power_kw INTEGER NOT NULL
);
"""

# 초기 데이터: jobshop_peak.py의 가상 공장 예제와 같은 값 (소요 시간은 분 단위)
SEED_MACHINES = ["프레스", "용접", "도장", "검사"]
SEED_ORDERS = {
    "J1": ("브래킷 A", [(0, 90, 55), (1, 60, 40), (2, 90, 35), (3, 30, 10)]),
    "J2": ("프레임 B", [(1, 90, 45), (0, 60, 60), (3, 60, 10), (2, 60, 30)]),
    "J3": ("커버 C", [(0, 60, 50), (2, 120, 35), (1, 60, 40), (3, 30, 10)]),
    "J4": ("하우징 D", [(2, 60, 30), (1, 90, 45), (0, 90, 55), (3, 30, 10)]),
    "J5": ("패널 E", [(0, 120, 60), (1, 60, 40), (3, 60, 10), (2, 60, 30)]),
    "J6": ("레일 F", [(1, 60, 40), (2, 90, 35), (0, 60, 50), (3, 60, 10)]),
}


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(reset=False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with connect() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM machines").fetchone()[0] == 0:
            con.executemany("INSERT INTO machines (id, name) VALUES (?, ?)",
                            list(enumerate(SEED_MACHINES)))
            for job, (product, ops) in SEED_ORDERS.items():
                con.execute("INSERT INTO orders (job_id, product) VALUES (?, ?)", (job, product))
                con.executemany(
                    "INSERT INTO operations (job_id, seq, machine_id, duration_min, power_kw) VALUES (?, ?, ?, ?, ?)",
                    [(job, k + 1, m, d, p) for k, (m, d, p) in enumerate(ops)])


if __name__ == "__main__":
    init_db(reset=True)
    print(f"초기화 완료: {DB_PATH}")
