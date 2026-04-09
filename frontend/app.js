const messagesEl = document.getElementById('messages');
const stateEl = document.getElementById('state');
const entityEl = document.getElementById('entityDetail');
const debugEl = document.getElementById('debugDetail');
const sessionInput = document.getElementById('sessionId');
const sessionList = document.getElementById('sessionList');
const composer = document.getElementById('composer');
const input = document.getElementById('input');
const reloadBtn = document.getElementById('reloadBtn');
const deleteSessionBtn = document.getElementById('deleteSessionBtn');
const newGameBtn = document.getElementById('newGameBtn');
const regenerateBtn = document.getElementById('regenerateBtn');
const statusBar = document.getElementById('statusBar');
const debugPanel = document.getElementById('debugPanel');
const stateColumn = document.getElementById('stateColumn');
const settingsBtn = document.getElementById('settingsBtn');
const settingsPanel = document.getElementById('settingsPanel');
const settingsBackdrop = document.getElementById('settingsBackdrop');
const settingsCloseBtn = document.getElementById('settingsCloseBtn');
const sessionIndicator = document.getElementById('sessionIndicator');
const characterNameEl = document.getElementById('characterName');
const characterSubtitleEl = document.getElementById('characterSubtitle');
const characterCoverEl = document.getElementById('characterCover');
const characterCoverFallbackEl = document.getElementById('characterCoverFallback');

let lastDebug = null;
let lastCharacterCard = null;
let shouldStickToBottom = true;
let pendingUserMessage = null;
let lastHistoryItems = [];
let webConfig = {
  default_debug: false,
  history_page_size: 80,
  show_state_panel: true,
  show_debug_panel: false,
};

function applyWebConfig(nextConfig = {}) {
  webConfig = {
    ...webConfig,
    ...nextConfig,
  };
  if (debugPanel) {
    debugPanel.hidden = !webConfig.show_debug_panel;
    if (!webConfig.show_debug_panel) {
      debugPanel.open = false;
    } else if (webConfig.default_debug) {
      debugPanel.open = true;
    }
  }
  if (stateColumn) {
    stateColumn.hidden = !webConfig.show_state_panel;
  }
}

function openSettings() {
  if (!settingsPanel || !settingsBackdrop) return;
  settingsPanel.dataset.open = 'true';
  settingsPanel.setAttribute('aria-hidden', 'false');
  settingsBackdrop.hidden = false;
  settingsBtn?.setAttribute('aria-expanded', 'true');
}

function closeSettings() {
  if (!settingsPanel || !settingsBackdrop) return;
  settingsPanel.dataset.open = 'false';
  settingsPanel.setAttribute('aria-hidden', 'true');
  settingsBackdrop.hidden = true;
  settingsBtn?.setAttribute('aria-expanded', 'false');
}

function updateSessionIndicator() {
  if (sessionIndicator) {
    sessionIndicator.textContent = sessionId();
  }
}

function renderCharacterCard(card) {
  lastCharacterCard = card || null;
  const name = card?.name || card?.title || '未命名角色卡';
  const subtitle = card?.subtitle || card?.summary || '待加载';

  if (characterNameEl) characterNameEl.textContent = name;
  if (characterSubtitleEl) characterSubtitleEl.textContent = subtitle;

  const initials = (name || 'TL').trim().slice(0, 2);
  if (characterCoverFallbackEl) {
    characterCoverFallbackEl.textContent = initials;
  }

  if (characterCoverEl) {
    if (card?.cover_url) {
      characterCoverEl.src = `${card.cover_url}?v=${Date.now()}`;
      characterCoverEl.hidden = false;
      if (characterCoverFallbackEl) characterCoverFallbackEl.hidden = true;
    } else {
      characterCoverEl.hidden = true;
      characterCoverEl.removeAttribute('src');
      if (characterCoverFallbackEl) characterCoverFallbackEl.hidden = false;
    }
  }
}

function resetSidePanels() {
  if (entityEl) {
    entityEl.textContent = '点击右侧状态里的 NPC 名称查看';
  }
  renderDebug(null);
}

function setStatus(text, kind = 'info') {
  statusBar.textContent = text;
  statusBar.dataset.kind = kind;
}

function sessionId() {
  return sessionInput.value.trim() || 'story-live';
}

function formatSessionOption(item) {
  const tags = [];
  if (item.archived) tags.push('archive');
  if (item.replay) tags.push('replay');
  return tags.length ? `${item.session_id} [${tags.join(',')}]` : item.session_id;
}

async function loadSessions() {
  const res = await fetch('/api/sessions');
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || 'session list load failed');
  applyWebConfig(data.web || {});
  renderCharacterCard(data.character_card || lastCharacterCard);
  if (!sessionList) return;
  const current = sessionId();
  const recommended = data.default_session_id || (data.sessions || []).find(item => !item.archived && !item.replay)?.session_id || current;
  if (!sessionInput.value.trim() || sessionInput.value.trim() === 'story-live') {
    sessionInput.value = recommended;
  }
  sessionList.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = '选择已有 session';
  sessionList.appendChild(placeholder);
  for (const item of data.sessions || []) {
    const option = document.createElement('option');
    option.value = item.session_id;
    option.textContent = formatSessionOption(item);
    if (item.session_id === sessionId()) option.selected = true;
    sessionList.appendChild(option);
  }
  updateSessionIndicator();
}

function renderMessages(items) {
  lastHistoryItems = items;
  messagesEl.innerHTML = '';
  const allItems = [...items];
  if (pendingUserMessage) {
    allItems.push({role: 'user', content: pendingUserMessage, pending: true});
  }
  for (const item of allItems) {
    const article = document.createElement('article');
    article.className = `msg ${item.role}`;
    if (item.pending) article.classList.add('pending');

    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = item.role === 'user' ? 'Player' : 'World';

    const body = document.createElement('div');
    body.className = 'msg-body';
    body.textContent = item.content;

    article.appendChild(label);
    article.appendChild(body);
    messagesEl.appendChild(article);
  }
  if (shouldStickToBottom) {
    focusLatestAssistant({ smooth: false });
  }
}

function scrollToLatest(options = {}) {
  const smooth = Boolean(options.smooth);
  requestAnimationFrame(() => {
    messagesEl.scrollTo({
      top: messagesEl.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    });
  });
}

function focusLatestAssistant(options = {}) {
  const smooth = Boolean(options.smooth);
  requestAnimationFrame(() => {
    const assistants = messagesEl.querySelectorAll('.msg.assistant');
    const latest = assistants[assistants.length - 1];
    if (latest) {
      latest.scrollIntoView({block: 'end', behavior: smooth ? 'smooth' : 'auto'});
    } else {
      scrollToLatest({ smooth });
    }
  });
}

function isNearBottom(threshold = 96) {
  const distance = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight;
  return distance <= threshold;
}

function npcLink(name, entityId) {
  const btn = document.createElement('button');
  btn.className = 'npc-link';
  btn.textContent = name;
  btn.onclick = () => loadEntity(entityId);
  return btn;
}

function renderState(state) {
  stateEl.innerHTML = '';
  const rows = [
    ['时间', state.time],
    ['地点', state.location],
    ['主事件', state.main_event],
    ['局势核心', state.scene_core],
    ['当前目标', state.immediate_goal],
    ['场景风险', (state.immediate_risks || []).join(' / ') || '暂无'],
    ['延续线索', (state.carryover_clues || []).join(' / ') || '暂无'],
  ];
  const table = document.createElement('table');
  table.className = 'state-table';
  for (const [label, value] of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<th>${label}</th><td>${value || '待确认'}</td>`;
    table.appendChild(tr);
  }
  stateEl.appendChild(table);

  function buildNpcTable(title, items) {
    const wrap = document.createElement('div');
    wrap.className = 'npc-block';
    const heading = document.createElement('strong');
    heading.textContent = title;
    wrap.appendChild(heading);

    const table = document.createElement('table');
    table.className = 'state-table npc-table';
    const tbody = document.createElement('tbody');

    if (!items || items.length === 0) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<th>状态</th><td>暂无</td>';
      tbody.appendChild(tr);
    } else {
      items.forEach((item, idx) => {
        const tr = document.createElement('tr');
        const th = document.createElement('th');
        th.textContent = `${idx + 1}`;
        const td = document.createElement('td');
        const name = item?.name || '待确认';
        const entityId = item?.entity_id || null;
        const roleLabel = item?.role_label || '';
        const ambiguous = Boolean(item?.ambiguous);
        const label = roleLabel ? `${name} / ${roleLabel}` : name;

        if (entityId && !ambiguous) {
          td.appendChild(npcLink(label, entityId));
        } else if (ambiguous) {
          const span = document.createElement('span');
          span.className = 'npc-fallback';
          span.textContent = `${label}（存在多个同名实体）`;
          td.appendChild(span);
        } else {
          const span = document.createElement('span');
          span.className = 'npc-fallback';
          span.textContent = label;
          td.appendChild(span);
        }
        tr.appendChild(th);
        tr.appendChild(td);
        tbody.appendChild(tr);
      });
    }

    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  stateEl.appendChild(buildNpcTable('Onstage NPCs', state.onstage_entities || []));
  stateEl.appendChild(buildNpcTable('Relevant NPCs', state.relevant_entities || []));

  const threads = state.active_threads || [];
  const threadWrap = document.createElement('div');
  threadWrap.className = 'npc-block';
  const threadHeading = document.createElement('strong');
  threadHeading.textContent = 'Active Threads';
  threadWrap.appendChild(threadHeading);

  const threadTable = document.createElement('table');
  threadTable.className = 'state-table npc-table';
  const threadBody = document.createElement('tbody');
  if (!threads.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<th>状态</th><td>暂无</td>';
    threadBody.appendChild(tr);
  } else {
    threads.slice(0, 5).forEach((item, idx) => {
      const tr = document.createElement('tr');
      const th = document.createElement('th');
      th.textContent = `${idx + 1}`;
      const td = document.createElement('td');
      td.textContent = `${item.thread_id || 'thread'} / ${item.status || 'active'} / ${item.label || '待确认'}`;
      tr.appendChild(th);
      tr.appendChild(td);
      threadBody.appendChild(tr);
    });
  }
  threadTable.appendChild(threadBody);
  threadWrap.appendChild(threadTable);
  stateEl.appendChild(threadWrap);
}

function renderDebug(debug) {
  if (!debugEl) return;
  lastDebug = debug || null;
  if (regenerateBtn) {
    const isPartial = debug && debug.completion_status === 'partial';
    regenerateBtn.hidden = !isPartial;
  }
  if (!debug) {
    debugEl.textContent = '本轮未返回调试信息';
    return;
  }
  debugEl.textContent = JSON.stringify({
    arbiter_analysis: debug.arbiter_analysis || null,
    arbiter_results: debug.arbiter_results || [],
    state_keeper_diagnostics: debug.state_keeper_diagnostics || null,
    retained_threads: debug.retained_threads || [],
    retained_entities: debug.retained_entities || [],
    completion_status: debug.completion_status || null,
    finish_reason: debug.finish_reason || null,
    state_error: debug.state_error || null,
    model_error: debug.model_error || null,
  }, null, 2);
}

async function regenerateLast() {
  const res = await fetch('/api/regenerate-last', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sessionId()})
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || 'regenerate failed');
  pendingUserMessage = null;
  await loadHistory();
  renderState(data.state_snapshot || {});
  renderDebug(data.debug || null);
  shouldStickToBottom = true;
  focusLatestAssistant({ smooth: false });
}

async function loadHistory() {
  const res = await fetch(`/api/history?session_id=${encodeURIComponent(sessionId())}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || 'history load failed');
  applyWebConfig(data.web || {});
  const wasNearBottom = isNearBottom();
  pendingUserMessage = null;
  renderCharacterCard(data.character_card || lastCharacterCard);
  updateSessionIndicator();
  renderMessages(data.messages || []);
  if (wasNearBottom) {
    shouldStickToBottom = true;
  }
}

async function loadState() {
  const res = await fetch(`/api/state?session_id=${encodeURIComponent(sessionId())}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || 'state load failed');
  applyWebConfig(data.web || {});
  renderCharacterCard(data.character_card || lastCharacterCard);
  updateSessionIndicator();
  renderState(data.state || {});
}

async function startNewGame() {
  const res = await fetch('/api/new-game', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sessionId()})
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || 'new game failed');
  sessionInput.value = data.session_id || sessionId();
  pendingUserMessage = null;
  renderMessages(data.messages || []);
  renderState(data.state_snapshot || {});
  await loadSessions();
  resetSidePanels();
  renderDebug({new_game: {session_id: data.session_id || sessionId(), archived_to: data.archived_to || null}});
  updateSessionIndicator();
  closeSettings();
  shouldStickToBottom = true;
  focusLatestAssistant({ smooth: false });
}

async function deleteSession() {
  const current = sessionId();
  const res = await fetch('/api/delete-session', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: current})
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || 'delete session failed');
  const next = (data.sessions || []).find(item => !item.archived && !item.replay)?.session_id || 'story-live';
  sessionInput.value = next;
  await loadSessions();
  await loadHistory();
  await loadState();
  resetSidePanels();
  renderDebug({session_deleted: {session_id: current, next_session: next, deleted_paths: data.deleted_paths || []}});
  updateSessionIndicator();
  closeSettings();
}

async function loadEntity(entityId) {
  const res = await fetch(`/api/entity?session_id=${encodeURIComponent(sessionId())}&entity_id=${encodeURIComponent(entityId)}`);
  const data = await res.json();
  if (!res.ok) {
    entityEl.textContent = JSON.stringify(data, null, 2);
    return;
  }
  entityEl.textContent = JSON.stringify(data.entity || data, null, 2);
}

composer.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  const submitButton = composer.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  setStatus('发送中...', 'working');
  pendingUserMessage = text;
  renderMessages(lastHistoryItems);
  try {
    const res = await fetch('/api/message', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session_id: sessionId(),
        text,
        client_turn_id: `web-${Date.now()}`,
        meta: {source: 'web', debug: webConfig.default_debug}
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error?.message || 'message send failed');
    shouldStickToBottom = true;
    await loadHistory();
    renderState(data.state_snapshot || {});
    renderCharacterCard(data.character_card || lastCharacterCard);
    renderDebug(data.debug || null);
    updateSessionIndicator();
    if (shouldStickToBottom) {
      focusLatestAssistant({ smooth: false });
    }
    input.value = '';
    setStatus('已更新', 'ok');
  } catch (err) {
    pendingUserMessage = null;
    renderMessages(lastHistoryItems);
    setStatus(`错误：${err.message}`, 'error');
  } finally {
    submitButton.disabled = false;
  }
});

deleteSessionBtn.addEventListener('click', async () => {
  setStatus('删除会话中...', 'working');
  try {
    await deleteSession();
    setStatus('会话已删除', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    composer.requestSubmit();
  }
});

reloadBtn.addEventListener('click', async () => {
  setStatus('刷新中...', 'working');
  try {
    resetSidePanels();
    await loadSessions();
    await loadHistory();
    await loadState();
    closeSettings();
    setStatus('已刷新', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

sessionList.addEventListener('change', async () => {
  if (!sessionList.value) return;
  sessionInput.value = sessionList.value;
  setStatus('切换会话中...', 'working');
  try {
    resetSidePanels();
    await loadHistory();
    await loadState();
    closeSettings();
    setStatus('已切换', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

newGameBtn.addEventListener('click', async () => {
  setStatus('新游戏初始化中...', 'working');
  try {
    await startNewGame();
    setStatus('新游戏已开始', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

regenerateBtn.addEventListener('click', async () => {
  setStatus('重新生成中...', 'working');
  try {
    await regenerateLast();
    setStatus('已重新生成', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

messagesEl.addEventListener('scroll', () => {
  shouldStickToBottom = isNearBottom();
});

settingsBtn?.addEventListener('click', () => {
  if (settingsPanel?.dataset.open === 'true') {
    closeSettings();
  } else {
    openSettings();
  }
});

settingsCloseBtn?.addEventListener('click', closeSettings);
settingsBackdrop?.addEventListener('click', closeSettings);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeSettings();
  }
});

(async function init() {
  setStatus('初始化中...', 'working');
  try {
    resetSidePanels();
    await loadSessions();
    await loadHistory();
    await loadState();
    closeSettings();
    shouldStickToBottom = true;
    focusLatestAssistant({ smooth: false });
    setStatus('就绪', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
})();
