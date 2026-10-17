"""
tools.py
--------
Pydantic models, date-calculation helpers, and risk-assessment
tool functions used by the LangGraph agent.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Optional

import holidays
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ─── Pydantic Models ──────────────────────────────────────────────────────────

VALID_STATUSES = {"not_started", "in_progress", "completed", "blocked", "delayed"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}
VALID_PHASES = {"discovery", "planning", "design", "development",
                "testing", "deployment", "maintenance"}


class TaskModel(BaseModel):
    """Represents a single decomposed task."""

    task_id: str = Field(..., description="Unique task identifier e.g. T-001")
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="")
    phase: str = Field(default="development")
    priority: str = Field(default="medium")
    status: str = Field(default="not_started")
    duration_days: float = Field(default=1.0, ge=0.25, le=180.0)
    start_date: str = Field(default="")
    end_date: str = Field(default="")
    dependencies: list[str] = Field(default_factory=list)
    completion_criteria: str = Field(default="")
    notes: str = Field(default="")

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        v = v.lower()
        if v not in VALID_PRIORITIES:
            return "medium"
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.lower().replace(" ", "_")
        if v not in VALID_STATUSES:
            return "not_started"
        return v

    @field_validator("phase")
    @classmethod
    def validate_phase(cls, v: str) -> str:
        v = v.lower()
        return v if v in VALID_PHASES else "development"


class ProjectPlan(BaseModel):
    """Full project plan returned by the agent."""

    project_name: str
    summary: str = ""
    tech_stack: str = ""
    deadline: str = ""
    weekly_hours: float = 20.0
    tasks: list[TaskModel] = Field(default_factory=list)
    risk_level: str = "medium"
    risk_notes: str = ""
    recommendations: list[str] = Field(default_factory=list)


class DateCalcInput(BaseModel):
    start_date: str = Field(..., description="ISO date string YYYY-MM-DD")
    duration_days: float = Field(..., ge=0.25)
    country: str = Field(default="US", description="Country code for holidays")
    skip_weekends: bool = Field(default=True)
    skip_holidays: bool = Field(default=True)


class RiskInput(BaseModel):
    project_name: str
    tech_stack: str
    deadline: str
    weekly_hours: float
    tasks: list[dict] = Field(default_factory=list)


class ReplanInput(BaseModel):
    project_id: int
    blocked_task_id: str
    reason: str
    new_start_date: Optional[str] = None


# ─── Date Calculation Tool ────────────────────────────────────────────────────

def _get_holidays(year: int, country: str) -> set[date]:
    """Return a set of public holiday dates for the given country/year."""
    try:
        return set(holidays.country_holidays(country, years=year).keys())
    except Exception:
        return set()


def calculate_end_date(input_data: DateCalcInput) -> dict[str, Any]:
    """
    Given a start date and working-day duration, return the end date
    skipping weekends and/or public holidays.

    Returns a dict with keys: start_date, end_date, calendar_days, working_days.
    """
    try:
        start = date.fromisoformat(input_data.start_date)
    except ValueError as exc:
        return {"error": f"Invalid start_date: {exc}"}

    duration = input_data.duration_days
    if not input_data.skip_weekends and not input_data.skip_holidays:
        end = start + timedelta(days=int(duration))
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "calendar_days": int(duration),
            "working_days": int(duration),
        }

    country_holidays = (
        _get_holidays(start.year, input_data.country) |
        _get_holidays(start.year + 1, input_data.country)
    )

    working_days_counted = 0.0
    current = start
    while working_days_counted < duration:
        is_weekend = current.weekday() >= 5
        is_holiday = current in country_holidays

        skip = (input_data.skip_weekends and is_weekend) or \
               (input_data.skip_holidays and is_holiday)

        if not skip:
            remaining = duration - working_days_counted
            working_days_counted += min(1.0, remaining)

        if working_days_counted < duration:
            current += timedelta(days=1)

    calendar_days = (current - start).days + 1
    return {
        "start_date": start.isoformat(),
        "end_date": current.isoformat(),
        "calendar_days": calendar_days,
        "working_days": duration,
    }


def schedule_tasks(tasks: list[dict], project_start: str,
                   country: str = "US") -> list[dict]:
    """
    Topologically sort tasks by dependencies and assign start/end dates.
    Returns the same task list with start_date and end_date populated.
    """
    try:
        start_date = date.fromisoformat(project_start)
    except ValueError:
        start_date = date.today()

    # Build adjacency and in-degree maps
    task_map: dict[str, dict] = {t["task_id"]: t for t in tasks}
    end_dates: dict[str, date] = {}

    def resolve(task_id: str, visited: set[str] | None = None) -> date:
        if visited is None:
            visited = set()
        if task_id in end_dates:
            return end_dates[task_id]
        if task_id in visited:
            # Circular dependency – break cycle
            return start_date
        visited.add(task_id)

        task = task_map.get(task_id)
        if task is None:
            return start_date

        deps = task.get("dependencies", [])
        if deps:
            dep_ends = [resolve(d, visited.copy()) for d in deps if d in task_map]
            t_start = max(dep_ends) + timedelta(days=1) if dep_ends else start_date
        else:
            t_start = start_date

        calc = calculate_end_date(
            DateCalcInput(
                start_date=t_start.isoformat(),
                duration_days=task.get("duration_days", 1.0),
                country=country,
            )
        )
        t_end = date.fromisoformat(calc["end_date"])
        end_dates[task_id] = t_end
        task["start_date"] = t_start.isoformat()
        task["end_date"] = t_end.isoformat()
        return t_end

    for tid in list(task_map.keys()):
        resolve(tid)

    return list(task_map.values())


# ─── Risk Assessment Tool ──────────────────────────────────────────────────────

# Known high-risk tech keywords and their risk explanations
_HIGH_RISK_TECH = {
    "blockchain": "Blockchain integrations carry high complexity and audit overhead.",
    "ml": "Machine-learning workloads need significant experimentation time.",
    "ai": "AI model training/tuning timelines are hard to estimate accurately.",
    "cuda": "GPU/CUDA setup can block early development on non-GPU machines.",
    "kubernetes": "K8s cluster management adds substantial DevOps complexity.",
    "microservices": "Distributed systems increase debugging and deployment surface.",
    "real-time": "Real-time features (WebSockets, streaming) require careful load testing.",
    "websocket": "WebSocket infrastructure demands extra reliability engineering.",
    "oauth": "OAuth/OIDC integration involves security-sensitive third-party flows.",
    "payment": "Payment gateway integration requires PCI compliance awareness.",
    "stripe": "Stripe webhook handling needs rigorous idempotency design.",
    "graphql": "GraphQL schema design and N+1 query problems can delay backend work.",
}

_TIGHT_RATIO = 2.0   # hours-per-task-day threshold below which it's tight
_CRITICAL_RATIO = 1.0


def assess_risk(input_data: RiskInput) -> dict[str, Any]:
    """
    Analyse the project plan and return a risk level ('low'/'medium'/'high'/'critical')
    plus a list of specific risk notes and recommendations.
    """
    risks: list[str] = []
    recommendations: list[str] = []
    score = 0  # Higher → riskier

    tech_lower = input_data.tech_stack.lower()
    for keyword, note in _HIGH_RISK_TECH.items():
        if keyword in tech_lower:
            risks.append(f"⚠️  Tech risk ({keyword}): {note}")
            score += 2

    # Deadline analysis
    try:
        deadline = date.fromisoformat(input_data.deadline)
        days_left = (deadline - date.today()).days
        if days_left < 0:
            risks.append("🚨 Deadline is already in the past!")
            score += 10
        elif days_left < 7:
            risks.append(f"🚨 Deadline is extremely tight ({days_left} days left).")
            score += 8
        elif days_left < 14:
            risks.append(f"⚠️  Deadline is very soon ({days_left} days left).")
            score += 4
        elif days_left < 30:
            risks.append(f"ℹ️  Deadline is within one month ({days_left} days).")
            score += 1
    except ValueError:
        risks.append("⚠️  Could not parse deadline date.")
        score += 1

    # Workload analysis
    total_task_days = sum(t.get("duration_days", 1.0) for t in input_data.tasks)
    weekly_hours = max(input_data.weekly_hours, 0.1)
    daily_hours_available = weekly_hours / 5.0
    available_hours = total_task_days * daily_hours_available

    if total_task_days > 0 and input_data.weekly_hours > 0:
        ratio = available_hours / total_task_days
        if ratio < _CRITICAL_RATIO:
            risks.append(
                f"🚨 Severe time shortage: {available_hours:.1f}h available "
                f"for {total_task_days} task-days."
            )
            score += 6
            recommendations.append(
                "Consider reducing scope or increasing weekly commitment hours."
            )
        elif ratio < _TIGHT_RATIO:
            risks.append(
                f"⚠️  Tight schedule: {available_hours:.1f}h available for {total_task_days} task-days."
            )
            score += 3

    # Dependency chain analysis
    if input_data.tasks:
        max_deps = max(len(t.get("dependencies", [])) for t in input_data.tasks)
        if max_deps >= 4:
            risks.append(
                f"⚠️  Long dependency chain detected (max depth ~{max_deps}). "
                "One delay could cascade."
            )
            score += 2
            recommendations.append(
                "Identify the critical path and add buffer time to high-dependency tasks."
            )

    # Task count analysis
    task_count = len(input_data.tasks)
    if task_count > 30:
        risks.append(f"ℹ️  Large plan ({task_count} tasks). Break into milestones.")
        recommendations.append("Use milestone reviews every 10 tasks to avoid scope creep.")
        score += 1

    # Determine overall level
    if score >= 10:
        level = "critical"
    elif score >= 6:
        level = "high"
    elif score >= 3:
        level = "medium"
    else:
        level = "low"

    if not recommendations:
        recommendations.append(
            "Maintain daily standups and keep the task board up to date."
        )

    return {
        "risk_level": level,
        "risk_score": score,
        "risks": risks,
        "recommendations": recommendations,
    }


# ─── Convenience wrappers for LangGraph tool nodes ───────────────────────────

def tool_calculate_dates(
    start_date: Annotated[str, "ISO start date YYYY-MM-DD"],
    duration_days: Annotated[float, "Working days needed"],
    country: Annotated[str, "Country code"] = "US",
) -> str:
    """LangGraph-compatible wrapper for calculate_end_date."""
    result = calculate_end_date(
        DateCalcInput(start_date=start_date, duration_days=duration_days, country=country)
    )
    return json.dumps(result)


def tool_assess_risk(
    project_name: Annotated[str, "Project name"],
    tech_stack: Annotated[str, "Comma-separated tech stack"],
    deadline: Annotated[str, "ISO deadline date YYYY-MM-DD"],
    weekly_hours: Annotated[float, "Available weekly hours"],
    tasks_json: Annotated[str, "JSON array of task dicts"] = "[]",
) -> str:
    """LangGraph-compatible wrapper for assess_risk."""
    try:
        tasks = json.loads(tasks_json)
    except Exception:
        tasks = []
    result = assess_risk(
        RiskInput(
            project_name=project_name,
            tech_stack=tech_stack,
            deadline=deadline,
            weekly_hours=weekly_hours,
            tasks=tasks,
        )
    )
    return json.dumps(result)
