# 🧠 AI Project Planner Agent

An autonomous, LangGraph-powered project planning assistant with a Streamlit dashboard.

---

## ✨ Features

| Feature | Details |
|---|---|
| **AI Task Decomposition** | LangGraph Plan→Act→Evaluate loop breaks any project into phased tasks |
| **Smart Scheduling** | Dates computed respecting working days, weekends, and public holidays |
| **Risk Analysis** | Deterministic engine scores tech complexity, deadline tightness, and workload |
| **Autonomous Replanning** | Block any task; the agent cascades date shifts to all dependents |
| **Interactive Dashboard** | Gantt chart, KPI metrics, task CRUD, phase distribution pie chart |
| **Persistent Storage** | SQLite database – no external service required |
| **CSV Export** | Download the full task list at any time |

---

## 🏗️ Project Structure

```
.
├── app.py            # Streamlit UI and dashboard
├── agent.py          # LangGraph workflow (Plan-Act-Evaluate-Save)
├── tools.py          # Pydantic models, date math, risk scoring
├── database.py       # SQLite schema and CRUD operations
├── requirements.txt  # Python dependencies
├── .env.example      # API key template
└── project_planner.db  # Created automatically on first run
```

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your LLM API key

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY or ANTHROPIC_API_KEY
```

### 3. Run the app

```bash
streamlit run app.py
```

Open your browser at **http://localhost:8501**

---

## 🤖 LangGraph Agent Architecture

```
User Input
    │
    ▼
┌─────────┐    ┌──────────────────────┐    ┌─────────────┐
│  PLAN   │───▶│  PARSE & SCHEDULE    │───▶│ ASSESS RISK │
│  (LLM)  │◀──│  (Pydantic + dates)  │    │ (heuristic) │
└─────────┘    └──────────────────────┘    └──────┬──────┘
  retry on                                        │
  bad JSON                                        ▼
                                         ┌─────────────────┐
                                         │    EVALUATE      │
                                         │  (LLM review)   │
                                         └────────┬────────┘
                                                  │
                                                  ▼
                                         ┌─────────────────┐
                                         │  SAVE TO SQLite  │
                                         └─────────────────┘
```

---

## 📋 Supported LLM Providers

| Provider | Model | Set in `.env` |
|---|---|---|
| **OpenAI** (preferred) | `gpt-4o-mini` | `OPENAI_API_KEY=sk-...` |
| **Anthropic** (fallback) | `claude-3-5-haiku` | `ANTHROPIC_API_KEY=sk-ant-...` |

---

## 🗂️ Database Schema

- **projects** – Name, tech stack, deadline, risk level, weekly hours
- **tasks** – Task ID, phase, priority, status, dates, dependencies, criteria
- **replan_history** – Log of every autonomous replanning event

---

## ⚙️ Tech Stack

- **Frontend**: Streamlit + custom CSS (glassmorphism dark theme)
- **Agent**: LangGraph `StateGraph` with conditional edges
- **Data**: Pydantic v2 models for validation
- **Scheduling**: Topological sort + `holidays` library
- **Persistence**: SQLite via `sqlite3` stdlib
- **Charts**: Plotly (Gantt + gauge + pie)
