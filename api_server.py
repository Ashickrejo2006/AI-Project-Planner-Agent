
"""
api_server.py
-------------
FastAPI REST API that bridges the HTML/JS frontend with the
LangGraph agent and SQLite database.

Endpoints:
  GET    /api/projects                    – list all projects
  POST   /api/projects                    – create project (triggers AI plan)
  GET    /api/projects/{id}               – get single project
  DELETE /api/projects/{id}               – delete project
  GET    /api/projects/{id}/tasks         – list tasks
  PUT    /api/tasks/{id}/status           – update task status
  GET    /api/projects/{id}/stats         – project KPI stats
  GET    /api/projects/{id}/history       – replan history
  POST   /api/projects/{id}/replan        – trigger autonomous replan
  POST   /api/projects/{id}/generate-plan – (re)generate AI plan for existing project
  GET    /api/stream/generate-plan        – SSE streaming plan generation
  POST   /api/upload-prd                  – upload PRD document
  GET    /api/health                      – health check

Run with:
  uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import json
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import aiofiles
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import database as db
from agent import replan_project, run_planner

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Project Planner API",
    description="REST API for the LangGraph-powered AI Project Planner Agent",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Robust path detection for frontend static files
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    app.mount("/frontend", StaticFiles(directory=str(frontend_dir), html=True), name="frontend_alt")

# Thread pool for blocking agent calls
_executor = ThreadPoolExecutor(max_workers=4)

# ─── Request / Response Models ────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=10)
    tech_stack: str = Field(..., min_length=2)
    deadline: str = Field(..., description="ISO date YYYY-MM-DD")
    weekly_hours: float = Field(default=20.0, ge=1.0, le=80.0)
    country: str = Field(default="US")
    generate_plan: bool = Field(default=True)


class UpdateTaskStatusRequest(BaseModel):
    status: str = Field(..., description="not_started|in_progress|completed|blocked|delayed")
    notes: str = Field(default="")


class ReplanRequest(BaseModel):
    blocked_task_id: str
    reason: str
    new_start_date: Optional[str] = None


class GeneratePlanRequest(BaseModel):
    weekly_hours: Optional[float] = None
    country: str = "US"


class ConfigureKeyRequest(BaseModel):
    provider: str = Field(default="openai", description="openai or anthropic")
    api_key: str = Field(..., min_length=5)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _run_in_thread(fn, *args):
    """Run a blocking function in the thread pool and await it."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "AI Project Planner API", "docs": "/docs", "frontend": "/app"}


# Handles both /api/health and /health so frontend never gets 404
@app.get("/api/health")
@app.get("/health")
async def health():
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    has_llm = bool(
        (openai_key and openai_key.startswith("sk-")) or
        (anthropic_key and len(anthropic_key) > 10)
    )
    provider = "openai" if (openai_key and openai_key.startswith("sk-")) else \
               ("anthropic" if has_llm else "none")
    return {
        "status": "ok",
        "has_llm_key": has_llm,
        "llm_provider": provider,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/config/key")
async def set_api_key(req: ConfigureKeyRequest):
    key = req.api_key.strip()
    provider = req.provider.strip().lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    var_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    os.environ[var_name] = key
    
    env_file = BASE_DIR / ".env"
    lines = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
    
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{var_name}="):
            new_lines.append(f"{var_name}={key}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{var_name}={key}")
        
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    
    return {
        "status": "ok",
        "provider": provider,
        "has_llm_key": True,
        "message": f"Successfully configured {provider.upper()} API key."
    }


# ── Projects ──────────────────────────────────────────────────────────────────

@app.get("/api/projects")
async def list_projects():
    db.init_db()
    projects = db.list_projects()
    for p in projects:
        try:
            p["stats"] = db.get_project_stats(p["id"])
        except Exception:
            p["stats"] = {}
    return {"projects": projects}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    db.init_db()
    project = db.load_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["stats"] = db.get_project_stats(project_id)
    return project


@app.post("/api/projects", status_code=201)
async def create_project(req: CreateProjectRequest):
    db.init_db()
    if req.generate_plan:
        def _run():
            return run_planner(
                project_name=req.name,
                description=req.description,
                tech_stack=req.tech_stack,
                deadline=req.deadline,
                weekly_hours=req.weekly_hours,
                country=req.country,
            )
        loop = asyncio.get_event_loop()
        state = await loop.run_in_executor(_executor, _run)

        if state.get("error"):
            raise HTTPException(status_code=500, detail=state["error"])

        project = db.load_project(state["project_id"])
        project["stats"] = db.get_project_stats(state["project_id"])
        project["tasks"] = db.load_tasks(state["project_id"])
        project["evaluation"] = state.get("evaluation", "")
        project["risk_result"] = state.get("risk_result", {})
        return JSONResponse(content=project, status_code=201)
    else:
        project_id = db.save_project(
            name=req.name,
            description=req.description,
            tech_stack=req.tech_stack,
            deadline=req.deadline,
            weekly_hours=req.weekly_hours,
        )
        project = db.load_project(project_id)
        project["stats"] = db.get_project_stats(project_id)
        return JSONResponse(content=project, status_code=201)


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    db.init_db()
    if not db.load_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete_project(project_id)
    return {"message": f"Project {project_id} deleted"}


# ── Tasks ─────────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/tasks")
async def get_tasks(project_id: int):
    db.init_db()
    if not db.load_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    tasks = db.load_tasks(project_id)
    return {"tasks": tasks}


@app.put("/api/tasks/{task_id}/status")
async def update_task_status(task_id: int, req: UpdateTaskStatusRequest):
    valid = {"not_started", "in_progress", "completed", "blocked", "delayed"}
    if req.status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status. Choose from: {valid}")
    db.update_task_status(task_id, req.status, req.notes)
    return {"message": "Task updated", "task_id": task_id, "status": req.status}


# ── Stats & History ───────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/stats")
async def get_stats(project_id: int):
    db.init_db()
    if not db.load_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return db.get_project_stats(project_id)


@app.get("/api/projects/{project_id}/history")
async def get_history(project_id: int):
    db.init_db()
    history = db.load_replan_history(project_id)
    return {"history": history}


# ── AI Actions ────────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/replan")
async def replan(project_id: int, req: ReplanRequest):
    db.init_db()
    if not db.load_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    def _run():
        return replan_project(
            project_id=project_id,
            blocked_task_id=req.blocked_task_id,
            reason=req.reason,
            new_start_date=req.new_start_date,
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _run)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    result["tasks"] = db.load_tasks(project_id)
    result["stats"] = db.get_project_stats(project_id)
    return result


@app.post("/api/projects/{project_id}/generate-plan")
async def regenerate_plan(project_id: int, req: GeneratePlanRequest):
    db.init_db()
    project = db.load_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    def _run():
        return run_planner(
            project_name=project["name"],
            description=project.get("description", ""),
            tech_stack=project.get("tech_stack", ""),
            deadline=project["deadline"],
            weekly_hours=req.weekly_hours or project.get("weekly_hours", 20.0),
            country=req.country,
        )

    loop = asyncio.get_event_loop()
    state = await loop.run_in_executor(_executor, _run)

    if state.get("error"):
        raise HTTPException(status_code=500, detail=state["error"])

    return {
        "project_id": state["project_id"],
        "tasks": db.load_tasks(state["project_id"]),
        "risk_result": state.get("risk_result", {}),
        "evaluation": state.get("evaluation", ""),
        "stats": db.get_project_stats(state["project_id"]),
    }


@app.get("/api/stream/generate-plan")
async def stream_generate_plan(
    name: str,
    description: str,
    tech_stack: str,
    deadline: str,
    weekly_hours: float = 20.0,
    country: str = "US",
):
    async def event_stream():
        async def send(event: str, message: str, payload: dict = None):
            data = json.dumps({"event": event, "message": message, "payload": payload or {}})
            yield f"data: {data}\n\n"

        try:
            async for chunk in send("start", "🤖 Agent initialising…"):
                yield chunk
            await asyncio.sleep(0.1)

            async for chunk in send("plan", "📋 Planning: decomposing project into tasks…"):
                yield chunk

            loop = asyncio.get_event_loop()
            fut = loop.run_in_executor(
                _executor,
                lambda: run_planner(
                    project_name=name,
                    description=description,
                    tech_stack=tech_stack,
                    deadline=deadline,
                    weekly_hours=weekly_hours,
                    country=country,
                ),
            )

            while not fut.done():
                await asyncio.sleep(3)
                if not fut.done():
                    async for chunk in send("heartbeat", "⏳ Still planning, please wait…"):
                        yield chunk

            state = await fut

            if state.get("error"):
                async for chunk in send("error", state["error"]):
                    yield chunk
                return

            async for chunk in send("schedule", "📅 Scheduling: assigning dates and dependencies…"):
                yield chunk
            await asyncio.sleep(0.2)

            async for chunk in send("risk", "⚠️  Risk analysis complete", state.get("risk_result", {})):
                yield chunk
            await asyncio.sleep(0.2)

            tasks = db.load_tasks(state["project_id"])
            async for chunk in send("complete", "✅ Plan generated successfully!", {
                "project_id": state["project_id"],
                "task_count": len(tasks),
                "risk_level": state.get("risk_result", {}).get("risk_level", "medium"),
                "evaluation": state.get("evaluation", ""),
            }):
                yield chunk

        except Exception as e:
            logger.exception("SSE stream error")
            data = json.dumps({"event": "error", "message": str(e), "payload": {}})
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── File Upload ───────────────────────────────────────────────────────────────

@app.post("/api/upload-prd")
async def upload_prd(file: UploadFile = File(...)):
    allowed = {".pdf", ".docx", ".md", ".txt"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {allowed}",
        )

    dest = UPLOAD_DIR / file.filename
    async with aiofiles.open(dest, "wb") as f:
        content = await file.read()
        await f.write(content)

    preview = ""
    try:
        if suffix in (".md", ".txt"):
            preview = content.decode("utf-8", errors="ignore")[:1500]
        elif suffix == ".docx":
            import docx as _docx
            doc = _docx.Document(str(dest))
            preview = "\n".join(p.text for p in doc.paragraphs if p.text.strip())[:1500]
        elif suffix == ".pdf":
            preview = f"[PDF uploaded: {file.filename}. Text extraction requires PyMuPDF.]"
    except Exception as e:
        preview = f"File uploaded but preview unavailable: {e}"

    return {
        "filename": file.filename,
        "size_bytes": len(content),
        "preview": preview,
        "path": str(dest),
    }

