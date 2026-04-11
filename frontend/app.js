const messagesEl = document.getElementById('messages');
const stateEl = document.getElementById('state');
const entityEl = document.getElementById('entityDetail');
const debugEl = document.getElementById('debugDetail');
const composer = document.getElementById('composer');
const input = document.getElementById('input');
const regenerateBtn = document.getElementById('regenerateBtn');
const statusBar = document.getElementById('statusBar');
const debugPanel = document.getElementById('debugPanel');
const stateColumn = document.getElementById('stateColumn');
const settingsBtn = document.getElementById('settingsBtn');
const settingsPanel = document.getElementById('settingsPanel');
const settingsBackdrop = document.getElementById('settingsBackdrop');
const settingsCloseBtn = document.getElementById('settingsCloseBtn');
const sessionIndicator = document.getElementById('sessionIndicator');
const sessionIndicatorLabel = document.getElementById('sessionIndicatorLabel');
const characterNameEl = document.getElementById('characterName');
const characterSubtitleEl = document.getElementById('characterSubtitle');
const characterCoverEl = document.getElementById('characterCover');
const characterCoverFallbackEl = document.getElementById('characterCoverFallback');
const sessionDockPanel = document.getElementById('sessionDockPanel');
const sessionDockList = document.getElementById('sessionDockList');
const saveModelConfigBtn = document.getElementById('saveModelConfigBtn');
const narratorModelSelect = document.getElementById('narratorModelSelect');
const stateKeeperModelSelect = document.getElementById('stateKeeperModelSelect');
const siteBaseUrlInput = document.getElementById('siteBaseUrlInput');
const siteApiTypeSelect = document.getElementById('siteApiTypeSelect');
const siteApiKeyInput = document.getElementById('siteApiKeyInput');
const saveSiteConfigBtn = document.getElementById('saveSiteConfigBtn');
const discoverSiteModelsBtn = document.getElementById('discoverSiteModelsBtn');
const siteStatusNote = document.getElementById('siteStatusNote');
const modelConfigNote = document.getElementById('modelConfigNote');

let lastDebug = null;
let lastCharacterCard = null;
let shouldStickToBottom = true;
let pendingUserMessage = null;
let lastHistoryItems = [];
let currentSessionId = '';
let sessionItems = [];
let webConfig = {
  default_debug: false,
  history_page_size: 80,
  show_state_panel: true,
  show_debug_panel: false,
};
let coverLoadToken = 0;
let lastCharacterCoverUrl = null;
let siteApiTypes = [];
let siteConfig = {
  base_url: '',
  api: 'openai-completions',
  api_key_configured: false,
  api_key_masked: '',
  api_key_reference: null,
  status: 'invalid',
  status_label: '未配置',
  models: [],
};
let modelConfig = {
  narrator: {
    model: '',
  },
  state_keeper: {
    model: '',
  },
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

function toggleSessionDock(forceOpen) {
  if (!sessionDockPanel) return;
  const nextOpen = typeof forceOpen === 'boolean' ? forceOpen : sessionDockPanel.hidden;
  sessionDockPanel.hidden = !nextOpen;
  sessionIndicator?.setAttribute('aria-expanded', String(nextOpen));
}

function updateSessionIndicator() {
  if (sessionIndicatorLabel) {
    sessionIndicatorLabel.textContent = currentSessionId || '未选择';
  }
}

function sessionId() {
  return currentSessionId.trim();
}

function topSessions(items) {
  return (items || [])
    .filter(item => !item.archived && !item.replay)
    .sort((a, b) => {
      const messageGap = (b.last_message_ts || 0) - (a.last_message_ts || 0);
      if (messageGap !== 0) return messageGap;
      return (b.updated_at_ns || 0) - (a.updated_at_ns || 0);
    })
    .slice(0, 5);
}

function setStatus(text, kind = 'info') {
  statusBar.textContent = text;
  statusBar.dataset.kind = kind;
}

function renderCharacterCard(card) {
  const incomingCard = (card && typeof card === 'object') ? card : null;
  if (incomingCard && (incomingCard.name || incomingCard.title || incomingCard.cover_url || incomingCard.subtitle || incomingCard.summary)) {
    lastCharacterCard = {
      ...lastCharacterCard,
      ...incomingCard,
    };
  }
  const effectiveCard = lastCharacterCard || incomingCard;
  const name = effectiveCard?.name || effectiveCard?.title || '未命名角色卡';
  const subtitle = effectiveCard?.subtitle || effectiveCard?.summary || '待加载';

  if (characterNameEl) characterNameEl.textContent = name;
  if (characterSubtitleEl) characterSubtitleEl.textContent = subtitle;

  const initials = (name || 'TL').trim().slice(0, 2);
  if (characterCoverFallbackEl) {
    characterCoverFallbackEl.textContent = initials;
  }

  if (characterCoverEl) {
    if (effectiveCard?.cover_url) {
      const nextCoverUrl = effectiveCard.cover_url;
      if (nextCoverUrl === lastCharacterCoverUrl && characterCoverEl.dataset.loaded === 'true') {
        characterCoverEl.hidden = false;
        if (characterCoverFallbackEl) characterCoverFallbackEl.hidden = true;
        return;
      }
      const token = ++coverLoadToken;
      lastCharacterCoverUrl = nextCoverUrl;
      if (!characterCoverEl.dataset.loaded) {
        characterCoverEl.hidden = true;
        if (characterCoverFallbackEl) characterCoverFallbackEl.hidden = false;
      }
      characterCoverEl.onload = () => {
        if (token !== coverLoadToken) return;
        characterCoverEl.dataset.loaded = 'true';
        characterCoverEl.hidden = false;
        if (characterCoverFallbackEl) characterCoverFallbackEl.hidden = true;
      };
      characterCoverEl.onerror = () => {
        if (token !== coverLoadToken) return;
        characterCoverEl.dataset.loaded = '';
        characterCoverEl.hidden = true;
        lastCharacterCoverUrl = null;
        if (characterCoverFallbackEl) characterCoverFallbackEl.hidden = false;
      };
      if (characterCoverEl.getAttribute('src') !== nextCoverUrl) {
        characterCoverEl.src = nextCoverUrl;
      }
    } else {
      characterCoverEl.dataset.loaded = '';
      characterCoverEl.hidden = true;
      lastCharacterCoverUrl = null;
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

function setSelectOptions(selectEl, items, selectedValue, formatter) {
  if (!selectEl) return;
  selectEl.innerHTML = '';
  for (const item of items) {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = formatter(item);
    if (option.value === selectedValue) {
      option.selected = true;
    }
    selectEl.appendChild(option);
  }
  if (!selectEl.value && selectEl.options.length > 0) {
    selectEl.selectedIndex = 0;
  }
}

function currentSiteModelChoices() {
  return (siteConfig.models || []).map(item => ({value: item.id, label: item.name || item.id}));
}

function renderSiteConfig() {
  siteBaseUrlInput.value = siteConfig.base_url || '';
  setSelectOptions(
    siteApiTypeSelect,
    siteApiTypes.map(item => ({value: item.value, label: item.label})),
    siteConfig.api,
    item => item.label,
  );
  siteApiKeyInput.value = '';
  if (siteStatusNote) {
    siteStatusNote.textContent = siteConfig.status_label || '未配置';
    siteStatusNote.dataset.kind = siteConfig.status === 'ready' ? 'ok' : (siteConfig.status === 'invalid' ? 'error' : '');
  }
}

function renderModelConfig() {
  const models = currentSiteModelChoices();
  setSelectOptions(narratorModelSelect, models, modelConfig.narrator?.model, item => item.label);
  setSelectOptions(stateKeeperModelSelect, models, modelConfig.state_keeper?.model, item => item.label);
  if (modelConfigNote && !modelConfigNote.dataset.kind) {
    modelConfigNote.textContent = '温度和最大输出长度已固定到默认配置，由管理员维护。';
  }
}

function validateSiteDraft(draft) {
  if (!draft.baseUrl) return '站点 URL 不能为空';
  if (!/^https?:\/\//.test(draft.baseUrl)) return '站点 URL 必须以 http:// 或 https:// 开头';
  if (!draft.api) return 'API 类型不能为空';
  return '';
}

function validateRuntimeDraft(draft) {
  const available = new Set((siteConfig.models || []).map(item => item.id));
  if (!draft.narrator.model) return 'Narrator 模型不能为空';
  if (!draft.state_keeper.model) return 'State Keeper 模型不能为空';
  if (available.size === 0) return '当前还没有模型列表，请先点击“获取模型”';
  if (!available.has(draft.narrator.model)) return 'Narrator 模型不在当前站点模型列表中';
  if (!available.has(draft.state_keeper.model)) return 'State Keeper 模型不在当前站点模型列表中';
  return '';
}

async function apiJson(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message || `request failed: ${url}`);
  }
  return data;
}

async function loadSessions() {
  const data = await apiJson('/api/sessions');
  applyWebConfig(data.web || {});
  renderCharacterCard(data.character_card || lastCharacterCard);
  sessionItems = data.sessions || [];
  const availableIds = new Set(sessionItems.map(item => item.session_id));
  const recommended = data.default_session_id || topSessions(sessionItems)[0]?.session_id || '';
  if (currentSessionId && !availableIds.has(currentSessionId)) {
    currentSessionId = '';
  }
  if (!currentSessionId && recommended) {
    currentSessionId = recommended;
  }
  updateSessionIndicator();
  renderSessionDock();
}

function renderSessionDock() {
  if (!sessionDockList) return;
  sessionDockList.innerHTML = '';
  const items = topSessions(sessionItems);

  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'session-dock-item';
    if (item.session_id === sessionId()) row.dataset.active = 'true';

    const openBtn = document.createElement('button');
    openBtn.type = 'button';
    openBtn.className = 'session-dock-open';
    openBtn.textContent = item.session_id;
    openBtn.addEventListener('click', async () => {
      currentSessionId = item.session_id;
      updateSessionIndicator();
      setStatus('切换会话中...', 'working');
      try {
        resetSidePanels();
        await loadHistory();
        await loadState();
        renderSessionDock();
        toggleSessionDock(false);
        setStatus('已切换', 'ok');
      } catch (err) {
        setStatus(`错误：${err.message}`, 'error');
      }
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'session-dock-delete';
    deleteBtn.setAttribute('aria-label', `删除 ${item.session_id}`);
    deleteBtn.innerHTML = '<span class="material-symbols-outlined">skull</span>';
    deleteBtn.addEventListener('click', async () => {
      setStatus('删除会话中...', 'working');
      try {
        await deleteSession(item.session_id);
        renderSessionDock();
        setStatus('会话已删除', 'ok');
      } catch (err) {
        setStatus(`错误：${err.message}`, 'error');
      }
    });

    row.appendChild(openBtn);
    row.appendChild(deleteBtn);
    sessionDockList.appendChild(row);
  }

  const newGameRow = document.createElement('div');
  newGameRow.className = 'session-dock-item session-dock-new';
  const newGameAction = document.createElement('button');
  newGameAction.type = 'button';
  newGameAction.className = 'session-dock-new-btn';
  newGameAction.textContent = '开始新游戏';
  newGameAction.addEventListener('click', async () => {
    setStatus('新游戏初始化中...', 'working');
    try {
      await startNewGame();
      renderSessionDock();
      toggleSessionDock(false);
      setStatus('新游戏已开始', 'ok');
    } catch (err) {
      setStatus(`错误：${err.message}`, 'error');
    }
  });
  newGameRow.appendChild(newGameAction);
  sessionDockList.appendChild(newGameRow);
}

async function loadSiteConfig() {
  const data = await apiJson('/api/site-config');
  siteConfig = {
    ...siteConfig,
    ...data,
  };
  siteApiTypes = data.supported_api_types || siteApiTypes;
  applyWebConfig(data.web || {});
  renderSiteConfig();
  renderModelConfig();
}

async function saveSiteConfig() {
  const draft = {
    baseUrl: siteBaseUrlInput.value.trim(),
    api: siteApiTypeSelect.value,
    replace_api_key: siteApiKeyInput.value.trim().length > 0,
    apiKey: siteApiKeyInput.value.trim(),
  };
  const validationError = validateSiteDraft(draft);
  if (validationError) {
    setStatus(`错误：${validationError}`, 'error');
    if (siteStatusNote) {
      siteStatusNote.textContent = validationError;
      siteStatusNote.dataset.kind = 'error';
    }
    return;
  }
  setStatus('保存站点中...', 'working');
  const data = await apiJson('/api/site-config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(draft),
  });
  siteConfig = {
    ...siteConfig,
    ...data,
  };
  renderSiteConfig();
  setStatus('站点已保存', 'ok');
}

async function discoverSiteModels() {
  setStatus('获取模型中...', 'working');
  const data = await apiJson('/api/site-models/discover', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({}),
  });
  siteConfig = {
    ...siteConfig,
    ...data,
  };
  renderSiteConfig();
  renderModelConfig();
  setStatus('模型列表已更新', 'ok');
}

async function loadModelConfig() {
  const data = await apiJson('/api/model-config');
  modelConfig = {
    ...modelConfig,
    ...data,
  };
  applyWebConfig(data.web || {});
  if (data.site) {
    siteConfig = {
      ...siteConfig,
      ...data.site,
    };
  }
  renderSiteConfig();
  renderModelConfig();
}

async function saveModelRuntimeConfig() {
  const draft = {
    narrator: {
      model: narratorModelSelect.value,
    },
    state_keeper: {
      model: stateKeeperModelSelect.value,
    },
  };
  const validationError = validateRuntimeDraft(draft);
  if (validationError) {
    if (modelConfigNote) {
      modelConfigNote.textContent = validationError;
      modelConfigNote.dataset.kind = 'error';
    }
    return;
  }
  if (modelConfigNote) {
    modelConfigNote.textContent = '保存模型配置中...';
    modelConfigNote.dataset.kind = '';
  }
  const data = await apiJson('/api/model-config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(draft),
  });
  modelConfig = {
    ...modelConfig,
    ...data,
  };
  if (data.site) {
    siteConfig = {
      ...siteConfig,
      ...data.site,
    };
  }
  renderSiteConfig();
  renderModelConfig();
  if (modelConfigNote) {
    modelConfigNote.textContent = '模型配置已保存';
    modelConfigNote.dataset.kind = 'ok';
  }
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
    const th = document.createElement('th');
    th.textContent = label;
    const td = document.createElement('td');
    td.textContent = value || '待确认';
    tr.appendChild(th);
    tr.appendChild(td);
    table.appendChild(tr);
  }
  stateEl.appendChild(table);
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
  const data = await apiJson('/api/regenerate-last', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sessionId()})
  });
  pendingUserMessage = null;
  await loadHistory();
  renderState(data.state_snapshot || {});
  renderDebug(data.debug || null);
  shouldStickToBottom = true;
  focusLatestAssistant({ smooth: false });
}

async function loadHistory() {
  if (!sessionId()) {
    pendingUserMessage = null;
    renderMessages([]);
    updateSessionIndicator();
    return;
  }
  const data = await apiJson(`/api/history?session_id=${encodeURIComponent(sessionId())}`);
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
  if (!sessionId()) {
    renderState({});
    updateSessionIndicator();
    return;
  }
  const data = await apiJson(`/api/state?session_id=${encodeURIComponent(sessionId())}`);
  applyWebConfig(data.web || {});
  renderCharacterCard(data.character_card || lastCharacterCard);
  updateSessionIndicator();
  renderState(data.state || {});
}

async function startNewGame() {
  const data = await apiJson('/api/new-game', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sessionId() || 'story-live'})
  });
  currentSessionId = data.session_id || sessionId();
  pendingUserMessage = null;
  renderMessages(data.messages || []);
  renderState(data.state_snapshot || {});
  await loadSessions();
  resetSidePanels();
  renderDebug({new_game: {session_id: data.session_id || sessionId(), archived_to: data.archived_to || null}});
  updateSessionIndicator();
  shouldStickToBottom = true;
  focusLatestAssistant({ smooth: false });
}

async function deleteSession(targetSessionId = sessionId()) {
  const current = targetSessionId;
  const activeBeforeDelete = sessionId();
  const data = await apiJson('/api/delete-session', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: current})
  });
  const next = (data.sessions || []).find(item => !item.archived && !item.replay)?.session_id || '';
  if (current === activeBeforeDelete) {
    currentSessionId = next;
  }
  await loadSessions();
  if (current === activeBeforeDelete) {
    if (next) {
      await loadHistory();
      await loadState();
    } else {
      renderMessages([]);
      renderState({});
    }
    resetSidePanels();
    renderDebug({session_deleted: {session_id: current, next_session: next, deleted_paths: data.deleted_paths || []}});
    updateSessionIndicator();
  }
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
  const originalText = input.value;
  const submitButton = composer.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  setStatus('发送中...', 'working');
  pendingUserMessage = text;
  input.value = '';
  renderMessages(lastHistoryItems);
  try {
    const data = await apiJson('/api/message', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session_id: sessionId(),
        text,
        client_turn_id: `web-${Date.now()}`,
        meta: {source: 'web', debug: webConfig.default_debug}
      })
    });
    pendingUserMessage = null;
    shouldStickToBottom = true;
    await loadHistory();
    renderState(data.state_snapshot || {});
    renderCharacterCard(data.character_card || lastCharacterCard);
    renderDebug(data.debug || null);
    updateSessionIndicator();
    if (shouldStickToBottom) {
      focusLatestAssistant({ smooth: false });
    }
    setStatus('已更新', 'ok');
  } catch (err) {
    pendingUserMessage = null;
    input.value = originalText;
    renderMessages(lastHistoryItems);
    setStatus(`错误：${err.message}`, 'error');
  } finally {
    submitButton.disabled = false;
  }
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    composer.requestSubmit();
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

sessionIndicator?.addEventListener('click', () => {
  toggleSessionDock();
});

document.addEventListener('click', (e) => {
  const target = e.target;
  if (!(target instanceof Node)) return;
  if (sessionDockPanel?.hidden) return;
  if (sessionDockPanel.contains(target) || sessionIndicator?.contains(target)) return;
  toggleSessionDock(false);
});

settingsCloseBtn?.addEventListener('click', closeSettings);
settingsBackdrop?.addEventListener('click', closeSettings);

saveSiteConfigBtn?.addEventListener('click', async () => {
  try {
    await saveSiteConfig();
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
    if (siteStatusNote) {
      siteStatusNote.textContent = err.message;
      siteStatusNote.dataset.kind = 'error';
    }
  }
});

discoverSiteModelsBtn?.addEventListener('click', async () => {
  try {
    await discoverSiteModels();
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
    if (siteStatusNote) {
      siteStatusNote.textContent = err.message;
      siteStatusNote.dataset.kind = 'error';
    }
  }
});

saveModelConfigBtn?.addEventListener('click', async () => {
  try {
    await saveModelRuntimeConfig();
  } catch (err) {
    if (modelConfigNote) {
      modelConfigNote.textContent = err.message;
      modelConfigNote.dataset.kind = 'error';
    }
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeSettings();
    toggleSessionDock(false);
  }
});

(async function init() {
  setStatus('初始化中...', 'working');
  try {
    resetSidePanels();
    await Promise.all([
      loadSessions(),
      loadSiteConfig(),
      loadModelConfig(),
    ]);
    await loadHistory();
    await loadState();
    closeSettings();
    toggleSessionDock(false);
    shouldStickToBottom = true;
    focusLatestAssistant({ smooth: false });
    setStatus('就绪', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
})();
