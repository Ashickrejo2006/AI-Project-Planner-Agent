"""
app.py
------
Streamlit dashboard for the AI Project Planner Agent.
Run with:  streamlit run app.py
"""

import json
import logging
import os
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

import database as db
from agent import replan_project, run_planner

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Project Planner",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  /* Dark gradient background */
  .stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #1a1a3e 40%, #0d1b2a 100%);
    color: #e2e8f0;
  }

  /* Sidebar */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1e1b4b 0%, #0f172a 100%);
    border-right: 1px solid rgba(99,102,241,0.3);
  }
  [data-testid="stSidebar"] * { color: #c7d2fe !important; }
  [data-testid="stSidebar"] h1,
  [data-testid="stSidebar"] h2,
  [data-testid="stSidebar"] h3 { color: #a5b4fc !important; }

  /* Metric cards */
  [data-testid="stMetric"] {
    background: rgba(99,102,241,0.12);
    border: 1px solid rgba(99,102,241,0.3);
    border-radius: 12px;
    padding: 16px;
    backdrop-filter: blur(10px);
    transition: transform .2s ease, box-shadow .2s ease;
  }
  [data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(99,102,241,0.25);
  }
  [data-testid="stMetricLabel"] { color: #94a3b8 !important; font-size: .8rem; }
  [data-testid="stMetricValue"] { color: #c7d2fe !important; font-weight: 700; }

  /* Hero banner */
  .hero-banner {
    background: linear-gradient(135deg, rgba(99,102,241,0.2) 0%, rgba(168,85,247,0.15) 100%);
    border: 1px solid rgba(99,102,241,0.4);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 24px;
    backdrop-filter: blur(12px);
  }
  .hero-banner h1 {
    font-size: 2rem;
    font-weight: 800;
    background: linear-gradient(90deg, #a5b4fc, #e879f9);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0 0 4px;
  }
  .hero-banner p { color: #94a3b8; margin: 0; }

  /* Tabs */
  [data-testid="stTabs"] button {
    color: #94a3b8 !important;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    transition: all .2s;
  }
  [data-testid="stTabs"] button[aria-selected="true"] {
    color: #a5b4fc !important;
    border-bottom: 2px solid #6366f1 !important;
  }

  /* Task cards */
  .task-card {
    background: rgba(15,12,41,0.6);
    border: 1px solid rgba(99,102,241,0.25);
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 10px;
    transition: border-color .2s ease;
  }
  .task-card:hover { border-color: rgba(99,102,241,0.6); }

  /* Status badges */
  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 9999px;
    font-size: .72rem;
    font-weight: 600;
    letter-spacing: .04em;
  }
  .badge-completed  { background: rgba(34,197,94,0.2);  color: #4ade80; border: 1px solid #4ade80; }
  .badge-inprogress { background: rgba(59,130,246,0.2); color: #60a5fa; border: 1px solid #60a5fa; }
  .badge-notstarted { background: rgba(100,116,139,0.2);color: #94a3b8; border: 1px solid #94a3b8; }
  .badge-blocked    { background: rgba(239,68,68,0.2);  color: #f87171; border: 1px solid #f87171; }
  .badge-delayed    { background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid #fbbf24; }

  /* Risk level colours */
  .risk-low      { color: #4ade80; }
  .risk-medium   { color: #fbbf24; }
  .risk-high     { color: #f97316; }
  .risk-critical { color: #ef4444; }

  /* Buttons */
  [data-testid="stButton"] button {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    transition: opacity .2s, transform .2s;
  }
  [data-testid="stButton"] button:hover {
    opacity: .88;
    transform: translateY(-1px);
  }

  /* Divider */
  hr { border-color: rgba(99,102,241,0.2) !important; }

  /* DataFrames */
  [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }

  /* Expander */
  [data-testid="stExpander"] {
    background: rgba(15,12,41,0.4);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 10px;
  }

  /* Inputs */
  [data-testid="stTextInput"] input,
  [data-testid="stTextArea"] textarea,
  [data-testid="stNumberInput"] input,
  [data-testid="stSelectbox"] div {
    background: rgba(15,12,41,0.7) !important;
    border: 1px solid rgba(99,102,241,0.3) !important;
    color: #e2e8f0 !important;
    border-radius: 8px !important;
  }

  /* Plotly chart background */
  .js-plotly-plot { border-radius: 12px; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: rgba(15,12,41,0.5); }
  ::-webkit-scrollbar-thumb { background: rgba(99,102,241,0.5); border-radius: 3px; }

  /* Alert boxes */
  .stAlert { border-radius: 10px !important; }
</style>
""", unsafe_allow_html=True)


# ─── Helper functions ──────────────────────────────────────────────────────────

def _badge(status: str) -> str:
    cls = {
        "completed": "badge-completed",
        "in_progress": "badge-inprogress",
        "not_started": "badge-notstarted",
        "blocked": "badge-blocked",
        "delayed": "badge-delayed",
    }.get(status, "badge-notstarted")
    label = status.replace("_", " ").title()
    return f'<span class="badge {cls}">{label}</span>'


def _priority_icon(p: str) -> str:
    return {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(p, "⚪")


def _risk_class(level: str) -> str:
    return f"risk-{level}"


def _plotly_dark_layout(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94a3b8"),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def _check_api_key() -> bool:
    """Return True if at least one LLM key is available."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(
        (openai_key and openai_key.startswith("sk-")) or
        (anthropic_key and len(anthropic_key) > 10)
    )


# ─── Session State Init ───────────────────────────────────────────────────────

for k, v in {
    "active_project_id": None,
    "generating": False,
    "replan_mode": False,
    "last_error": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🧠 AI Project Planner")
    st.markdown("---")

    # API Key Status
    has_key = _check_api_key()
    if has_key:
        st.success("✅ LLM API key detected", icon="🔑")
    else:
        st.warning("⚠️ No API key found", icon="🔑")
        with st.expander("Configure API Key"):
            st.markdown(
                "Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in a `.env` file "
                "in the same directory as `app.py`."
            )
            st.code("OPENAI_API_KEY=sk-...")

    st.markdown("---")
    st.markdown("### 📋 New Project")

    with st.form("new_project_form", clear_on_submit=False):
        proj_name = st.text_input("Project Name *", placeholder="e.g. E-commerce Platform")
        proj_desc = st.text_area(
            "Description *",
            placeholder="Describe your project goals, features, and constraints...",
            height=120,
        )
        tech_stack = st.text_input(
            "Tech Stack *",
            placeholder="e.g. React, FastAPI, PostgreSQL, Docker",
        )

        col_a, col_b = st.columns(2)
        with col_a:
            deadline = st.date_input(
                "Deadline *",
                value=date.today().replace(month=date.today().month % 12 + 1),
                min_value=date.today(),
            )
        with col_b:
            weekly_hours = st.number_input(
                "Weekly Hours",
                min_value=1.0,
                max_value=80.0,
                value=20.0,
                step=1.0,
            )

        country = st.selectbox(
            "Holiday Region",
            options=["US", "GB", "IN", "AU", "CA", "DE", "FR"],
            index=0,
        )

        submitted = st.form_submit_button(
            "🚀 Generate Plan",
            use_container_width=True,
            disabled=not has_key,
        )

    # Project selector
    st.markdown("---")
    st.markdown("### 📁 Existing Projects")
    db.init_db()
    all_projects = db.list_projects()
    if all_projects:
        proj_options = {f"{p['id']} · {p['name']}": p["id"] for p in all_projects}
        selected_label = st.selectbox(
            "Load Project",
            options=list(proj_options.keys()),
            index=0,
        )
        if st.button("📂 Load", use_container_width=True):
            st.session_state.active_project_id = proj_options[selected_label]
            st.rerun()

        if st.button("🗑️ Delete Selected", use_container_width=True):
            pid = proj_options[selected_label]
            db.delete_project(pid)
            if st.session_state.active_project_id == pid:
                st.session_state.active_project_id = None
            st.rerun()
    else:
        st.info("No projects yet. Create one above.")


# ─── Handle Form Submission ────────────────────────────────────────────────────

if submitted:
    if not proj_name.strip():
        st.sidebar.error("Project Name is required.")
    elif not proj_desc.strip():
        st.sidebar.error("Description is required.")
    elif not tech_stack.strip():
        st.sidebar.error("Tech Stack is required.")
    else:
        with st.spinner("🤖 Agent is planning your project… this may take 30-60 seconds."):
            try:
                final_state = run_planner(
                    project_name=proj_name.strip(),
                    description=proj_desc.strip(),
                    tech_stack=tech_stack.strip(),
                    deadline=deadline.isoformat(),
                    weekly_hours=float(weekly_hours),
                    country=country,
                )
                if final_state.get("error"):
                    st.error(f"❌ {final_state['error']}")
                    st.session_state.last_error = final_state["error"]
                else:
                    st.session_state.active_project_id = final_state["project_id"]
                    st.session_state.last_error = None
                    st.success("✅ Project plan created successfully!")
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Unexpected error: {e}")
                logger.exception("Form submission error")


# ─── Main Dashboard ────────────────────────────────────────────────────────────

st.markdown("""
<div class="hero-banner">
  <h1>🧠 AI Project Planner Agent</h1>
  <p>Autonomous task decomposition · Smart scheduling · Risk analysis · Dynamic replanning</p>
</div>
""", unsafe_allow_html=True)

if not st.session_state.active_project_id:
    # Welcome screen
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class="task-card" style="text-align:center; padding:30px;">
          <div style="font-size:2.5rem">🤖</div>
          <h3 style="color:#a5b4fc; margin:10px 0 6px;">AI Decomposition</h3>
          <p style="color:#94a3b8; font-size:.87rem;">
            LangGraph agent breaks your project into phased, prioritised tasks automatically.
          </p>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div class="task-card" style="text-align:center; padding:30px;">
          <div style="font-size:2.5rem">📅</div>
          <h3 style="color:#a5b4fc; margin:10px 0 6px;">Smart Scheduling</h3>
          <p style="color:#94a3b8; font-size:.87rem;">
            Dates calculated respecting working days, holidays, and task dependencies.
          </p>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div class="task-card" style="text-align:center; padding:30px;">
          <div style="font-size:2.5rem">🔄</div>
          <h3 style="color:#a5b4fc; margin:10px 0 6px;">Auto Replanning</h3>
          <p style="color:#94a3b8; font-size:.87rem;">
            Block a task and the agent cascades schedule changes across dependents.
          </p>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.info("👈  Fill in the **New Project** form in the sidebar and click **Generate Plan** to begin.", icon="💡")
    st.stop()


# ─── Load Active Project ───────────────────────────────────────────────────────

project = db.load_project(st.session_state.active_project_id)
if not project:
    st.error("Project not found. Please select another project.")
    st.session_state.active_project_id = None
    st.stop()

tasks = db.load_tasks(st.session_state.active_project_id)
stats = db.get_project_stats(st.session_state.active_project_id)

# ─── Header ───────────────────────────────────────────────────────────────────

risk_level = project.get("risk_level", "medium")
risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk_level, "⚪")

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.markdown(f"## 📌 {project['name']}")
    st.caption(f"Created: {project['created_at'][:10]}  |  Deadline: {project['deadline']}  |  "
               f"Risk: {risk_emoji} **{risk_level.title()}**  |  "
               f"Weekly hours: {project.get('weekly_hours', 20)}")
with col_h2:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

# ─── KPI Metrics ──────────────────────────────────────────────────────────────

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("📊 Progress", f"{stats.get('progress_pct', 0)}%")
m2.metric("✅ Completed", stats.get("done", 0))
m3.metric("🔵 In Progress", stats.get("in_progress", 0))
m4.metric("⚠️ Overdue", stats.get("overdue", 0))
m5.metric("🚫 Blocked", stats.get("blocked", 0))

# Progress bar
progress = stats.get("progress_pct", 0) / 100
bar_col = st.columns(1)[0]
st.progress(progress, text=f"Overall completion: {stats.get('progress_pct', 0)}%")

st.markdown("---")

# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab_tasks, tab_gantt, tab_risk, tab_replan, tab_history = st.tabs([
    "📋 Task Board",
    "📅 Timeline (Gantt)",
    "⚠️  Risk Analysis",
    "🔄 Replan",
    "📜 History",
])


# ──────────────────────────────────────────────────────────────────────────────
# TAB 1: TASK BOARD
# ──────────────────────────────────────────────────────────────────────────────

with tab_tasks:
    if not tasks:
        st.info("No tasks found for this project.")
    else:
        # Filter controls
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            filter_status = st.multiselect(
                "Filter by Status",
                options=["not_started", "in_progress", "completed", "blocked", "delayed"],
                default=[],
            )
        with fc2:
            filter_phase = st.multiselect(
                "Filter by Phase",
                options=sorted({t.get("phase", "") for t in tasks if t.get("phase")}),
                default=[],
            )
        with fc3:
            filter_priority = st.multiselect(
                "Filter by Priority",
                options=["critical", "high", "medium", "low"],
                default=[],
            )

        displayed = tasks
        if filter_status:
            displayed = [t for t in displayed if t["status"] in filter_status]
        if filter_phase:
            displayed = [t for t in displayed if t.get("phase") in filter_phase]
        if filter_priority:
            displayed = [t for t in displayed if t.get("priority") in filter_priority]

        # Editable task table
        st.markdown(f"**Showing {len(displayed)} of {len(tasks)} tasks**")

        today_str = date.today().isoformat()
        for task in displayed:
            is_overdue = (
                task.get("end_date", "") < today_str
                and task["status"] not in ("completed",)
                and task.get("end_date", "")
            )
            border_color = "rgba(239,68,68,0.5)" if is_overdue else "rgba(99,102,241,0.25)"

            with st.expander(
                f"{_priority_icon(task.get('priority','medium'))}  "
                f"**{task['task_id']}** · {task['title']}  "
                f"({'⚠️ OVERDUE' if is_overdue else task.get('phase','').title()})",
                expanded=False,
            ):
                col_left, col_right = st.columns([2, 1])
                with col_left:
                    st.markdown(f"**Description:** {task.get('description','—')}")
                    st.markdown(f"**Completion Criteria:** {task.get('completion_criteria','—')}")
                    deps = task.get("dependencies", [])
                    st.markdown(f"**Dependencies:** {', '.join(deps) if deps else 'None'}")
                    if task.get("notes"):
                        st.markdown(f"**Notes:** {task['notes']}")

                with col_right:
                    st.markdown(
                        f"Status: {_badge(task['status'])}",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**Phase:** {task.get('phase','').title()}")
                    st.markdown(f"**Priority:** {_priority_icon(task.get('priority','medium'))} {task.get('priority','').title()}")
                    st.markdown(f"**Duration:** {task.get('duration_days', 1)} working days")
                    st.markdown(f"**Start:** {task.get('start_date','—')}")
                    st.markdown(f"**End:** {task.get('end_date','—')}")

                # Status override
                st.markdown("**Update Status:**")
                uc1, uc2, uc3 = st.columns(3)
                new_status = uc1.selectbox(
                    "New Status",
                    options=["not_started", "in_progress", "completed", "blocked", "delayed"],
                    index=["not_started", "in_progress", "completed", "blocked", "delayed"].index(
                        task["status"] if task["status"] in
                        ["not_started","in_progress","completed","blocked","delayed"]
                        else "not_started"
                    ),
                    key=f"status_{task['id']}",
                    label_visibility="collapsed",
                )
                new_notes = uc2.text_input(
                    "Notes",
                    value=task.get("notes", ""),
                    key=f"notes_{task['id']}",
                    label_visibility="collapsed",
                    placeholder="Add a note…",
                )
                if uc3.button("💾 Save", key=f"save_{task['id']}"):
                    db.update_task_status(task["id"], new_status, new_notes)
                    st.success(f"Task {task['task_id']} updated to **{new_status}**.")
                    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# TAB 2: GANTT CHART
# ──────────────────────────────────────────────────────────────────────────────

with tab_gantt:
    if not tasks:
        st.info("No tasks to display.")
    else:
        gantt_data = []
        for t in tasks:
            if t.get("start_date") and t.get("end_date"):
                gantt_data.append({
                    "Task": f"{t['task_id']}: {t['title'][:40]}",
                    "Start": t["start_date"],
                    "Finish": t["end_date"],
                    "Phase": t.get("phase", "development").title(),
                    "Status": t["status"].replace("_", " ").title(),
                    "Priority": t.get("priority", "medium").title(),
                })

        if gantt_data:
            df_gantt = pd.DataFrame(gantt_data)
            color_map = {
                "Discovery": "#6366f1",
                "Planning": "#8b5cf6",
                "Design": "#a855f7",
                "Development": "#3b82f6",
                "Testing": "#06b6d4",
                "Deployment": "#10b981",
                "Maintenance": "#64748b",
            }
            fig = px.timeline(
                df_gantt,
                x_start="Start",
                x_end="Finish",
                y="Task",
                color="Phase",
                color_discrete_map=color_map,
                hover_data=["Status", "Priority"],
                title="Project Gantt Chart",
            )
            fig.update_yaxes(autorange="reversed")
            fig = _plotly_dark_layout(fig)
            fig.update_layout(
                title_font_size=16,
                legend_title_text="Phase",
                xaxis_title="",
                yaxis_title="",
                height=max(400, len(gantt_data) * 34),
            )
            # Mark today
            fig.add_vline(
                x=datetime.now().timestamp() * 1000,
                line_dash="dash",
                line_color="#f87171",
                annotation_text="Today",
                annotation_font_color="#f87171",
            )
            # Mark deadline
            try:
                ddl = datetime.fromisoformat(project["deadline"]).timestamp() * 1000
                fig.add_vline(
                    x=ddl,
                    line_dash="dot",
                    line_color="#fbbf24",
                    annotation_text="Deadline",
                    annotation_font_color="#fbbf24",
                )
            except Exception:
                pass

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Tasks don't have dates yet. Regenerate the plan.")

        # Phase breakdown pie
        st.markdown("### Phase Distribution")
        phase_counts = {}
        for t in tasks:
            p = t.get("phase", "development").title()
            phase_counts[p] = phase_counts.get(p, 0) + 1

        pie_fig = go.Figure(go.Pie(
            labels=list(phase_counts.keys()),
            values=list(phase_counts.values()),
            hole=0.5,
            marker=dict(
                colors=["#6366f1","#8b5cf6","#a855f7","#3b82f6","#06b6d4","#10b981","#64748b"],
                line=dict(color="#0f0c29", width=2),
            ),
            textinfo="label+percent",
            textfont=dict(color="#c7d2fe"),
        ))
        pie_fig.update_layout(
            title="Tasks by Phase",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", color="#94a3b8"),
            showlegend=False,
            height=350,
        )
        st.plotly_chart(pie_fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3: RISK ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

with tab_risk:
    risk_notes_raw = project.get("risk_notes", "")
    risk_lines = [ln.strip() for ln in risk_notes_raw.split("\n") if ln.strip()]

    rl = project.get("risk_level", "medium")
    risk_colour = {"low": "#4ade80", "medium": "#fbbf24",
                   "high": "#f97316", "critical": "#ef4444"}.get(rl, "#fbbf24")

    # Risk gauge
    gauge_fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value={"low": 20, "medium": 45, "high": 70, "critical": 95}.get(rl, 45),
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "Risk Score", "font": {"color": "#94a3b8", "size": 18}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#64748b"},
            "bar": {"color": risk_colour},
            "bgcolor": "rgba(0,0,0,0)",
            "steps": [
                {"range": [0, 33],  "color": "rgba(74,222,128,0.15)"},
                {"range": [33, 66], "color": "rgba(251,191,36,0.15)"},
                {"range": [66, 100],"color": "rgba(239,68,68,0.15)"},
            ],
            "threshold": {
                "line": {"color": risk_colour, "width": 4},
                "thickness": 0.85,
                "value": {"low": 20, "medium": 45, "high": 70, "critical": 95}.get(rl, 45),
            },
        },
        number={"font": {"color": risk_colour}},
    ))
    gauge_fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94a3b8"),
        height=280,
        margin=dict(l=20, r=20, t=30, b=10),
    )
    rc1, rc2 = st.columns([1, 2])
    with rc1:
        st.plotly_chart(gauge_fig, use_container_width=True)
    with rc2:
        st.markdown(f"### Risk Level: <span class='{_risk_class(rl)}'>{rl.upper()}</span>",
                    unsafe_allow_html=True)
        if risk_lines:
            st.markdown("**Identified Risks:**")
            for ln in risk_lines:
                st.markdown(f"- {ln}")
        else:
            st.info("No specific risks recorded.")

    st.markdown("---")

    # Re-run risk analysis on demand
    if st.button("🔍 Re-run Risk Analysis", use_container_width=False):
        from tools import RiskInput, assess_risk
        with st.spinner("Analysing risks…"):
            result = assess_risk(
                RiskInput(
                    project_name=project["name"],
                    tech_stack=project.get("tech_stack", ""),
                    deadline=project["deadline"],
                    weekly_hours=project.get("weekly_hours", 20.0),
                    tasks=tasks,
                )
            )
            db.update_project(
                st.session_state.active_project_id,
                risk_level=result["risk_level"],
                risk_notes="\n".join(result["risks"]),
            )
            st.success("Risk analysis updated.")
            st.markdown("**Recommendations:**")
            for rec in result.get("recommendations", []):
                st.markdown(f"- ✅ {rec}")
            st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# TAB 4: REPLAN
# ──────────────────────────────────────────────────────────────────────────────

with tab_replan:
    st.markdown("### 🔄 Autonomous Replanning")
    st.markdown(
        "Select a blocked or delayed task and the agent will reschedule all dependent tasks automatically."
    )

    if not tasks:
        st.info("No tasks to replan.")
    else:
        rp_col1, rp_col2 = st.columns(2)
        with rp_col1:
            task_options = {f"{t['task_id']} · {t['title']}": t["task_id"] for t in tasks
                           if t["status"] not in ("completed",)}
            if not task_options:
                st.success("All tasks are completed! No replanning needed.")
            else:
                selected_task_label = st.selectbox(
                    "Blocked / Delayed Task",
                    options=list(task_options.keys()),
                )
                selected_task_id = task_options[selected_task_label]

                block_reason = st.text_area(
                    "Reason for Delay / Block",
                    placeholder="e.g. Third-party API unavailable, waiting for design approval…",
                    height=90,
                )
                new_start = st.date_input(
                    "Revised Start Date for Blocked Task",
                    value=date.today(),
                    min_value=date.today(),
                )

        with rp_col2:
            # Show dependent tasks
            sel_id = task_options.get(selected_task_label, "") if task_options else ""
            if sel_id:
                deps_affected = [
                    t for t in tasks
                    if sel_id in (t.get("dependencies") or [])
                ]
                st.markdown("**Tasks that will be affected:**")
                if deps_affected:
                    for d in deps_affected:
                        st.markdown(
                            f"- {_priority_icon(d.get('priority','medium'))} "
                            f"`{d['task_id']}` {d['title']}",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("No downstream dependents found for this task.")

        if task_options and st.button(
            "🤖 Run Autonomous Replan", use_container_width=True,
            disabled=not block_reason.strip()
        ):
            with st.spinner("Agent is replanning dependent tasks…"):
                result = replan_project(
                    project_id=st.session_state.active_project_id,
                    blocked_task_id=selected_task_id,
                    reason=block_reason.strip(),
                    new_start_date=new_start.isoformat(),
                )
                if result.get("error"):
                    st.error(result["error"])
                else:
                    st.success(
                        f"✅ Replanning complete. "
                        f"{len(result.get('updated_tasks', []))} task(s) rescheduled."
                    )
                    st.info(result.get("evaluation", ""))
                    new_risk = result.get("risk_result", {})
                    if new_risk:
                        rl = new_risk.get("risk_level", "medium")
                        _replan_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(rl, "⚪")
                        st.markdown(f"Updated Risk Level: **{rl.upper()}**  {_replan_emoji}")
                    st.rerun()



# ──────────────────────────────────────────────────────────────────────────────
# TAB 5: HISTORY
# ──────────────────────────────────────────────────────────────────────────────

with tab_history:
    st.markdown("### 📜 Replan History")
    history = db.load_replan_history(st.session_state.active_project_id)
    if not history:
        st.info("No replanning events recorded yet.")
    else:
        for event in history:
            with st.expander(
                f"🔄 Replan on {event['created_at'][:16]} — {event['reason'][:60]}…",
                expanded=False,
            ):
                st.markdown(f"**Reason:** {event['reason']}")
                st.markdown(f"**Tasks Changed:** {len(event.get('changes', []))}")
                if event.get("changes"):
                    change_df = pd.DataFrame([
                        {
                            "Task ID": c.get("task_id", ""),
                            "Title": c.get("title", ""),
                            "New Start": c.get("start_date", ""),
                            "New End": c.get("end_date", ""),
                        }
                        for c in event["changes"]
                    ])
                    st.dataframe(change_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 📊 Project Summary")
    pj = project
    summary_data = {
        "Field": ["Name", "Description", "Tech Stack", "Deadline", "Weekly Hours",
                  "Status", "Risk Level", "Created"],
        "Value": [
            pj.get("name", ""),
            pj.get("description", "")[:120] + ("…" if len(pj.get("description", "")) > 120 else ""),
            pj.get("tech_stack", ""),
            pj.get("deadline", ""),
            str(pj.get("weekly_hours", "")),
            pj.get("status", "active").title(),
            pj.get("risk_level", "").title(),
            pj.get("created_at", "")[:16],
        ],
    }
    st.dataframe(
        pd.DataFrame(summary_data),
        use_container_width=True,
        hide_index=True,
    )

    # Export tasks as CSV
    if tasks:
        task_export = pd.DataFrame([
            {k: v for k, v in t.items() if k != "dependencies"}
            | {"dependencies": ", ".join(t.get("dependencies", []))}
            for t in tasks
        ])
        csv = task_export.to_csv(index=False)
        st.download_button(
            "⬇️ Export Tasks as CSV",
            data=csv,
            file_name=f"{pj['name'].replace(' ','_')}_tasks.csv",
            mime="text/csv",
            use_container_width=True,
        )
