"""
Google OR-Tools 활용: Job-Shop 스케줄링 최적화 및 간트 차트 시각화
"""
import collections
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

def solve_job_shop():
    # 1. 데이터 정의 (Job 데이터: 각 튜플은 (기계 번호, 작업 소요 시간)을 의미)
    jobs_data = [
        [(0, 3), (1, 2), (2, 2)],  # Job 0: 기계0(3시간) -> 기계1(2시간) -> 기계2(2시간)
        [(0, 2), (2, 1), (1, 4)],  # Job 1: 기계0(2시간) -> 기계2(1시간) -> 기계1(4시간)
        [(1, 4), (2, 3)]           # Job 2: 기계1(4시간) -> 기계2(3시간)
    ]

    num_machines = 3
    all_machines = range(num_machines)
    all_jobs = range(len(jobs_data))

    # 최대 가능 시간 (모든 작업을 순서대로 했을 때의 합)
    horizon = sum(task[1] for job in jobs_data for task in job)

    model = cp_model.CpModel()

    # 2. 결정 변수 정의
    task_type = collections.namedtuple('task_type', 'start end interval')
    all_tasks = {}

    for job_id in all_jobs:
        for task_id, task in enumerate(jobs_data[job_id]):
            machine, duration = task[0], task[1]
            suffix = f'_j{job_id}_t{task_id}_m{machine}'
            
            start_var = model.NewIntVar(0, horizon, 'start' + suffix)
            end_var = model.NewIntVar(0, horizon, 'end' + suffix)
            interval_var = model.NewIntervalVar(start_var, duration, end_var, 'interval' + suffix)
            
            all_tasks[job_id, task_id] = task_type(start=start_var, end=end_var, interval=interval_var)

    # 3. 제약 조건 추가
    # 제약 1: 설비 용량 제약 (No-Overlap). 한 기계는 동시에 한 작업만 가능
    for machine in all_machines:
        machine_intervals = []
        for job_id in all_jobs:
            for task_id, task in enumerate(jobs_data[job_id]):
                if task[0] == machine:
                    machine_intervals.append(all_tasks[job_id, task_id].interval)
        model.AddNoOverlap(machine_intervals)

    # 제약 2: 공정 순서 제약 (Precedence). 이전 공정이 끝나야 다음 공정 시작 가능
    for job_id in all_jobs:
        for task_id in range(len(jobs_data[job_id]) - 1):
            model.Add(all_tasks[job_id, task_id + 1].start >= all_tasks[job_id, task_id].end)

    # 4. 목적 함수: 전체 공정 완료 시간(Makespan) 최소화
    obj_var = model.NewIntVar(0, horizon, 'makespan')
    model.AddMaxEquality(obj_var, [
        all_tasks[job_id, len(jobs_data[job_id]) - 1].end
        for job_id in all_jobs
    ])
    model.Minimize(obj_var)

    # 5. 솔버 실행
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    # 6. 시각화 데이터 추출
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f'최적 공정 완료 시간: {solver.ObjectiveValue()} 시간\n')
        
        schedule_data = []
        # Plotly 타임라인을 위해 임의의 기준 날짜 설정
        base_time = datetime(2026, 10, 14, 0, 0) 
        
        for job_id in all_jobs:
            for task_id, task in enumerate(jobs_data[job_id]):
                machine = task[0]
                start = solver.Value(all_tasks[job_id, task_id].start)
                end = solver.Value(all_tasks[job_id, task_id].end)
                
                # 데이터프레임용 데이터 적재
                schedule_data.append(dict(
                    Job=f"Job {job_id}",
                    Machine=f"Machine {machine}",
                    Start=base_time + timedelta(hours=start),
                    Finish=base_time + timedelta(hours=end),
                    Duration=end-start
                ))
                print(f'Job {job_id} 공정 {task_id} (기계 {machine}): {start}시작 -> {end}종료')
        
        # 7. Plotly 간트 차트 그리기
        df = pd.DataFrame(schedule_data)
        # 기계 번호 기준으로 정렬
        df = df.sort_values(by=['Machine', 'Start'])
        
        fig = px.timeline(
            df, 
            x_start="Start", 
            x_end="Finish", 
            y="Machine", 
            color="Job", 
            text="Job",
            title="최적화된 공정 스케줄링 간트 차트 (MIP 모델링 적용)"
        )
        
        # 차트 디자인 다듬기
        fig.update_yaxes(autorange="reversed") # 기계0이 위로 오도록 반전
        fig.update_layout(
            xaxis_title="시간", 
            yaxis_title="설비(Machine)",
            font=dict(size=14)
        )
        
        # 브라우저에 차트 띄우기
        fig.show()

    else:
        print('최적해를 찾을 수 없습니다.')

if __name__ == '__main__':
    solve_job_shop()