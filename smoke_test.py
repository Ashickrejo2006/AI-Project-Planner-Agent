import sys, os
sys.path.insert(0, '.')

# Test database
import database as db
db.init_db()
pid = db.save_project('Test Project', 'A test', 'Python', '2026-12-31', 20.0)
db.save_tasks(pid, [
    {'task_id': 'T-001', 'title': 'Setup', 'duration_days': 2,
     'phase': 'planning', 'priority': 'high', 'dependencies': [],
     'completion_criteria': 'done', 'status': 'not_started'}
])
stats = db.get_project_stats(pid)
print('DB test passed. Stats:', stats)
db.delete_project(pid)

# Test tools
from tools import DateCalcInput, calculate_end_date, RiskInput, assess_risk, schedule_tasks

result = calculate_end_date(DateCalcInput(start_date='2026-10-20', duration_days=5))
print('Date calc:', result)

tasks = [
    {'task_id': 'T-001', 'title': 'Setup', 'duration_days': 2, 'dependencies': []},
    {'task_id': 'T-002', 'title': 'Build', 'duration_days': 5, 'dependencies': ['T-001']},
]
scheduled = schedule_tasks(tasks, '2026-10-20')
for t in scheduled:
    print('  ' + t['task_id'] + ': ' + t['start_date'] + ' -> ' + t['end_date'])

risk = assess_risk(RiskInput(
    project_name='Test', tech_stack='AI, blockchain',
    deadline='2026-10-25', weekly_hours=10, tasks=tasks
))
print('Risk level:', risk['risk_level'], '| Score:', risk['risk_score'])
print('ALL TESTS PASSED')
