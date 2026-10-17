"""
database.py
-----------
SQLite connection, table definitions, and CRUD operations
for the AI Project Planner Agent.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("project_planner.db")


@contextmanager
def get_connection():
    """Thread-safe context manager for SQLite connections."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                description TEXT,
                tech_stack  TEXT,
                deadline    TEXT,
                weekly_hours REAL   DEFAULT 20.0,
                status      TEXT    DEFAULT 'active',
                risk_level  TEXT    DEFAULT 'medium',
                risk_notes  TEXT,
                evaluation  TEXT    DEFAULT '',
                created_at  TEXT    DEFAULT (datetime('now')),
                updated_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      INTEGER NOT NULL,
                task_id         TEXT    NOT NULL,
                title           TEXT    NOT NULL,
                description     TEXT,
                phase           TEXT,
                priority        TEXT    DEFAULT 'medium',
                status          TEXT    DEFAULT 'not_started',
                duration_days   REAL    DEFAULT 1.0,
                start_date      TEXT,
                end_date        TEXT,
                dependencies    TEXT    DEFAULT '[]',
                completion_criteria TEXT,
                notes           TEXT,
                created_at      TEXT    DEFAULT (datetime('now')),
                updated_at      TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE (project_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS replan_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER NOT NULL,
                reason      TEXT,
                changes     TEXT,
                created_at  TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
        """)
        # ── Schema migrations (safe: ignored if column already exists) ───────
        for migration in [
            "ALTER TABLE projects ADD COLUMN evaluation TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass  # Column already exists — harmless
    logger.info("Database initialised at %s", DB_PATH)


# ─── Projects ────────────────────────────────────────────────────────────────

def save_project(name: str, description: str, tech_stack: str,
                 deadline: str, weekly_hours: float,
                 risk_level: str = "medium", risk_notes: str = "",
                 evaluation: str = "") -> int:
    """Insert a new project and return its id."""
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO projects
               (name, description, tech_stack, deadline, weekly_hours, risk_level, risk_notes, evaluation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, description, tech_stack, deadline, weekly_hours, risk_level, risk_notes, evaluation),
        )
        return cur.lastrowid


def update_project(project_id: int, **kwargs) -> None:
    """Update arbitrary project fields."""
    allowed = {"name", "description", "tech_stack", "deadline",
                "weekly_hours", "status", "risk_level", "risk_notes", "evaluation"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE projects SET {set_clause} WHERE id = ?",
            (*fields.values(), project_id),
        )


def load_project(project_id: int) -> Optional[dict]:
    """Load a single project by id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None


def list_projects() -> list[dict]:
    """Return all projects ordered by creation date (newest first)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_project(project_id: int) -> None:
    """Hard-delete a project and its tasks (cascade)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ─── Tasks ───────────────────────────────────────────────────────────────────

def save_tasks(project_id: int, tasks: list[dict]) -> None:
    """Bulk-upsert a list of task dicts for a project."""
    with get_connection() as conn:
        for t in tasks:
            conn.execute(
                """INSERT INTO tasks
                   (project_id, task_id, title, description, phase, priority,
                    status, duration_days, start_date, end_date, dependencies,
                    completion_criteria, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, task_id) DO UPDATE SET
                       title=excluded.title,
                       description=excluded.description,
                       phase=excluded.phase,
                       priority=excluded.priority,
                       duration_days=excluded.duration_days,
                       start_date=excluded.start_date,
                       end_date=excluded.end_date,
                       dependencies=excluded.dependencies,
                       completion_criteria=excluded.completion_criteria,
                       notes=excluded.notes,
                       updated_at=datetime('now')
                """,
                (
                    project_id,
                    t.get("task_id", t.get("id", "")),
                    t.get("title", ""),
                    t.get("description", ""),
                    t.get("phase", ""),
                    t.get("priority", "medium"),
                    t.get("status", "not_started"),
                    t.get("duration_days", 1.0),
                    t.get("start_date", ""),
                    t.get("end_date", ""),
                    json.dumps(t.get("dependencies", [])),
                    t.get("completion_criteria", ""),
                    t.get("notes", ""),
                ),
            )


def load_tasks(project_id: int) -> list[dict]:
    """Return all tasks for a project, dependencies parsed to list."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY start_date, task_id",
            (project_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["dependencies"] = json.loads(d["dependencies"] or "[]")
            except Exception:
                d["dependencies"] = []
            result.append(d)
        return result


def update_task_status(task_db_id: int, status: str, notes: str = "") -> None:
    """Update a task's status and optional notes."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE tasks
               SET status = ?, notes = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (status, notes, task_db_id),
        )


def get_project_stats(project_id: int) -> dict:
    """Return aggregate stats for a project's tasks."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='completed'   THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status='not_started' THEN 1 ELSE 0 END) as not_started,
                SUM(CASE WHEN status='blocked'     THEN 1 ELSE 0 END) as blocked
               FROM tasks WHERE project_id = ?""",
            (project_id,),
        ).fetchone()
        stats = dict(row) if row else {}
        today = datetime.now().date().isoformat()
        overdue_row = conn.execute(
            """SELECT COUNT(*) as overdue FROM tasks
               WHERE project_id = ?
               AND status NOT IN ('completed')
               AND end_date < ?""",
            (project_id, today),
        ).fetchone()
        stats["overdue"] = overdue_row["overdue"] if overdue_row else 0
        total = stats.get("total") or 1
        stats["progress_pct"] = round((stats.get("done", 0) / total) * 100, 1)
        return stats


# ─── Replan History ──────────────────────────────────────────────────────────

def log_replan(project_id: int, reason: str, changes: list[dict]) -> None:
    """Record a replanning event."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO replan_history (project_id, reason, changes) VALUES (?, ?, ?)",
            (project_id, reason, json.dumps(changes)),
        )


def load_replan_history(project_id: int) -> list[dict]:
    """Load all replan events for a project."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM replan_history WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["changes"] = json.loads(d["changes"] or "[]")
            except Exception:
                d["changes"] = []
            result.append(d)
        return result
