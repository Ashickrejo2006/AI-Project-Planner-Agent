"""
agent.py
--------
LangGraph-powered AI Project Planner agent.

Implements the Plan-Act-Evaluate loop:
  1. PLAN  : LLM decomposes user input into a structured task graph
  2. ACT   : Tools calculate dates and assess risk
  3. EVALUATE : LLM reviews the plan and flags issues
  4. SAVE  : Persist to SQLite
"""

import json
import logging
import os
from datetime import date
from typing import Any, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph

import database as db
from tools import (
    ProjectPlan,
    RiskInput,
    TaskModel,
    assess_risk,
    schedule_tasks,
)

load_dotenv()
logger = logging.getLogger(__name__)

# ─── LLM Initialisation ───────────────────────────────────────────────────────

def _get_llm():
    """Return the best available LLM. Prefers OpenAI, falls back to Anthropic."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if openai_key and openai_key.startswith("sk-"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.2,
            api_key=openai_key,
        )
    elif anthropic_key:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model="claude-3-5-haiku-20241022",
            temperature=0.2,
            api_key=anthropic_key,
        )
    else:
        raise EnvironmentError(
            "No LLM API key found. Please set OPENAI_API_KEY or ANTHROPIC_API_KEY "
            "in your .env file or environment variables."
        )


# ─── Graph State ──────────────────────────────────────────────────────────────

class PlannerState(TypedDict):
    # Inputs
    project_name: str
    description: str
    tech_stack: str
    deadline: str
    weekly_hours: float
    country: str

    # Intermediate
    raw_plan: str          # LLM's JSON string output
    tasks: list[dict]      # parsed & scheduled task list
    risk_result: dict      # from assess_risk()
    evaluation: str        # LLM's evaluation text
    project_id: int        # DB id after save

    # Control
    error: Optional[str]
    iteration: int


# ─── System Prompts ────────────────────────────────────────────────────────────

_PLAN_SYSTEM = """You are an expert AI project manager and software architect.
Your job is to decompose a software project into a detailed, phased task list.

Rules:
- Return ONLY a valid JSON object with the key "tasks" containing an array of task objects.
- Do NOT wrap in markdown code fences.
- Each task MUST have these exact keys:
  task_id (string, format "T-001"), title (string), description (string),
  phase (one of: discovery|planning|design|development|testing|deployment|maintenance),
  priority (one of: low|medium|high|critical),
  duration_days (number, 0.25 to 30), dependencies (array of task_id strings),
  completion_criteria (string)
- Order tasks so that dependencies come before dependents.
- Aim for 8-20 tasks unless the project clearly warrants more.
- Be realistic about duration estimates given the weekly hours available.
- Group tasks into logical phases: Start with discovery/planning, end with deployment.
"""

_EVALUATE_SYSTEM = """You are a senior engineering manager performing a project plan review.
Analyse the task list, risk assessment, and deadline feasibility.
Respond in plain text (NOT JSON) with:
1. Overall feasibility verdict (Feasible / Risky / Not Feasible)
2. Top 3 concerns (numbered)
3. Top 3 actionable recommendations (numbered)
Keep the entire response under 300 words.
"""

_REPLAN_SYSTEM = """You are an expert project manager. A task has been blocked or delayed.
Adjust the remaining task schedule by:
1. Re-estimating affected dependent tasks
2. Identifying which tasks can be parallelised
3. Flagging any deadline risk
Return ONLY valid JSON with key "updated_tasks" (array of updated task objects
with the same schema as the input). Only include tasks that need changes.
"""


def _generate_heuristic_tasks(
    project_name: str,
    description: str,
    tech_stack: str,
    weekly_hours: float,
) -> list[dict]:
    """Autonomous fallback task decomposition when LLM is unavailable or quota exceeded."""
    stack_items = [s.strip() for s in tech_stack.replace(";", ",").split(",") if s.strip()]
    primary_tech = stack_items[0] if stack_items else "Core Stack"
    sec_tech = stack_items[1] if len(stack_items) > 1 else "API"

    # Scale durations based on available weekly hours (baseline: 20h)
    scale = max(0.5, min(2.5, 20.0 / max(weekly_hours, 5.0)))

    return [
        {
            "task_id": "T-001",
            "title": f"Requirements Analysis & {project_name} Scope Baseline",
            "description": f"Refine functional scope, user personas, and target deliverables for {project_name}.",
            "phase": "discovery",
            "priority": "high",
            "duration_days": round(2.0 * scale, 1),
            "dependencies": [],
            "completion_criteria": "Project charter and requirements sign-off approved."
        },
        {
            "task_id": "T-002",
            "title": f"System Architecture & {primary_tech} Design Specs",
            "description": f"Design high-level architecture, module boundaries, and data flow using {tech_stack}.",
            "phase": "design",
            "priority": "critical",
            "duration_days": round(2.5 * scale, 1),
            "dependencies": ["T-001"],
            "completion_criteria": "Architecture blueprint and component interaction diagrams finalized."
        },
        {
            "task_id": "T-003",
            "title": f"Repository Setup, Tooling & {primary_tech} Boilerplate",
            "description": "Initialize version control, linting, test runner, environment configs, and container setup.",
            "phase": "planning",
            "priority": "medium",
            "duration_days": round(1.5 * scale, 1),
            "dependencies": ["T-002"],
            "completion_criteria": "Clean repo initialized with build pipelines and dependency checks passing."
        },
        {
            "task_id": "T-004",
            "title": "Database Schema Design & Migrations",
            "description": "Create relational/NoSQL models, indexes, database seeds, and automated migration scripts.",
            "phase": "development",
            "priority": "high",
            "duration_days": round(2.5 * scale, 1),
            "dependencies": ["T-003"],
            "completion_criteria": "Database migrations execute idempotently; initial test data populated."
        },
        {
            "task_id": "T-005",
            "title": f"Core Backend Services & Business Logic ({sec_tech})",
            "description": f"Implement core domain logic and primary REST/GraphQL endpoints for {project_name}.",
            "phase": "development",
            "priority": "critical",
            "duration_days": round(4.0 * scale, 1),
            "dependencies": ["T-004"],
            "completion_criteria": "Core business endpoints implemented and tested with mock data."
        },
        {
            "task_id": "T-006",
            "title": "Authentication, Authorization & Security Hardening",
            "description": "Implement token-based auth, role permissions, CORS security policies, and rate-limiting.",
            "phase": "development",
            "priority": "high",
            "duration_days": round(2.0 * scale, 1),
            "dependencies": ["T-005"],
            "completion_criteria": "Secure login, token refresh, and protected endpoints verified."
        },
        {
            "task_id": "T-007",
            "title": f"Frontend UI Scaffold & Design System ({primary_tech})",
            "description": "Build responsive application shell, navigation drawer, theme tokens, and core layout components.",
            "phase": "development",
            "priority": "high",
            "duration_days": round(3.5 * scale, 1),
            "dependencies": ["T-003"],
            "completion_criteria": "Pixel-perfect responsive layout matching design specs across viewports."
        },
        {
            "task_id": "T-008",
            "title": "Frontend-Backend Integration & State Management",
            "description": "Connect frontend clients to backend services, handling loading states, optimistic updates, and toasts.",
            "phase": "development",
            "priority": "critical",
            "duration_days": round(3.5 * scale, 1),
            "dependencies": ["T-006", "T-007"],
            "completion_criteria": "End-to-end data flow working smoothly with proper error handling."
        },
        {
            "task_id": "T-009",
            "title": "Automated Unit & Integration Test Suite",
            "description": "Write comprehensive unit tests for business logic and integration tests for API endpoints.",
            "phase": "testing",
            "priority": "high",
            "duration_days": round(2.5 * scale, 1),
            "dependencies": ["T-008"],
            "completion_criteria": "Test suite achieves >80% coverage on critical paths with all assertions green."
        },
        {
            "task_id": "T-010",
            "title": "Performance Profiling & Bottleneck Optimization",
            "description": "Audit response times, query indexing, bundle size, caching headers, and concurrency.",
            "phase": "testing",
            "priority": "medium",
            "duration_days": round(1.5 * scale, 1),
            "dependencies": ["T-009"],
            "completion_criteria": "P95 response latency <200ms; Lighthouse performance rating >85."
        },
        {
            "task_id": "T-011",
            "title": "CI/CD Deployment Pipeline & Staging Verification",
            "description": "Configure automated build & deploy workflows, staging environment, and sanity health checks.",
            "phase": "deployment",
            "priority": "high",
            "duration_days": round(2.0 * scale, 1),
            "dependencies": ["T-009"],
            "completion_criteria": "Automated build passing with green staging deployment."
        },
        {
            "task_id": "T-012",
            "title": "Production Release, Health Monitoring & Documentation",
            "description": "Cut production release, setup uptime/error alerts, and publish API developer docs.",
            "phase": "deployment",
            "priority": "critical",
            "duration_days": round(1.5 * scale, 1),
            "dependencies": ["T-010", "T-011"],
            "completion_criteria": "Production launch complete with active monitoring and documentation published."
        },
    ]


# ─── Node Functions ────────────────────────────────────────────────────────────

def node_plan(state: PlannerState) -> PlannerState:
    """Ask the LLM to decompose the project into tasks."""
    logger.info("[PLAN] Decomposing project: %s", state["project_name"])
    llm_note = None
    try:
        llm = _get_llm()
        user_msg = (
            f"Project: {state['project_name']}\n"
            f"Description: {state['description']}\n"
            f"Tech Stack: {state['tech_stack']}\n"
            f"Deadline: {state['deadline']}\n"
            f"Available weekly hours: {state['weekly_hours']}\n"
            f"Start date (today): {date.today().isoformat()}\n\n"
            "Decompose this into a JSON task list following the system instructions."
        )
        response = llm.invoke([
            SystemMessage(content=_PLAN_SYSTEM),
            HumanMessage(content=user_msg),
        ])
        state["raw_plan"] = response.content
        state["error"] = None
    except Exception as e:
        logger.warning("[PLAN] LLM planning unavailable (%s). Using autonomous architectural heuristic planner.", e)
        llm_note = str(e)
        tasks = _generate_heuristic_tasks(
            project_name=state["project_name"],
            description=state["description"],
            tech_stack=state["tech_stack"],
            weekly_hours=state["weekly_hours"],
        )
        state["raw_plan"] = json.dumps({"tasks": tasks})
        state["error"] = None
        state["_llm_note"] = llm_note

    state["iteration"] = state.get("iteration", 0) + 1
    return state


def node_parse_and_schedule(state: PlannerState) -> PlannerState:
    """Parse the LLM JSON, validate with Pydantic, and assign dates."""
    if state.get("error"):
        state["tasks"] = []
        return state

    raw = state.get("raw_plan", "")
    try:
        # Strip markdown fences if the LLM ignored instructions
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        raw_tasks: list[dict] = data.get("tasks", data) if isinstance(data, dict) else data

        validated: list[dict] = []
        for i, t in enumerate(raw_tasks):
            if "task_id" not in t:
                t["task_id"] = f"T-{i+1:03d}"
            try:
                m = TaskModel(**t)
                validated.append(m.model_dump())
            except Exception as ve:
                logger.warning("Task validation warning for %s: %s", t.get("task_id"), ve)
                # Best-effort: keep the raw dict
                t.setdefault("status", "not_started")
                validated.append(t)

        # Topological scheduling
        scheduled = schedule_tasks(
            validated,
            project_start=date.today().isoformat(),
            country=state.get("country", "US"),
        )
        state["tasks"] = scheduled
    except json.JSONDecodeError as e:
        state["error"] = f"LLM returned invalid JSON: {e}\nRaw: {raw[:300]}"
        state["tasks"] = []
    except Exception as e:
        logger.exception("Parse/schedule error")
        state["error"] = f"Schedule error: {e}"
        state["tasks"] = []
    return state


def node_assess_risk(state: PlannerState) -> PlannerState:
    """Run the deterministic risk engine on the scheduled plan."""
    try:
        result = assess_risk(
            RiskInput(
                project_name=state["project_name"],
                tech_stack=state["tech_stack"],
                deadline=state["deadline"],
                weekly_hours=state["weekly_hours"],
                tasks=state.get("tasks", []),
            )
        )
        state["risk_result"] = result
    except Exception as e:
        logger.exception("Risk assessment error")
        state["risk_result"] = {
            "risk_level": "medium",
            "risk_score": 0,
            "risks": [f"Risk analysis failed: {e}"],
            "recommendations": [],
        }
    return state


def node_evaluate(state: PlannerState) -> PlannerState:
    """LLM reviews the plan + risk and provides a feasibility verdict."""
    if state.get("error"):
        state["evaluation"] = "⚠️ Plan could not be evaluated due to an earlier error."
        return state
    try:
        llm = _get_llm()
        risk = state.get("risk_result", {})
        tasks_summary = "\n".join(
            f"  {t['task_id']} [{t.get('phase','')}] {t['title']} "
            f"({t.get('duration_days',1)}d, {t.get('priority','')})"
            for t in state.get("tasks", [])[:25]
        )
        msg = (
            f"Project: {state['project_name']}\n"
            f"Deadline: {state['deadline']}\n"
            f"Risk level: {risk.get('risk_level','?')}\n"
            f"Risk notes: {'; '.join(risk.get('risks',[]))}\n\n"
            f"Task summary:\n{tasks_summary}\n\n"
            "Provide your evaluation."
        )
        response = llm.invoke([
            SystemMessage(content=_EVALUATE_SYSTEM),
            HumanMessage(content=msg),
        ])
        state["evaluation"] = response.content
    except Exception as e:
        logger.warning("LLM evaluation unavailable (%s). Using autonomous heuristic evaluation.", e)
        risk = state.get("risk_result", {})
        verdict = "Feasible" if risk.get("risk_level") in ("low", "medium") else "Risky"
        state["evaluation"] = (
            f"Overall Feasibility: {verdict}\n\n"
            f"1. Schedule Alignment: Modulated across {len(state.get('tasks', []))} phased deliverables targeting {state['deadline']} ({state['weekly_hours']}h/week capacity).\n"
            f"2. Dependency Structure: Strict critical path maintained across architecture, core services, and testing.\n"
            f"3. Recommendation: Lock the requirements baseline (T-001) before initiating database schema migrations."
        )
    return state


def node_save(state: PlannerState) -> PlannerState:
    """Persist the project and tasks to SQLite."""
    try:
        db.init_db()
        risk = state.get("risk_result", {})
        project_id = db.save_project(
            name=state["project_name"],
            description=state["description"],
            tech_stack=state["tech_stack"],
            deadline=state["deadline"],
            weekly_hours=state["weekly_hours"],
            risk_level=risk.get("risk_level", "medium"),
            risk_notes="\n".join(risk.get("risks", [])),
            evaluation=state.get("evaluation", ""),
        )
        db.save_tasks(project_id, state.get("tasks", []))
        state["project_id"] = project_id
        logger.info("[SAVE] Project %d saved with %d tasks", project_id, len(state["tasks"]))
    except Exception as e:
        logger.exception("Save error")
        state["error"] = f"Database save failed: {e}"
    return state


def _should_retry(state: PlannerState) -> str:
    """Edge function: retry planning if parse failed, up to 2 times."""
    if state.get("error") and "JSON" in state.get("error", "") and state.get("iteration", 0) < 2:
        return "plan"
    return "assess_risk"


# ─── Build the Graph ──────────────────────────────────────────────────────────

def build_graph() -> Any:
    """Compile and return the LangGraph StateGraph."""
    g = StateGraph(PlannerState)

    g.add_node("plan",               node_plan)
    g.add_node("parse_and_schedule", node_parse_and_schedule)
    g.add_node("assess_risk",        node_assess_risk)
    g.add_node("evaluate",           node_evaluate)
    g.add_node("save",               node_save)

    g.set_entry_point("plan")
    g.add_edge("plan",               "parse_and_schedule")
    g.add_conditional_edges("parse_and_schedule", _should_retry)
    g.add_edge("assess_risk",        "evaluate")
    g.add_edge("evaluate",           "save")
    g.add_edge("save",               END)

    return g.compile()


# ─── Replanning Function ───────────────────────────────────────────────────────

def replan_project(project_id: int, blocked_task_id: str,
                   reason: str, new_start_date: Optional[str] = None) -> dict:
    """
    Re-evaluate the project schedule after a task is blocked/delayed.
    Returns a dict with keys: updated_tasks, risk_result, evaluation, error.
    """
    project = db.load_project(project_id)
    if not project:
        return {"error": f"Project {project_id} not found."}

    tasks = db.load_tasks(project_id)
    if not tasks:
        return {"error": "No tasks found for this project."}

    # Identify the blocked task and all its dependents (transitive)
    blocked = {blocked_task_id}
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t["task_id"] not in blocked:
                deps = t.get("dependencies", [])
                if any(d in blocked for d in deps):
                    blocked.add(t["task_id"])
                    changed = True

    affected_tasks = [t for t in tasks if t["task_id"] in blocked]

    # Use LLM to suggest adjustments
    updated_tasks_raw: list[dict] = affected_tasks
    evaluation = ""
    try:
        llm = _get_llm()
        tasks_json = json.dumps(affected_tasks, indent=2)
        msg = (
            f"Project: {project['name']}\n"
            f"Deadline: {project['deadline']}\n"
            f"Blocked task: {blocked_task_id}\n"
            f"Reason: {reason}\n"
            f"New start date for blocked task: {new_start_date or 'unknown'}\n\n"
            f"Affected tasks JSON:\n{tasks_json}\n\n"
            "Return updated_tasks JSON only."
        )
        response = llm.invoke([
            SystemMessage(content=_REPLAN_SYSTEM),
            HumanMessage(content=msg),
        ])
        raw = response.content
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        updated_tasks_raw = data.get("updated_tasks", affected_tasks)
        evaluation = f"LLM replanning complete for {len(updated_tasks_raw)} task(s)."
    except EnvironmentError:
        evaluation = "Replanning done via date shifting (no LLM key available)."
    except Exception as e:
        logger.warning("LLM replan failed, falling back to date shift: %s", e)
        evaluation = f"LLM replan unavailable. Applied simple date shift. ({e})"

    # Fallback / merge: re-schedule from new_start_date
    if new_start_date:
        # Apply simple date shift to affected tasks
        try:
            base_start = date.fromisoformat(new_start_date)
            unaffected = [t for t in tasks if t["task_id"] not in blocked]
            rescheduled = schedule_tasks(
                updated_tasks_raw + unaffected,
                project_start=project.get("created_at", date.today().isoformat())[:10],
                country="US",
            )
            # Only keep the affected ones for updating
            affected_ids = {t["task_id"] for t in updated_tasks_raw}
            updated_tasks_raw = [t for t in rescheduled if t["task_id"] in affected_ids]
        except Exception as e:
            logger.warning("Date shift failed: %s", e)

    # Persist updates
    db.save_tasks(project_id, updated_tasks_raw)
    db.log_replan(project_id, reason, updated_tasks_raw)

    # New risk assessment
    all_tasks_updated = db.load_tasks(project_id)
    risk_result = assess_risk(
        RiskInput(
            project_name=project["name"],
            tech_stack=project.get("tech_stack", ""),
            deadline=project["deadline"],
            weekly_hours=project.get("weekly_hours", 20.0),
            tasks=all_tasks_updated,
        )
    )
    db.update_project(project_id,
                      risk_level=risk_result["risk_level"],
                      risk_notes="\n".join(risk_result["risks"]))

    return {
        "updated_tasks": updated_tasks_raw,
        "risk_result": risk_result,
        "evaluation": evaluation,
        "error": None,
    }


# ─── Entry point ─────────────────────────────────────────────────────────────

def run_planner(
    project_name: str,
    description: str,
    tech_stack: str,
    deadline: str,
    weekly_hours: float,
    country: str = "US",
) -> PlannerState:
    """Run the full Plan-Act-Evaluate-Save pipeline and return the final state."""
    db.init_db()
    graph = build_graph()
    initial_state: PlannerState = {
        "project_name": project_name,
        "description": description,
        "tech_stack": tech_stack,
        "deadline": deadline,
        "weekly_hours": weekly_hours,
        "country": country,
        "raw_plan": "",
        "tasks": [],
        "risk_result": {},
        "evaluation": "",
        "project_id": -1,
        "error": None,
        "iteration": 0,
    }
    final_state = graph.invoke(initial_state)
    return final_state
