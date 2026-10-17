/**
 * app.js — AI Project Planner Frontend
 * Connects the HTML/CSS UI to the FastAPI REST backend at /api/*
 */

'use strict';

// ─── Config ────────────────────────────────────────────────────────────────
const API_BASE = window.location.protocol.startsWith('http')
  ? `${window.location.origin}/api`
  : 'http://localhost:8000/api';

// ─── State ─────────────────────────────────────────────────────────────────
const state = {
  projects: [],
  activeProjectId: null,
  activeTasks: [],
  currentView: 'dashboard',
  streaming: false,
};

// ─── Utils ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const qs = sel => document.querySelector(sel);

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  });
  children.flat().forEach(c => {
    if (c === null || c === undefined || c === false) return;
    if (typeof c === 'string' || typeof c === 'number') e.append(c);
    else if (c instanceof Node) e.appendChild(c);
  });
  return e;
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'info', dur = 4000) {
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const t = el('div', { class: `toast toast-${type}` },
    el('span', {}, icons[type] || 'ℹ️'),
    el('span', { html: msg })
  );
  const container = $('toastContainer');
  container.appendChild(t);
  setTimeout(() => {
    t.classList.add('removing');
    setTimeout(() => t.remove(), 350);
  }, dur);
}

// ─── Navigation ──────────────────────────────────────────────────────────────
function navigate(view) {
  // Hide all views
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  // Deactivate all nav items
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const viewId = view === 'new-project' ? 'new-project' : view;
  const el = $(`view-${viewId}`);
  if (el) el.classList.add('active');

  const navBtn = qs(`[data-view="${view}"]`);
  if (navBtn) navBtn.classList.add('active');

  state.currentView = view;
  $('topbarView').textContent = viewLabels[view] || view;

  if (view === 'tasks') renderKanban();
  if (view === 'timeline') renderTimeline();
  if (view === 'history') loadHistory();
}

const viewLabels = {
  dashboard: 'Dashboard',
  agent: 'AI Agent',
  tasks: 'Task Board',
  timeline: 'Timeline',
  history: 'History',
  'new-project': 'New Project',
};

// ─── Health check ──────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const h = await apiFetch('/health');
    const el = $('apiStatus');
    const txt = $('apiStatusText');
    if (h.has_llm_key) {
      el.className = 'api-status ok';
      txt.textContent = `${h.llm_provider.toUpperCase()} connected`;
      el.title = 'Click to switch or update API key';
    } else {
      el.className = 'api-status warn';
      txt.textContent = 'No LLM key set (Click here)';
      el.title = 'Click to configure API key';
    }
  } catch {
    const el = $('apiStatus');
    el.className = 'api-status warn';
    $('apiStatusText').textContent = 'API offline';
    el.title = 'API is currently offline';
  }
}

// ─── Projects ───────────────────────────────────────────────────────────────
async function loadProjects() {
  try {
    const data = await apiFetch('/projects');
    state.projects = data.projects || [];
    renderProjectList();
    if (state.activeProjectId) {
      const p = state.projects.find(p => p.id === state.activeProjectId);
      if (p) renderDashboard(p);
    }
  } catch (e) {
    toast(`Failed to load projects: ${e.message}`, 'error');
  }
}

function renderProjectList() {
  const list = $('projectList');
  list.innerHTML = '';

  if (!state.projects.length) {
    list.innerHTML = '<div class="text-xs text-muted" style="padding:8px 20px">No projects yet</div>';
    return;
  }

  state.projects.forEach(p => {
    const riskColors = { low: '#4ade80', medium: '#fbbf24', high: '#fb923c', critical: '#ef4444' };
    const pct = p.stats?.progress_pct ?? 0;
    const item = el('div', {
      class: `project-item${p.id === state.activeProjectId ? ' selected' : ''}`,
      onclick: () => selectProject(p.id),
    },
      el('div', { class: 'project-item-dot', style: `background:${riskColors[p.risk_level] || '#94a3b8'}` }),
      el('div', { class: 'project-item-info' },
        el('div', { class: 'project-item-name', html: p.name }),
        el('div', { class: 'project-item-meta' }, `${pct}% · ${p.deadline || '—'}`),
      )
    );
    list.appendChild(item);
  });
}

async function selectProject(id) {
  state.activeProjectId = id;
  renderProjectList();
  try {
    const project = await apiFetch(`/projects/${id}`);
    const tasks = await apiFetch(`/projects/${id}/tasks`);
    state.activeTasks = tasks.tasks || [];
    renderDashboard(project);
    $('navTaskCount').textContent = state.activeTasks.length;
    $('topbarProject').textContent = project.name;
    navigate('dashboard');
  } catch (e) {
    toast(`Failed to load project: ${e.message}`, 'error');
  }
}

function renderDashboard(project) {
  $('welcomeBlock').classList.add('hidden');
  $('dashboardBlock').classList.remove('hidden');

  $('dashProjName').textContent = project.name;
  $('dashProjMeta').textContent =
    `Deadline: ${project.deadline || '—'} · Stack: ${project.tech_stack || '—'} · ${project.weekly_hours}h/week`;

  const stats = project.stats || {};
  $('kpiProgress').textContent = `${stats.progress_pct ?? 0}%`;
  $('kpiDone').textContent = stats.done ?? 0;
  $('kpiInProgress').textContent = stats.in_progress ?? 0;
  $('kpiOverdue').textContent = stats.overdue ?? 0;
  $('kpiBlocked').textContent = stats.blocked ?? 0;

  const pct = stats.progress_pct ?? 0;
  $('progressFill').style.width = `${pct}%`;
  $('progressPct').textContent = `${pct}%`;

  // Risk
  const rl = project.risk_level || 'medium';
  const riskMap = {
    low:      { emoji: '🟢', label: 'Low risk — looking good!',    pct: 20 },
    medium:   { emoji: '🟡', label: 'Medium risk — keep an eye on it.', pct: 45 },
    high:     { emoji: '🟠', label: 'High risk — immediate attention.', pct: 72 },
    critical: { emoji: '🔴', label: 'Critical risk — action required!', pct: 95 },
  };
  const rm = riskMap[rl] || riskMap.medium;
  $('riskEmoji').textContent = rm.emoji;
  $('riskLabel').textContent = rm.label;
  $('riskGaugeFill').style.width = `${rm.pct}%`;
  $('riskGaugeWrap').className = `risk-gauge-wrap mb-3 risk-${rl}`;
  const riskBadge = $('riskBadge');
  riskBadge.className = `badge badge-risk-${rl}`;
  riskBadge.textContent = rl.toUpperCase();

  const riskNotes = (project.risk_notes || '').split('\n').filter(Boolean);
  const ul = $('riskList');
  ul.innerHTML = riskNotes.length
    ? riskNotes.map(r => `<li>${r}</li>`).join('')
    : '<li style="color:var(--text-muted)">No risk notes available.</li>';

  // Evaluation
  $('evaluationText').textContent = project.evaluation || project._evaluation ||
    'No evaluation recorded. Re-generate the plan to get AI analysis.';

  // Phase chart
  renderPhaseChart(state.activeTasks);
}

function renderPhaseChart(tasks) {
  const chart = $('phaseChart');
  chart.innerHTML = '';
  if (!tasks.length) return;

  const phaseColors = {
    discovery: '#8b5cf6', planning: '#6366f1', design: '#a855f7',
    development: '#3b82f6', testing: '#06b6d4', deployment: '#10b981', maintenance: '#64748b',
  };

  const counts = {};
  tasks.forEach(t => {
    const ph = t.phase || 'development';
    counts[ph] = (counts[ph] || 0) + 1;
  });

  const max = Math.max(...Object.values(counts));
  Object.entries(counts).forEach(([phase, count]) => {
    const pct = (count / max) * 80;
    const col = el('div', { style: 'display:flex;flex-direction:column;align-items:center;gap:4px;flex:1' },
      el('div', { class: 'text-xs text-muted' }, count),
      el('div', {
        style: `height:${pct}px;min-height:6px;background:${phaseColors[phase]||'#6366f1'};border-radius:4px 4px 0 0;width:100%;opacity:0.85;transition:height .5s ease`,
        title: `${phase}: ${count} tasks`,
      }),
      el('div', { class: 'text-xs text-muted', style: 'writing-mode:vertical-rl;transform:rotate(180deg);height:60px' }, phase)
    );
    chart.appendChild(col);
  });
}

async function deleteCurrentProject() {
  if (!state.activeProjectId) return;
  const p = state.projects.find(p => p.id === state.activeProjectId);
  if (!confirm(`Delete "${p?.name}"? This cannot be undone.`)) return;
  try {
    await apiFetch(`/projects/${state.activeProjectId}`, { method: 'DELETE' });
    toast('Project deleted.', 'success');
    state.activeProjectId = null;
    state.activeTasks = [];
    $('welcomeBlock').classList.remove('hidden');
    $('dashboardBlock').classList.add('hidden');
    $('topbarProject').textContent = 'AI Project Planner';
    $('navTaskCount').textContent = '0';
    loadProjects();
  } catch (e) {
    toast(`Delete failed: ${e.message}`, 'error');
  }
}

// ─── Generate Plan (SSE streaming) ──────────────────────────────────────────
function setDeadlineDefault() {
  const d = new Date();
  d.setMonth(d.getMonth() + 2);
  $('newProjDeadline').value = d.toISOString().split('T')[0];
  $('replanDate').value = new Date().toISOString().split('T')[0];
}

async function generatePlan() {
  const name    = $('newProjName').value.trim();
  const desc    = $('newProjDesc').value.trim();
  const tech    = $('newProjTech').value.trim();
  const dl      = $('newProjDeadline').value;
  const hours   = parseFloat($('newProjHours').value) || 20;
  const country = $('newProjCountry').value || 'US';

  if (!name || !desc || !tech || !dl) {
    toast('Please fill in all required fields.', 'warning');
    return;
  }

  if (state.streaming) return;
  state.streaming = true;

  const btn = $('generatePlanBtn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner"></div> AI is planning…';
  }

  // Switch to agent view
  navigate('agent');
  resetStages();

  addChatMessage('user', `Create a plan for: **${name}**\nStack: ${tech} | Deadline: ${dl} | ${hours}h/week`);
  addChatMessage('ai', null, true); // typing indicator

  const params = new URLSearchParams({ name, description: desc, tech_stack: tech, deadline: dl, weekly_hours: hours, country });
  const url = `${API_BASE}/stream/generate-plan?${params}`;

  try {
    const es = new EventSource(url);
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleSSEEvent(data);
        if (data.event === 'complete' || data.event === 'error') {
          es.close();
          state.streaming = false;
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🚀 Generate AI Plan';
          }
          if (data.event === 'complete') {
            loadProjects();
            setTimeout(() => {
              if (data.payload?.project_id) {
                selectProject(data.payload.project_id);
              }
            }, 800);
          }
        }
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    };
    es.onerror = async () => {
      es.close();
      if (!state.streaming) return;
      // Fallback: direct POST call if SSE stream drops
      addChatMessage('ai', '⏳ Finalizing plan via direct execution…');
      try {
        const result = await apiFetch('/projects', {
          method: 'POST',
          body: JSON.stringify({
            name,
            description: desc,
            tech_stack: tech,
            deadline: dl,
            weekly_hours: hours,
            country,
            generate_plan: true
          }),
        });
        state.streaming = false;
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '🚀 Generate AI Plan';
        }
        removeTypingIndicator();
        setStage('complete');
        addChatMessage('ai', `✅ **Plan generated!** ${result.tasks?.length || 0} tasks created.\n\n` +
          `**Risk Level:** ${(result.risk_level || 'medium').toUpperCase()}\n\n` +
          (result.evaluation ? `**AI Evaluation:**\n${result.evaluation}` : ''));
        toast('Project plan generated successfully!', 'success');
        await loadProjects();
        if (result.id) selectProject(result.id);
      } catch (err) {
        state.streaming = false;
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '🚀 Generate AI Plan';
        }
        removeTypingIndicator();
        markStageError();
        addChatMessage('ai', `❌ **Planning failed:** ${err.message}`);
        toast(err.message, 'error');
      }
    };
  } catch (e) {
    state.streaming = false;
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '🚀 Generate AI Plan';
    }
    removeTypingIndicator();
    toast(`Error: ${e.message}`, 'error');
  }
}

function handleSSEEvent(data) {
  const { event, message, payload } = data;
  removeTypingIndicator();

  const stageMap = {
    start: 'stage-start', plan: 'stage-plan',
    schedule: 'stage-schedule', risk: 'stage-risk', complete: 'stage-complete',
  };

  if (stageMap[event]) setStage(event);

  if (event === 'heartbeat') {
    addChatMessage('ai', null, true);
    return;
  }

  if (event === 'error') {
    addChatMessage('ai', `❌ **Error:** ${message}`);
    markStageError();
    toast(message, 'error');
    return;
  }

  if (event === 'risk' && payload?.risk_level) {
    const riskEmojis = { low: '🟢', medium: '🟡', high: '🟠', critical: '🔴' };
    addChatMessage('ai', `${riskEmojis[payload.risk_level] || '⚠️'} **Risk Assessment:** ${payload.risk_level?.toUpperCase()}\n${(payload.risks||[]).join('\n')}`);
    return;
  }

  if (event === 'complete') {
    const { task_count, risk_level, evaluation } = payload;
    addChatMessage('ai',
      `✅ **Plan generated!** ${task_count} tasks created.\n\n` +
      `**Risk Level:** ${risk_level?.toUpperCase()}\n\n` +
      (evaluation ? `**AI Evaluation:**\n${evaluation}` : '')
    );
    toast(`Plan ready — ${task_count} tasks generated!`, 'success');
    return;
  }

  addChatMessage('ai', message);
}

// ─── Chat ───────────────────────────────────────────────────────────────────
function addChatMessage(role, content, typing = false) {
  const messages = $('chatMessages');
  const isAI = role === 'ai';

  let bubble;
  if (typing) {
    bubble = el('div', { class: 'chat-bubble', id: 'typingBubble' },
      el('div', { class: 'bubble-sender' }, 'AI Planner Agent'),
      el('div', { class: 'typing-indicator' },
        el('div', { class: 'typing-dot' }),
        el('div', { class: 'typing-dot' }),
        el('div', { class: 'typing-dot' }),
      )
    );
  } else {
    const formatted = (content || '').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
    bubble = el('div', { class: 'chat-bubble' },
      isAI ? el('div', { class: 'bubble-sender' }, 'AI Planner Agent') : null,
      el('span', { html: formatted })
    );
  }

  const avatar = el('div', {
    class: `chat-avatar ${isAI ? 'avatar-ai' : 'avatar-user'}`,
    html: isAI ? '🧠' : '👤',
  });

  const msg = el('div', { class: `chat-message${isAI ? '' : ' user'}` },
    avatar, bubble
  );
  messages.appendChild(msg);
  messages.scrollTop = messages.scrollHeight;
}

function removeTypingIndicator() {
  const typing = $('typingBubble');
  if (typing) typing.closest('.chat-message')?.remove();
}

function handleChatKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendAgentMessage();
  }
}

async function sendAgentMessage() {
  const input = $('agentPrompt');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  addChatMessage('user', msg);
  addChatMessage('ai', null, true);

  const pid = state.activeProjectId;
  const lower = msg.toLowerCase();

  // If no project selected OR user wants to create/plan a project:
  const isCreateIntent = !pid ||
    lower.startsWith('create') ||
    lower.startsWith('build') ||
    lower.startsWith('plan') ||
    lower.startsWith('make') ||
    lower.includes('project') ||
    lower.includes('app') ||
    msg.length > 25;

  if (isCreateIntent && (!pid || lower.includes('create') || lower.includes('plan') || lower.includes('new') || lower.includes('build') || lower.includes('app'))) {
    removeTypingIndicator();
    addChatMessage('ai', `🧠 **Decomposing your project specifications…**\n\nStarting autonomous LangGraph plan generation for: *"${msg}"*`);

    // Auto populate project form fields
    const title = msg.length > 36 ? msg.slice(0, 32) + '…' : msg;
    $('newProjName').value = title;
    $('newProjDesc').value = msg;
    if (!$('newProjTech').value) $('newProjTech').value = 'Python, FastAPI, SQLite, React';
    setDeadlineDefault();

    // Trigger autonomous plan generation
    setTimeout(() => {
      generatePlan();
    }, 350);
    return;
  }

  // Simple contextual responses based on current project state
  await new Promise(r => setTimeout(r, 600));
  removeTypingIndicator();

  const tasks = state.activeTasks;
  if (!pid) {
    addChatMessage('ai', 'To get started, tell me what project you want to build (e.g. *"Build an AI SaaS platform in React and FastAPI"*) or click **＋ New Project** in the sidebar!');
    return;
  }

  //const lower = msg.toLowerCase();
  if (lower.includes('risk') || lower.includes('concern')) {
    const project = state.projects.find(p => p.id === pid);
    const notes = (project?.risk_notes || '').split('\n').filter(Boolean);
    addChatMessage('ai', notes.length
      ? `**Risk factors for this project:**\n${notes.join('\n')}`
      : 'No specific risk notes recorded. Run the risk analysis to get an updated assessment.'
    );
  } else if (lower.includes('blocked') || lower.includes('stuck')) {
    const blocked = tasks.filter(t => t.status === 'blocked' || t.status === 'delayed');
    addChatMessage('ai', blocked.length
      ? `**Blocked/delayed tasks:**\n${blocked.map(t => `• ${t.task_id}: ${t.title}`).join('\n')}`
      : 'Great news — no blocked tasks right now! 🎉'
    );
  } else if (lower.includes('progress') || lower.includes('complete')) {
    const done = tasks.filter(t => t.status === 'completed').length;
    addChatMessage('ai', `**Progress:** ${done}/${tasks.length} tasks completed.\nOverall: ${Math.round(done/Math.max(tasks.length,1)*100)}%`);
  } else if (lower.includes('next') || lower.includes('priority')) {
    const next = tasks
      .filter(t => t.status !== 'completed')
      .sort((a, b) => {
        const po = { critical: 0, high: 1, medium: 2, low: 3 };
        return (po[a.priority] || 2) - (po[b.priority] || 2);
      }).slice(0, 3);
    addChatMessage('ai', next.length
      ? `**Top priority tasks:**\n${next.map(t => `• ${t.task_id} [${t.priority}]: ${t.title}`).join('\n')}`
      : 'All tasks are completed — great work! 🚀'
    );
  } else if (lower.includes('deadline')) {
    const project = state.projects.find(p => p.id === pid);
    const dl = project?.deadline;
    const days = dl ? Math.ceil((new Date(dl) - new Date()) / 86400000) : null;
    addChatMessage('ai', days !== null
      ? `**Deadline:** ${dl} — that's ${days > 0 ? `${days} days away` : `${Math.abs(days)} days overdue! ⚠️`}`
      : 'No deadline set for this project.'
    );
  } else {
    addChatMessage('ai',
      `I'm your AI project planning assistant! I can tell you about:\n` +
      `• **Risks** — ask "What are the risks?"\n` +
      `• **Blocked tasks** — ask "Any blockers?"\n` +
      `• **Progress** — ask "How's progress?"\n` +
      `• **Priorities** — ask "What's next?"\n` +
      `• **Deadline** — ask "When is the deadline?"\n\n` +
      `To generate a full AI plan, use the **New Project** form.`
    );
  }
}

// ─── Stage bar ───────────────────────────────────────────────────────────────
function resetStages() {
  ['stage-start','stage-plan','stage-schedule','stage-risk','stage-complete'].forEach(id => {
    $(id).className = 'stage';
  });
}

function setStage(event) {
  const order = ['start', 'plan', 'schedule', 'risk', 'complete'];
  const idx = order.indexOf(event);
  order.forEach((s, i) => {
    const el = $(`stage-${s}`);
    if (i < idx) el.className = 'stage done';
    else if (i === idx) el.className = 'stage active';
    else el.className = 'stage';
  });
}

function markStageError() {
  const active = qs('.stage.active');
  if (active) active.className = 'stage error';
}

// ─── Kanban ──────────────────────────────────────────────────────────────────
const PRIORITY_ICON = { critical: '🔴', high: '🟠', medium: '🟡', low: '🟢' };
const PHASE_ABBR = { discovery:'DIS', planning:'PLN', design:'DES', development:'DEV', testing:'TST', deployment:'DEP', maintenance:'MNT' };

function renderKanban() {
  const phaseFilter    = $('phaseFilter').value;
  const priorityFilter = $('priorityFilter').value;

  let tasks = state.activeTasks;
  if (phaseFilter)    tasks = tasks.filter(t => t.phase    === phaseFilter);
  if (priorityFilter) tasks = tasks.filter(t => t.priority === priorityFilter);

  const columns = {
    not_started: { el: $('colTodo'),     count: $('countTodo') },
    in_progress:  { el: $('colProgress'), count: $('countProgress') },
    blocked:      { el: $('colBlocked'), count: $('countBlocked') },
    delayed:      { el: $('colBlocked'), count: $('countBlocked') },
    completed:    { el: $('colDone'),    count: $('countDone') },
  };

  // Clear
  Object.values(columns).forEach(c => c.el.innerHTML = '');
  const counts = { not_started:0, in_progress:0, blocked:0, completed:0 };

  const today = new Date().toISOString().split('T')[0];

  tasks.forEach(task => {
    const status = task.status || 'not_started';
    const col = columns[status] || columns.not_started;

    const isOverdue = task.end_date && task.end_date < today && status !== 'completed';
    const card = el('div', {
      class: 'task-card',
      onclick: () => openTaskDetail(task),
    },
      el('div', { class: 'task-card-id' }, `${task.task_id || '—'}${isOverdue ? '  ⚠️ OVERDUE' : ''}`),
      el('div', { class: 'task-card-title' }, task.title || 'Untitled'),
      el('div', { class: 'task-card-meta' },
        el('span', { class: 'task-card-phase' }, PHASE_ABBR[task.phase] || task.phase || '—'),
        el('span', { class: `badge badge-${task.priority||'medium'}` },
          `${PRIORITY_ICON[task.priority]||'⚪'} ${task.priority||'—'}`
        ),
        el('span', { class: 'task-card-duration' }, `📅 ${task.duration_days||1}d`)
      )
    );

    const colStatus = ['blocked','delayed'].includes(status) ? 'blocked' : status;
    counts[colStatus] = (counts[colStatus] || 0) + 1;
    col.el.appendChild(card);
  });

  $('countTodo').textContent     = counts.not_started;
  $('countProgress').textContent = counts.in_progress;
  $('countBlocked').textContent  = counts.blocked;
  $('countDone').textContent     = counts.completed;

  const empty = $('tasksEmptyState');
  const kanban = $('kanbanBoard');
  if (!tasks.length) {
    kanban.style.display = 'none';
    empty.classList.remove('hidden');
  } else {
    kanban.style.display = 'grid';
    empty.classList.add('hidden');
  }

  const meta = $('taskBoardMeta');
  if (state.activeProjectId) {
    const p = state.projects.find(p => p.id === state.activeProjectId);
    meta.textContent = p ? `${p.name} · ${tasks.length} tasks` : `${tasks.length} tasks`;
  }
}

// ─── Task Detail ─────────────────────────────────────────────────────────────
let _activeTask = null;

function openTaskDetail(task) {
  _activeTask = task;
  $('detailTaskId').textContent = task.task_id || '';
  $('detailTaskTitle').textContent = task.title || '';
  $('detailPhase').textContent = task.phase || '—';
  $('detailDuration').textContent = `${task.duration_days || 1} working days`;
  $('detailStart').textContent = task.start_date || '—';
  $('detailEnd').textContent = task.end_date || '—';
  $('detailDescription').textContent = task.description || 'No description provided.';
  $('detailCriteria').textContent = task.completion_criteria || 'No criteria specified.';

  $('detailPriority').innerHTML = `<span class="badge badge-${task.priority||'medium'}">${PRIORITY_ICON[task.priority]||'⚪'} ${task.priority||'medium'}</span>`;
  $('detailStatus').innerHTML   = badgeHTML(task.status);

  const select = $('detailStatusSelect');
  select.value = task.status || 'not_started';
  $('detailNotes').value = task.notes || '';

  const depsEl = $('detailDeps');
  depsEl.innerHTML = '';
  const deps = task.dependencies || [];
  if (deps.length) {
    deps.forEach(d => {
      depsEl.appendChild(el('span', { class: 'badge badge-not-started font-mono' }, d));
    });
  } else {
    depsEl.textContent = 'None';
  }

  $('detailSaveBtn').onclick = () => saveTaskStatus(task.id, task);
  $('taskDetailOverlay').classList.add('open');
}

function closeTaskDetail() { $('taskDetailOverlay').classList.remove('open'); }
window.addEventListener('keydown', e => { if (e.key === 'Escape') { closeTaskDetail(); closeReplanModal(); } });
$('taskDetailOverlay').addEventListener('click', e => { if (e.target === $('taskDetailOverlay')) closeTaskDetail(); });

async function saveTaskStatus(taskDbId, task) {
  const status = $('detailStatusSelect').value;
  const notes  = $('detailNotes').value;
  try {
    await apiFetch(`/tasks/${taskDbId}/status`, {
      method: 'PUT',
      body: JSON.stringify({ status, notes }),
    });
    toast(`Task ${task.task_id} → ${status}`, 'success');
    closeTaskDetail();
    // Refresh
    const data = await apiFetch(`/projects/${state.activeProjectId}/tasks`);
    state.activeTasks = data.tasks || [];
    renderKanban();
    if (state.currentView === 'dashboard') {
      const project = await apiFetch(`/projects/${state.activeProjectId}`);
      renderDashboard(project);
    }
    loadProjects();
  } catch (e) {
    toast(`Update failed: ${e.message}`, 'error');
  }
}

function badgeHTML(status) {
  const map = {
    not_started: 'Not Started', in_progress: 'In Progress',
    completed: 'Completed', blocked: 'Blocked', delayed: 'Delayed',
  };
  const cls = status === 'not_started' ? 'not-started' : status === 'in_progress' ? 'in-progress' : status;
  return `<span class="badge badge-${cls}">${map[status] || status}</span>`;
}

// ─── Timeline ───────────────────────────────────────────────────────────────
function renderTimeline() {
  const list = $('timelineList');
  const empty = $('timelineEmpty');
  const gantt = $('ganttBars');
  list.innerHTML = '';
  gantt.innerHTML = '';

  const tasks = [...state.activeTasks]
    .filter(t => t.start_date)
    .sort((a, b) => a.start_date.localeCompare(b.start_date));

  if (!tasks.length) {
    list.classList.add('hidden');
    empty.classList.remove('hidden');
    return;
  }
  list.classList.remove('hidden');
  empty.classList.add('hidden');

  // Mini Gantt
  const dates = tasks.flatMap(t => [t.start_date, t.end_date]).filter(Boolean).sort();
  const minDate = new Date(dates[0]);
  const maxDate = new Date(dates[dates.length - 1]);
  const totalDays = Math.max((maxDate - minDate) / 86400000, 1);
  $('ganttDateRange').textContent = `${dates[0]} → ${dates[dates.length-1]}`;

  const phaseColors = { discovery:'#8b5cf6',planning:'#6366f1',design:'#a855f7',development:'#3b82f6',testing:'#06b6d4',deployment:'#10b981',maintenance:'#64748b' };
  const statusOp = { completed:1, in_progress:0.75, not_started:0.45, blocked:0.5, delayed:0.5 };

  const ganttWrap = el('div', { style: 'min-width:600px;padding:10px 0' });
  tasks.slice(0, 20).forEach(t => {
    const tStart = t.start_date ? (new Date(t.start_date) - minDate) / 86400000 : 0;
    const tEnd   = t.end_date   ? (new Date(t.end_date)   - minDate) / 86400000 : tStart + 1;
    const left  = (tStart / totalDays * 100).toFixed(2);
    const width = Math.max(((tEnd - tStart) / totalDays * 100), 1).toFixed(2);
    const color = phaseColors[t.phase] || '#6366f1';
    const op    = statusOp[t.status] || 0.5;

    const row = el('div', { style: 'display:flex;align-items:center;gap:8px;margin-bottom:5px' },
      el('div', { class: 'text-xs font-mono text-muted', style: 'width:60px;text-align:right;flex-shrink:0' }, t.task_id),
      el('div', { style: 'flex:1;position:relative;height:22px;background:rgba(255,255,255,0.04);border-radius:4px;overflow:hidden' },
        el('div', {
          style: `position:absolute;left:${left}%;width:${width}%;height:100%;background:${color};opacity:${op};border-radius:4px;display:flex;align-items:center;padding:0 6px`,
          title: `${t.title} (${t.start_date} → ${t.end_date})`
        },
          el('span', { style: 'font-size:.62rem;color:white;white-space:nowrap;overflow:hidden;text-overflow:ellipsis' }, t.title)
        )
      )
    );
    ganttWrap.appendChild(row);
  });
  gantt.appendChild(ganttWrap);

  // Timeline items
  const today = new Date().toISOString().split('T')[0];
  tasks.forEach(task => {
    const isDone   = task.status === 'completed';
    const isActive = task.status === 'in_progress';
    const isOver   = task.end_date && task.end_date < today && !isDone;

    const dotClass = isDone ? 'done' : isActive ? 'active' : '';
    const phaseColor = phaseColors[task.phase] || '#6366f1';

    const item = el('div', { class: 'timeline-item' },
      el('div', { class: `timeline-dot ${dotClass}` }),
      el('div', { class: 'timeline-content' },
        el('div', { class: 'timeline-date' }, `${task.start_date || '—'} → ${task.end_date || '—'}`),
        el('div', { class: 'timeline-title' },
          `${PRIORITY_ICON[task.priority]||'⚪'} ${task.title}${isOver ? ' ⚠️' : ''}`
        ),
        el('div', { class: 'timeline-meta', style: 'display:flex;gap:8px;flex-wrap:wrap;margin-top:5px' },
          el('span', { html: badgeHTML(task.status) }),
          el('span', { class: 'badge', style: `background:${phaseColor}22;color:${phaseColor};border:1px solid ${phaseColor}44` }, task.phase || '—'),
          el('span', { class: 'text-xs text-muted' }, `${task.duration_days || 1}d · ${task.task_id}`),
        )
      )
    );
    list.appendChild(item);
  });
}

// ─── History ─────────────────────────────────────────────────────────────────
async function loadHistory() {
  const list  = $('historyList');
  const empty = $('historyEmpty');
  list.innerHTML = '';

  if (!state.activeProjectId) {
    empty.classList.remove('hidden');
    return;
  }

  try {
    const data = await apiFetch(`/projects/${state.activeProjectId}/history`);
    const events = data.history || [];

    if (!events.length) {
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');

    events.forEach(ev => {
      const changes = ev.changes || [];
      const card = el('div', { class: 'card mb-3' },
        el('div', { class: 'card-header' },
          el('div', {},
            el('div', { class: 'card-title' }, `🔄 Replan — ${ev.created_at?.slice(0,16).replace('T',' ')}`),
            el('div', { class: 'card-subtitle' }, ev.reason || '—'),
          ),
          el('span', { class: 'badge badge-in-progress' }, `${changes.length} tasks updated`),
        )
      );

      if (changes.length) {
        const table = el('table', { class: 'data-table' },
          el('thead', {},
            el('tr', {},
              el('th', {}, 'Task ID'), el('th', {}, 'Title'),
              el('th', {}, 'New Start'), el('th', {}, 'New End'),
            )
          ),
          el('tbody', {},
            ...changes.map(c =>
              el('tr', {},
                el('td', { class: 'font-mono' }, c.task_id || ''),
                el('td', {}, c.title || ''),
                el('td', { class: 'font-mono' }, c.start_date || '—'),
                el('td', { class: 'font-mono' }, c.end_date || '—'),
              )
            )
          )
        );
        card.appendChild(table);
      }
      list.appendChild(card);
    });
  } catch (e) {
    toast(`Failed to load history: ${e.message}`, 'error');
  }
}

// ─── Replan Modal ─────────────────────────────────────────────────────────────
function openReplanModal() {
  if (!state.activeProjectId) { toast('Select a project first.', 'warning'); return; }

  const sel = $('replanTaskSelect');
  sel.innerHTML = '';
  const nonDone = state.activeTasks.filter(t => t.status !== 'completed');
  if (!nonDone.length) { toast('All tasks are completed — nothing to replan!', 'info'); return; }

  nonDone.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t.task_id;
    opt.textContent = `${t.task_id} · ${t.title}`;
    sel.appendChild(opt);
  });

  $('replanModal').classList.add('open');
}

function closeReplanModal() { $('replanModal').classList.remove('open'); }
$('replanModal').addEventListener('click', e => { if (e.target === $('replanModal')) closeReplanModal(); });

// ─── Key Configuration Modal ──────────────────────────────────────────────────
function openKeyModal() {
  const modal = $('keyModal');
  if (!modal) return;
  modal.classList.add('open');
  setTimeout(() => $('inputApiKey')?.focus(), 50);
}

function closeKeyModal() {
  const modal = $('keyModal');
  if (!modal) return;
  modal.classList.remove('open');
}

$('keyModal')?.addEventListener('click', e => {
  if (e.target === $('keyModal')) closeKeyModal();
});

function onKeyProviderChange() {
  const prov = $('keyProviderSelect').value;
  const lbl = $('keyInputLabel');
  const inp = $('inputApiKey');
  const help = $('keyHelpText');
  if (prov === 'openai') {
    if (lbl) lbl.textContent = 'OpenAI API Key';
    if (inp) inp.placeholder = 'sk-...';
    if (help) help.innerHTML = 'OpenAI keys start with <code>sk-</code>. Get one at <a href="https://platform.openai.com/api-keys" target="_blank" style="color:var(--indigo-400);text-decoration:underline;">platform.openai.com</a>.';
  } else {
    if (lbl) lbl.textContent = 'Anthropic API Key';
    if (inp) inp.placeholder = 'sk-ant-...';
    if (help) help.innerHTML = 'Anthropic keys start with <code>sk-ant-</code>. Get one at <a href="https://console.anthropic.com/" target="_blank" style="color:var(--indigo-400);text-decoration:underline;">console.anthropic.com</a>.';
  }
}

async function submitApiKey() {
  const provider = $('keyProviderSelect').value;
  const key = $('inputApiKey').value.trim();

  if (!key) {
    toast('Please enter your API key.', 'warning');
    return;
  }

  const btn = $('keySubmitBtn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Saving…';

  try {
    const res = await apiFetch('/config/key', {
      method: 'POST',
      body: JSON.stringify({ provider, api_key: key }),
    });

    toast(`✅ ${res.message || 'API key saved!'}`, 'success');
    closeKeyModal();
    $('inputApiKey').value = '';
    await checkHealth();
  } catch (err) {
    toast(`Failed to save key: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '💾 Save & Connect';
  }
}

async function submitReplan() {
  const taskId = $('replanTaskSelect').value;
  const reason = $('replanReason').value.trim();
  const date   = $('replanDate').value;

  if (!reason) { toast('Please provide a reason for the delay.', 'warning'); return; }

  const btn = $('replanSubmitBtn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Replanning…';

  try {
    const result = await apiFetch(`/projects/${state.activeProjectId}/replan`, {
      method: 'POST',
      body: JSON.stringify({ blocked_task_id: taskId, reason, new_start_date: date || null }),
    });

    toast(`✅ Replan complete — ${result.updated_tasks?.length || 0} tasks updated.`, 'success');

    navigate('agent');
    addChatMessage('ai',
      `🔄 **Replan complete** for task ${taskId}.\n` +
      `Reason: ${reason}\n` +
      `Tasks rescheduled: ${result.updated_tasks?.length || 0}\n\n` +
      (result.evaluation || '')
    );

    // Refresh state
    state.activeTasks = result.tasks || state.activeTasks;
    closeReplanModal();
    $('replanReason').value = '';
    renderKanban();
    loadProjects();
  } catch (e) {
    toast(`Replan failed: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🤖 Run Autonomous Replan';
  }
}

// ─── File Upload ─────────────────────────────────────────────────────────────
async function handleFileUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const form = new FormData();
  form.append('file', file);

  try {
    const res = await fetch(`${API_BASE}/upload-prd`, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');

    $('prdFileName').textContent = `${data.filename} (${(data.size_bytes/1024).toFixed(1)} KB)`;
    $('prdPreviewText').textContent = data.preview || 'No preview available.';
    $('prdPreview').classList.remove('hidden');
    toast('PRD uploaded successfully!', 'success');

    // Pre-fill description if empty
    if (!$('newProjDesc').value && data.preview) {
      $('newProjDesc').value = data.preview.slice(0, 600);
    }
  } catch (e) {
    toast(`Upload failed: ${e.message}`, 'error');
  }
}

// Setup drop zone
function setupDropZone() {
  const dz = $('dropZone');
  ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('dragging'); }));
  ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('dragging'); }));
  dz.addEventListener('drop', e => {
    const file = e.dataTransfer.files[0];
    if (file) {
      const input = $('prdFile');
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      handleFileUpload(input);
    }
  });
}

// ─── Init ────────────────────────────────────────────────────────────────────
async function init() {
  setDeadlineDefault();
  setupDropZone();
  await checkHealth();
  await loadProjects();
}

init();
