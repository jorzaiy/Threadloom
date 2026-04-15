const messagesEl = document.getElementById('messages');
const stateEl = document.getElementById('state');
const npcSectionEl = document.getElementById('npcSection');
const objectThreadSectionEl = document.getElementById('objectThreadSection');
const entityEl = document.getElementById('entityDetail');
const debugEl = document.getElementById('debugDetail');
const composer = document.getElementById('composer');
const input = document.getElementById('input');
const regenerateBtn = document.getElementById('regenerateBtn');
const statusBar = document.getElementById('statusBar');
const debugPanel = document.getElementById('debugPanel');
const stateColumn = document.getElementById('stateColumn');
const mobileStateToggle = document.getElementById('mobileStateToggle');
const settingsBtn = document.getElementById('settingsBtn');
const settingsPanel = document.getElementById('settingsPanel');
const settingsBackdrop = document.getElementById('settingsBackdrop');
const settingsCloseBtn = document.getElementById('settingsCloseBtn');
const sessionIndicator = document.getElementById('sessionIndicator');
const sessionIndicatorLabel = document.getElementById('sessionIndicatorLabel');
const characterScopeEl = document.getElementById('characterScope');
const characterSelectEl = document.getElementById('characterSelect');
const characterSubtitleEl = document.getElementById('characterSubtitle');
const characterCoverEl = document.getElementById('characterCover');
const characterCoverFallbackEl = document.getElementById('characterCoverFallback');
const sessionDockPanel = document.getElementById('sessionDockPanel');
const sessionDockList = document.getElementById('sessionDockList');
const historyToolbar = document.getElementById('historyToolbar');
const loadEarlierBtn = document.getElementById('loadEarlierBtn');
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
const characterImportFileInput = document.getElementById('characterImportFileInput');
const characterImportNameInput = document.getElementById('characterImportNameInput');
const importCharacterBtn = document.getElementById('importCharacterBtn');
const characterImportNote = document.getElementById('characterImportNote');

let lastDebug = null;
let lastCharacterCard = null;
let shouldStickToBottom = true;
let pendingUserMessage = null;
let lastHistoryItems = [];
let historyHasMore = false;
let historyNextBefore = null;
let historyTotalCount = 0;
let isLoadingEarlierHistory = false;
let currentSessionId = '';
let sessionItems = [];
let isWaitingForResponse = false;
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
let characterItems = [];

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
  if (statusBar._fadeTimer) clearTimeout(statusBar._fadeTimer);
  statusBar.classList.remove('status-bar-fading');
  if (kind === 'ok') {
    statusBar._fadeTimer = setTimeout(() => {
      statusBar.classList.add('status-bar-fading');
      statusBar._fadeTimer = setTimeout(() => {
        statusBar.textContent = '就绪';
        statusBar.dataset.kind = 'info';
        statusBar.classList.remove('status-bar-fading');
      }, 400);
    }, 3000);
  }
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
  const userId = effectiveCard?.user_id || 'default_user';

  if (characterSubtitleEl) characterSubtitleEl.textContent = subtitle;
  if (characterScopeEl) {
    characterScopeEl.textContent = `${userId} / ${name}`;
  }

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

function renderCharacterSelect() {
  if (!characterSelectEl) return;
  setSelectOptions(
    characterSelectEl,
    characterItems.map(item => ({value: item.character_id, label: item.name || item.character_id})),
    lastCharacterCard?.character_id || '',
    item => item.label,
  );
}

function resetSidePanels() {
  if (entityEl) {
    entityEl.textContent = '点击状态面板中的 NPC 名称查看详情';
  }
  if (npcSectionEl) npcSectionEl.innerHTML = '';
  if (objectThreadSectionEl) objectThreadSectionEl.innerHTML = '';
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

async function loadCharacters() {
  const data = await apiJson('/api/characters');
  applyWebConfig(data.web || {});
  characterItems = data.characters || [];
  renderCharacterCard(data.character_card || lastCharacterCard);
  renderCharacterSelect();
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
  newGameAction.textContent = `开始新游戏 (${lastCharacterCard?.user_id || 'default_user'} / ${lastCharacterCard?.name || '角色卡'})`;
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
    if (item.role === 'assistant') {
      body.innerHTML = renderMarkdown(item.content);
    } else {
      body.textContent = item.content;
    }
    article.appendChild(label);
    article.appendChild(body);
    messagesEl.appendChild(article);
  }

  if (isWaitingForResponse) {
    showTypingIndicator();
  }

  if (historyToolbar) {
    historyToolbar.hidden = !historyHasMore;
  }
  if (loadEarlierBtn) {
    loadEarlierBtn.disabled = isLoadingEarlierHistory;
    loadEarlierBtn.textContent = isLoadingEarlierHistory ? '加载中...' : '加载更早记录';
  }

  if (shouldStickToBottom) {
    scrollToLatest({ smooth: false });
  }
}

function renderMarkdown(text) {
  if (typeof marked !== 'undefined') {
    return marked.parse(text, { breaks: true, gfm: true });
  }
  return text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function showTypingIndicator() {
  const article = document.createElement('article');
  article.className = 'msg assistant msg-typing';
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'World';
  const body = document.createElement('div');
  body.className = 'msg-body typing-indicator';
  body.innerHTML = `
    <span class="typing-indicator-label">正在思考</span>
    <span class="typing-dots">
      <span></span>
      <span></span>
      <span></span>
    </span>
  `;
  article.appendChild(label);
  article.appendChild(body);
  messagesEl.appendChild(article);
  if (shouldStickToBottom) {
    scrollToLatest({ smooth: false });
  }
}

function hideTypingIndicator() {
  const typing = messagesEl.querySelector('.msg-typing');
  if (typing) {
    typing.remove();
  }
}

function scrollToLatest(options = {}) {
  const smooth = Boolean(options.smooth);
  let passes = 3;
  const run = () => {
    messagesEl.scrollTo({
      top: messagesEl.scrollHeight,
      behavior: smooth && passes === 3 ? 'smooth' : 'auto'
    });
    passes -= 1;
    if (passes > 0) {
      requestAnimationFrame(run);
    }
  };
  requestAnimationFrame(run);
}

function focusLatestAssistant(options = {}) {
  scrollToLatest(options);
}

function isNearBottom(threshold = 96) {
  const distance = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight;
  return distance <= threshold;
}

function renderState(state) {
  stateEl.innerHTML = '';
  if (npcSectionEl) npcSectionEl.innerHTML = '';
  if (objectThreadSectionEl) objectThreadSectionEl.innerHTML = '';

  // --- Context table (time / location / main event / goal) ---
  const rows = [
    ['时间', state.time],
    ['地点', state.location],
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

  const summaryWrap = document.createElement('div');
  summaryWrap.className = 'state-summary-block';

  const mainThread = (state.active_threads || []).find(item => item?.kind === 'main') || (state.active_threads || [])[0] || null;
  if (mainThread?.label) {
    const summaryLine = document.createElement('div');
    summaryLine.className = 'state-summary-line';
    summaryLine.innerHTML = `<strong>主要事件</strong><span>${mainThread.label}</span>`;
    summaryWrap.appendChild(summaryLine);
  } else if (state.main_event) {
    const summaryLine = document.createElement('div');
    summaryLine.className = 'state-summary-line';
    summaryLine.innerHTML = `<strong>主要事件</strong><span>${state.main_event}</span>`;
    summaryWrap.appendChild(summaryLine);
  }

  if (state.immediate_goal) {
    const goalLine = document.createElement('div');
    goalLine.className = 'state-summary-line';
    goalLine.innerHTML = `<strong>当前目标</strong><span>${state.immediate_goal}</span>`;
    summaryWrap.appendChild(goalLine);
  }

  if (summaryWrap.children.length) {
    stateEl.appendChild(summaryWrap);
  }

  // --- NPC section ---
  const npcTarget = npcSectionEl || stateEl;

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
      const emptyTd = document.createElement('td');
      emptyTd.colSpan = 2;
      emptyTd.textContent = '暂无';
      emptyTd.className = 'empty-hint';
      tr.appendChild(emptyTd);
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
          const btn = document.createElement('button');
          btn.className = 'npc-link';
          btn.textContent = label;
          btn.onclick = () => loadEntity(entityId);
          td.appendChild(btn);
        } else {
          const span = document.createElement('span');
          span.className = 'npc-fallback';
          span.textContent = ambiguous ? `${label}（存在多个同名实体）` : label;
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

  npcTarget.appendChild(buildNpcTable('在场 NPC', state.onstage_entities || []));
  npcTarget.appendChild(buildNpcTable('相关 NPC', state.relevant_entities || []));

  const importantNpcs = state.important_npcs || [];
  const importantNpcRows = importantNpcs.slice(0, 6).map(item => ({
    name: item?.primary_label || '待确认',
    entity_id: null,
    role_label: item?.role_label || '',
    ambiguous: false,
  }));
  npcTarget.appendChild(buildNpcTable('重要 NPC', importantNpcRows));

  // --- Objects & Threads section ---
  const otTarget = objectThreadSectionEl || stateEl;

  const objects = state.tracked_objects || [];
  const possession = state.possession_state || [];
  const visibility = state.object_visibility || [];
  const possessionById = Object.fromEntries((possession || []).map(item => [item.object_id, item]));
  const visibilityById = Object.fromEntries((visibility || []).map(item => [item.object_id, item]));

  const objectWrap = document.createElement('div');
  objectWrap.className = 'npc-block';
  const objectHeading = document.createElement('strong');
  objectHeading.textContent = '关键物件';
  objectWrap.appendChild(objectHeading);

  const objectTable = document.createElement('table');
  objectTable.className = 'state-table npc-table';
  const objectBody = document.createElement('tbody');
  if (!objects.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 2;
    td.textContent = '暂无';
    td.className = 'empty-hint';
    tr.appendChild(td);
    objectBody.appendChild(tr);
  } else {
    objects.slice(0, 6).forEach((item, idx) => {
      const tr = document.createElement('tr');
      const th = document.createElement('th');
      th.textContent = `${idx + 1}`;
      const td = document.createElement('td');
      const holder = possessionById[item.object_id]?.holder || '未指明';
      const status = possessionById[item.object_id]?.status || '未指明';
      const vis = visibilityById[item.object_id]?.visibility || '未指明';
      const kind = item?.kind || 'item';
      const lines = [
        `${item.label || item.object_id} / ${kind}`,
        `持有：${holder}`,
        `状态：${status}`,
        `可见：${vis}`,
      ];
      lines.forEach(line => {
        const div = document.createElement('div');
        div.className = 'object-line';
        div.textContent = line;
        td.appendChild(div);
      });
      tr.appendChild(th);
      tr.appendChild(td);
      objectBody.appendChild(tr);
    });
  }
  objectTable.appendChild(objectBody);
  objectWrap.appendChild(objectTable);
  otTarget.appendChild(objectWrap);

  const threads = state.active_threads || [];
  const threadWrap = document.createElement('div');
  threadWrap.className = 'npc-block';
  const threadHeading = document.createElement('strong');
  threadHeading.textContent = '活跃线程';
  threadWrap.appendChild(threadHeading);

  const threadTable = document.createElement('table');
  threadTable.className = 'state-table npc-table';
  const threadBody = document.createElement('tbody');
  if (!threads.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 2;
    td.textContent = '暂无';
    td.className = 'empty-hint';
    tr.appendChild(td);
    threadBody.appendChild(tr);
  } else {
    threads.slice(0, 5).forEach((item, idx) => {
      const tr = document.createElement('tr');
      const th = document.createElement('th');
      th.textContent = `${idx + 1}`;
      const td = document.createElement('td');
      const parts = [
        item.label || '待确认',
        item.kind || 'thread',
        item.status || 'active',
      ].filter(Boolean);
      td.textContent = parts.join(' / ');
      tr.appendChild(th);
      tr.appendChild(td);
      threadBody.appendChild(tr);
    });
  }
  threadTable.appendChild(threadBody);
  threadWrap.appendChild(threadTable);
  otTarget.appendChild(threadWrap);
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
  const lorebookInjection = debug.lorebook_injection || {};
  const promptBlocks = debug.prompt_block_stats || [];
  const lines = [];
  if (promptBlocks.length) {
    lines.push('Prompt Blocks');
    for (const item of promptBlocks) {
      lines.push(`- ${item.label}: ${item.chars}`);
    }
    lines.push('');
  }
  if (lorebookInjection.items?.length) {
    lines.push(`System NPC Candidates: ${debug.system_npc_candidate_count || 0}`);
    lines.push(`Lorebook NPC Candidates: ${debug.lorebook_npc_candidate_count || 0}`);
    lines.push(`Lorebook Injected Chars: ${lorebookInjection.total_chars || 0}`);
    lines.push('Lorebook Injection');
    for (const item of lorebookInjection.items) {
      lines.push(`- ${item.title} | ${item.entryType}/${item.runtimeScope} | priority=${item.priority} | chars=${item.injected_chars}`);
    }
    lines.push('');
  }
  lines.push('Diagnostics');
  lines.push(JSON.stringify({
    arbiter_analysis: debug.arbiter_analysis || null,
    arbiter_results: debug.arbiter_results || [],
    state_keeper_diagnostics: debug.state_keeper_diagnostics || null,
    retained_threads: debug.retained_threads || [],
    retained_entities: debug.retained_entities || [],
    completion_status: debug.completion_status || null,
    finish_reason: debug.finish_reason || null,
    state_error: debug.state_error || null,
    model_error: debug.model_error || null,
  }, null, 2));
  debugEl.textContent = lines.join('\n');
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
    historyHasMore = false;
    historyNextBefore = null;
    historyTotalCount = 0;
    renderMessages([]);
    updateSessionIndicator();
    return;
  }
  const data = await apiJson(`/api/history?session_id=${encodeURIComponent(sessionId())}`);
  applyWebConfig(data.web || {});
  const wasNearBottom = isNearBottom();
  pendingUserMessage = null;
  historyHasMore = Boolean(data.has_more);
  historyNextBefore = data.next_before;
  historyTotalCount = Number(data.total_count || 0);
  renderCharacterCard(data.character_card || lastCharacterCard);
  updateSessionIndicator();
  renderMessages(data.messages || []);
  if (wasNearBottom) {
    shouldStickToBottom = true;
  }
}

async function loadEarlierHistory() {
  if (!sessionId() || !historyHasMore || historyNextBefore == null || isLoadingEarlierHistory) {
    return;
  }
  isLoadingEarlierHistory = true;
  shouldStickToBottom = false;
  renderMessages(lastHistoryItems);
  const previousHeight = messagesEl.scrollHeight;
  try {
    const data = await apiJson(`/api/history?session_id=${encodeURIComponent(sessionId())}&before=${encodeURIComponent(historyNextBefore)}`);
    applyWebConfig(data.web || {});
    historyHasMore = Boolean(data.has_more);
    historyNextBefore = data.next_before;
    historyTotalCount = Number(data.total_count || 0);
    lastHistoryItems = [...(data.messages || []), ...lastHistoryItems];
    renderMessages(lastHistoryItems);
    requestAnimationFrame(() => {
      const nextHeight = messagesEl.scrollHeight;
      messagesEl.scrollTop = Math.max(0, nextHeight - previousHeight);
    });
  } finally {
    isLoadingEarlierHistory = false;
    if (historyToolbar) {
      historyToolbar.hidden = !historyHasMore;
    }
    if (loadEarlierBtn) {
      loadEarlierBtn.disabled = false;
      loadEarlierBtn.textContent = '加载更早记录';
    }
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

async function selectCharacter(characterId) {
  const data = await apiJson('/api/character/select', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({character_id: characterId}),
  });
  characterItems = data.characters || [];
  currentSessionId = '';
  renderCharacterCard(data.character_card || lastCharacterCard);
  renderCharacterSelect();
  await loadSessions();
  resetSidePanels();
  if (currentSessionId) {
    await loadHistory();
    await loadState();
  } else {
    renderMessages([]);
    renderState({});
  }
}

async function importCharacterCard() {
  const file = characterImportFileInput?.files?.[0];
  if (!file) {
    throw new Error('请选择要导入的角色卡文件');
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  const data = await apiJson('/api/characters/import', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      filename: file.name,
      file_base64: btoa(binary),
      target_name: characterImportNameInput?.value?.trim() || '',
    }),
  });
  characterItems = data.characters || [];
  currentSessionId = '';
  renderCharacterCard(data.character_card || lastCharacterCard);
  renderCharacterSelect();
  if (characterImportFileInput) characterImportFileInput.value = '';
  if (characterImportNameInput) characterImportNameInput.value = '';
  await loadSessions();
  resetSidePanels();
  if (currentSessionId) {
    await loadHistory();
    await loadState();
  } else {
    renderMessages([]);
    renderState({});
  }
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
  isWaitingForResponse = true;
  input.value = '';
  shouldStickToBottom = true;
  renderMessages(lastHistoryItems);
  scrollToLatest({ smooth: false });
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
    isWaitingForResponse = false;
    hideTypingIndicator();
    shouldStickToBottom = true;
    await loadHistory();
    renderState(data.state_snapshot || {});
    renderCharacterCard(data.character_card || lastCharacterCard);
    renderDebug(data.debug || null);
    updateSessionIndicator();
    if (shouldStickToBottom) {
      scrollToLatest({ smooth: false });
    }
    setStatus('已更新', 'ok');
  } catch (err) {
    pendingUserMessage = null;
    isWaitingForResponse = false;
    hideTypingIndicator();
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

function openMobileSidebar() {
  if (!stateColumn) return;
  stateColumn.dataset.mobileOpen = 'true';
  let backdrop = document.querySelector('.mobile-state-backdrop');
  if (!backdrop) {
    backdrop = document.createElement('div');
    backdrop.className = 'mobile-state-backdrop';
    backdrop.addEventListener('click', closeMobileSidebar);
    document.body.appendChild(backdrop);
  } else {
    backdrop.hidden = false;
  }
}

function closeMobileSidebar() {
  if (!stateColumn) return;
  stateColumn.dataset.mobileOpen = 'false';
  const backdrop = document.querySelector('.mobile-state-backdrop');
  if (backdrop) backdrop.hidden = true;
}

mobileStateToggle?.addEventListener('click', () => {
  if (stateColumn?.dataset.mobileOpen === 'true') {
    closeMobileSidebar();
  } else {
    openMobileSidebar();
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

loadEarlierBtn?.addEventListener('click', async () => {
  try {
    await loadEarlierHistory();
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeSettings();
    closeMobileSidebar();
    toggleSessionDock(false);
  }
});

characterSelectEl?.addEventListener('change', async (e) => {
  try {
    setStatus('切换角色卡中...', 'working');
    await selectCharacter(e.target.value);
    setStatus('角色卡已切换', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

importCharacterBtn?.addEventListener('click', async () => {
  try {
    if (characterImportNote) {
      characterImportNote.textContent = '导入中...';
      characterImportNote.dataset.kind = '';
    }
    await importCharacterCard();
    if (characterImportNote) {
      characterImportNote.textContent = '角色卡已导入并切换';
      characterImportNote.dataset.kind = 'ok';
    }
    setStatus('角色卡已导入', 'ok');
  } catch (err) {
    if (characterImportNote) {
      characterImportNote.textContent = err.message;
      characterImportNote.dataset.kind = 'error';
    }
    setStatus(`错误：${err.message}`, 'error');
  }
});

(async function init() {
  setStatus('初始化中...', 'working');
  try {
    resetSidePanels();
    await Promise.all([
      loadSessions(),
      loadCharacters(),
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
