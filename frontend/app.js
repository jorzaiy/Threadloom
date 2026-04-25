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
const topbarContext = document.getElementById('topbarContext');
const brandSettingsTrigger = document.getElementById('brandSettingsTrigger');
const debugFloatPanel = document.getElementById('debugFloatPanel');
const debugBackdrop = document.getElementById('debugBackdrop');
const sessionBackdrop = document.getElementById('sessionBackdrop');
const debugCloseBtn = document.getElementById('debugCloseBtn');
const debugToggleBtn = document.getElementById('debugToggleBtn');
const settingsBtn = document.getElementById('settingsBtn');
const settingsPanel = document.getElementById('settingsPanel');
const settingsBackdrop = document.getElementById('settingsBackdrop');
const settingsCloseBtn = document.getElementById('settingsCloseBtn');
const sessionIndicator = document.getElementById('sessionIndicator');
const sessionIndicatorLabel = document.getElementById('sessionIndicatorLabel');
const characterScopeEl = document.getElementById('characterScope');
const characterSelectEl = document.getElementById('characterSelect');
const settingsCharacterSelectEl = document.getElementById('settingsCharacterSelect');
const characterSubtitleEl = document.getElementById('characterSubtitle');
const characterCoverEl = document.getElementById('characterCover');
const characterCoverFallbackEl = document.getElementById('characterCoverFallback');
const sessionDockPanel = document.getElementById('sessionDockPanel');
const sessionDockList = document.getElementById('sessionDockList');
const sessionDockCloseBtn = document.getElementById('sessionDockCloseBtn');
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
const userAvatarFileInput = document.getElementById('userAvatarFileInput');
const editBaseUserProfileBtn = document.getElementById('editBaseUserProfileBtn');
const editCharacterProfileOverrideBtn = document.getElementById('editCharacterProfileOverrideBtn');
const uploadUserAvatarBtn = document.getElementById('uploadUserAvatarBtn');
const deleteUserAvatarBtn = document.getElementById('deleteUserAvatarBtn');
const userProfileNote = document.getElementById('userProfileNote');
const charWizardStep1 = document.getElementById('charWizardStep1');
const charWizardStep2 = document.getElementById('charWizardStep2');
const charWizardStep3 = document.getElementById('charWizardStep3');
const charWizardStartBtn = document.getElementById('charWizardStartBtn');
const charWizardCancelBtn = document.getElementById('charWizardCancelBtn');
const characterImportFileInput = document.getElementById('characterImportFileInput');
const characterImportNameInput = document.getElementById('characterImportNameInput');
const importCharacterBtn = document.getElementById('importCharacterBtn');
const characterImportNote = document.getElementById('characterImportNote');
const characterManageNote = document.getElementById('characterManageNote');
const characterManageGrid = document.getElementById('characterManageGrid');
const characterProfileDraftPanel = document.getElementById('characterProfileDraftPanel');
const characterProfileDraftInput = document.getElementById('characterProfileDraftInput');
const saveCharacterProfileDraftBtn = document.getElementById('saveCharacterProfileDraftBtn');
const skipCharacterProfileDraftBtn = document.getElementById('skipCharacterProfileDraftBtn');
const characterProfileDraftNote = document.getElementById('characterProfileDraftNote');
const settingsSessionList = document.getElementById('settingsSessionList');
const settingsSessionNote = document.getElementById('settingsSessionNote');
const chatWizardStep1 = document.getElementById('chatWizardStep1');
const chatWizardStep2 = document.getElementById('chatWizardStep2');
const chatWizardStep3 = document.getElementById('chatWizardStep3');
const chatWizardStartBtn = document.getElementById('chatWizardStartBtn');
const chatWizardCancelBtn = document.getElementById('chatWizardCancelBtn');
const chatWizardBackBtn = document.getElementById('chatWizardBackBtn');
const chatImportFileInput = document.getElementById('chatImportFileInput');
const chatImportPreviewBtn = document.getElementById('chatImportPreviewBtn');
const chatImportBtn = document.getElementById('chatImportBtn');
const chatImportPreview = document.getElementById('chatImportPreview');
const chatImportNote = document.getElementById('chatImportNote');
const profileEditorBackdrop = document.getElementById('profileEditorBackdrop');
const profileEditorPanel = document.getElementById('profileEditorPanel');
const profileEditorTitle = document.getElementById('profileEditorTitle');
const profileEditorLabel = document.getElementById('profileEditorLabel');
const profileEditorInput = document.getElementById('profileEditorInput');
const profileEditorSaveBtn = document.getElementById('profileEditorSaveBtn');
const profileEditorCancelBtn = document.getElementById('profileEditorCancelBtn');
const profileEditorCloseBtn = document.getElementById('profileEditorCloseBtn');
const profileEditorNote = document.getElementById('profileEditorNote');

let lastDebug = null;
let lastCharacterCard = null;
let shouldStickToBottom = true;
let pendingUserMessage = null;
let lastHistoryItems = [];
let historyHasMore = false;
let historyNextBefore = null;
let historyTotalCount = 0;
let isLoadingEarlierHistory = false;
let historyRevealAllowed = false;
let inlineHistoryVisible = false;
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
let currentUserId = 'default-user';
let userProfile = {};
let userAvatarUrl = null;
let currentCharacterProfileOverride = {};
let profileEditorMode = '';

function hideCharacterProfileDraft() {
  if (charWizardStep3) charWizardStep3.hidden = true;
  if (charWizardStep2) charWizardStep2.hidden = true;
  if (charWizardStep1) charWizardStep1.hidden = false;
  if (characterProfileDraftPanel) characterProfileDraftPanel.hidden = false;
  if (characterProfileDraftInput) characterProfileDraftInput.value = '';
  if (characterProfileDraftNote) {
    characterProfileDraftNote.textContent = '';
    characterProfileDraftNote.dataset.kind = '';
  }
}

function showCharacterProfileDraft(draft) {
  if (!characterProfileDraftPanel || !characterProfileDraftInput) return;
  if (charWizardStep1) charWizardStep1.hidden = true;
  if (charWizardStep2) charWizardStep2.hidden = true;
  if (charWizardStep3) charWizardStep3.hidden = false;
  characterProfileDraftInput.value = JSON.stringify(draft || {}, null, 2);
  characterProfileDraftPanel.hidden = false;
  if (characterProfileDraftNote) {
    characterProfileDraftNote.textContent = '可直接保存，也可以按当前角色卡世界观略作修改后再保存。';
    characterProfileDraftNote.dataset.kind = 'info';
  }
}

async function saveCharacterProfileDraft() {
  const sourceInput = profileEditorMode === 'override' ? profileEditorInput : characterProfileDraftInput;
  if (!sourceInput) return;
  let override;
  try {
    override = JSON.parse(sourceInput.value || '{}');
  } catch (err) {
    const targetNote = profileEditorMode === 'override' ? profileEditorNote : characterProfileDraftNote;
    if (targetNote) {
      targetNote.textContent = `JSON 解析失败：${err.message}`;
      targetNote.dataset.kind = 'error';
    }
    return;
  }
  const data = await apiJson('/api/characters/profile-override', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({override}),
  });
  renderCharacterCard(data.character_card || lastCharacterCard);
  if (characterProfileDraftNote) {
    characterProfileDraftNote.textContent = '角色卡主角设定已保存并应用。';
    characterProfileDraftNote.dataset.kind = 'ok';
  }
}

function applyWebConfig(nextConfig = {}) {
  webConfig = {
    ...webConfig,
    ...nextConfig,
  };
}

function openSettings(tab) {
  if (!settingsPanel || !settingsBackdrop) return;
  settingsPanel.dataset.open = 'true';
  settingsPanel.setAttribute('aria-hidden', 'false');
  settingsBackdrop.hidden = false;
  settingsBtn?.setAttribute('aria-expanded', 'true');
  if (tab) switchSettingsTab(tab);
}

function closeSettings() {
  if (!settingsPanel || !settingsBackdrop) return;
  settingsPanel.dataset.open = 'false';
  settingsPanel.setAttribute('aria-hidden', 'true');
  settingsBackdrop.hidden = true;
  settingsBtn?.setAttribute('aria-expanded', 'false');
}

function switchSettingsTab(tabName) {
  const tabBtns = document.querySelectorAll('.settings-tabs .settings-tab-btn');
  const tabPanels = document.querySelectorAll('.settings-tab-panel');
  tabBtns.forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === tabName)));
  tabPanels.forEach(p => p.dataset.active = String(p.dataset.tabPanel === tabName));
}

function toggleSessionDock(forceOpen) {
  if (!sessionDockPanel) return;
  const isOpen = !sessionDockPanel.hidden;
  const nextOpen = typeof forceOpen === 'boolean' ? forceOpen : !isOpen;
  sessionDockPanel.hidden = !nextOpen;
  if (sessionBackdrop) sessionBackdrop.hidden = !nextOpen;
  sessionIndicator?.setAttribute('aria-expanded', String(nextOpen));
  sessionDockPanel.setAttribute('aria-hidden', String(!nextOpen));
}

function updateSessionIndicator() {
  if (sessionIndicatorLabel) {
    sessionIndicatorLabel.textContent = currentSessionId || '未选择';
  }
}

function renderTopbarContext() {
  if (!topbarContext) return;
  topbarContext.textContent = `${currentUserDisplayName()} · ${currentCharacterDisplayName()}`;
}

function updateHistoryToolbarVisibility() {
  const nearTop = messagesEl ? messagesEl.scrollTop <= 24 : false;
  if (historyToolbar) {
    historyToolbar.hidden = !(historyHasMore && historyRevealAllowed && nearTop && !shouldStickToBottom);
  }
}

function shouldShowInlineLoadEarlier() {
  return Boolean(historyHasMore && historyRevealAllowed && messagesEl && messagesEl.scrollTop <= 24 && !shouldStickToBottom);
}

function sessionId() {
  return currentSessionId.trim();
}

function topSessions(items, { activeLimit = 5 } = {}) {
  const active = (items || [])
    .filter(item => !item.replay)
    .sort((a, b) => {
      const messageGap = (b.last_message_ts || 0) - (a.last_message_ts || 0);
      if (messageGap !== 0) return messageGap;
      return (b.updated_at_ns || 0) - (a.updated_at_ns || 0);
    })
    .slice(0, activeLimit);
  return { active };
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
  renderTopbarContext();
}

function renderCharacterSelect() {
  const items = characterItems.map(item => ({value: item.character_id, label: item.name || item.character_id}));
  const selected = lastCharacterCard?.character_id || '';
  if (characterSelectEl) {
    setSelectOptions(characterSelectEl, items, selected, item => item.label);
  }
  if (settingsCharacterSelectEl) {
    setSelectOptions(settingsCharacterSelectEl, items, selected, item => item.label);
  }
  renderCharacterManageGrid();
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
  if (options.body && !options.headers?.['Content-Type']) {
    options.headers = { ...options.headers, 'Content-Type': 'application/json' };
  }
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

function renderSessionLists() {
  renderSessionList(sessionDockList, { closeDockOnSelect: true, noteEl: null, activeLimit: 5 });
  renderSessionList(settingsSessionList, { closeDockOnSelect: false, noteEl: settingsSessionNote, activeLimit: 20 });
}

function renderSessionDock() {
  renderSessionLists();
}

function renderSessionList(target, { closeDockOnSelect = false, noteEl = null, activeLimit = 5 } = {}) {
  if (!target) return;
  target.innerHTML = '';
  const { active } = topSessions(sessionItems, { activeLimit });

  function createSessionRow(item) {
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
        renderSessionLists();
        if (closeDockOnSelect) toggleSessionDock(false);
        if (noteEl) {
          noteEl.textContent = `已切换到：${item.session_id}`;
          noteEl.dataset.kind = 'ok';
        }
        setStatus('已切换', 'ok');
      } catch (err) {
        setStatus(`错误：${err.message}`, 'error');
        if (noteEl) {
          noteEl.textContent = err.message;
          noteEl.dataset.kind = 'error';
        }
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
        renderSessionLists();
        if (noteEl) {
          noteEl.textContent = `已删除：${item.session_id}`;
          noteEl.dataset.kind = 'ok';
        }
        setStatus('会话已删除', 'ok');
      } catch (err) {
        setStatus(`错误：${err.message}`, 'error');
        if (noteEl) {
          noteEl.textContent = err.message;
          noteEl.dataset.kind = 'error';
        }
      }
    });

    row.appendChild(openBtn);
    row.appendChild(deleteBtn);
    return row;
  }

  for (const item of active) {
    target.appendChild(createSessionRow(item));
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
      renderSessionLists();
      if (closeDockOnSelect) toggleSessionDock(false);
      if (noteEl) {
        noteEl.textContent = '新游戏已开始';
        noteEl.dataset.kind = 'ok';
      }
      setStatus('新游戏已开始', 'ok');
    } catch (err) {
      setStatus(`错误：${err.message}`, 'error');
      if (noteEl) {
        noteEl.textContent = err.message;
        noteEl.dataset.kind = 'error';
      }
    }
  });
  newGameRow.appendChild(newGameAction);
  target.appendChild(newGameRow);
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
  // 关闭首次设置引导
  const guide = document.getElementById('llmSetupGuide');
  if (guide) guide.hidden = true;
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

function currentUserDisplayName() {
  const name = String(userProfile?.name || userProfile?.courtesyName || '').trim();
  return name || 'user';
}

function currentCharacterDisplayName() {
  return String(lastCharacterCard?.name || lastCharacterCard?.title || '').trim() || 'world';
}

function renderUserProfileEditor() {
}

function openProfileEditor(mode, title, label, payload) {
  profileEditorMode = mode;
  if (profileEditorTitle) profileEditorTitle.textContent = title;
  if (profileEditorLabel) profileEditorLabel.textContent = label;
  if (profileEditorInput) profileEditorInput.value = JSON.stringify(payload || {}, null, 2);
  if (profileEditorNote) {
    profileEditorNote.textContent = '';
    profileEditorNote.dataset.kind = '';
  }
  if (profileEditorBackdrop) profileEditorBackdrop.hidden = false;
  if (profileEditorPanel) {
    profileEditorPanel.dataset.open = 'true';
    profileEditorPanel.setAttribute('aria-hidden', 'false');
  }
}

function closeProfileEditor() {
  profileEditorMode = '';
  if (profileEditorBackdrop) profileEditorBackdrop.hidden = true;
  if (profileEditorPanel) {
    profileEditorPanel.dataset.open = 'false';
    profileEditorPanel.setAttribute('aria-hidden', 'true');
  }
}

function renderCharacterManageGrid() {
  if (!characterManageGrid) return;
  characterManageGrid.innerHTML = '';
  for (const item of characterItems) {
    const card = document.createElement('section');
    card.className = 'character-manage-card';
    if (item.active) card.dataset.active = 'true';

    const coverWrap = document.createElement('div');
    coverWrap.className = 'character-manage-cover-wrap';
    if (item.cover_url) {
      const img = document.createElement('img');
      img.className = 'character-manage-cover';
      img.src = item.cover_url;
      img.loading = 'lazy';
      img.alt = item.name || item.character_id;
      img.addEventListener('error', () => {
        coverWrap.innerHTML = '';
        const fallback = document.createElement('div');
        fallback.className = 'character-manage-cover-fallback';
        fallback.textContent = (item.name || item.character_id || 'TL').trim().slice(0, 2);
        coverWrap.appendChild(fallback);
      });
      coverWrap.appendChild(img);
    } else {
      const fallback = document.createElement('div');
      fallback.className = 'character-manage-cover-fallback';
      fallback.textContent = (item.name || item.character_id || 'TL').trim().slice(0, 2);
      coverWrap.appendChild(fallback);
    }

    const body = document.createElement('div');
    body.className = 'character-manage-copy';
    const title = document.createElement('strong');
    title.textContent = item.name || item.character_id;
    const scope = document.createElement('p');
    scope.className = 'character-manage-scope';
    scope.textContent = item.character_id;
    const summary = document.createElement('p');
    summary.className = 'character-manage-summary';
    const rawSummary = String(item.summary || item.subtitle || '暂无简介').replace(/\s+/g, ' ').trim();
    summary.textContent = rawSummary.length > 64 ? `${rawSummary.slice(0, 64)}...` : rawSummary;
    body.appendChild(title);
    if (String(item.character_id || '').trim() !== String(item.name || '').trim()) {
      body.appendChild(scope);
    }
    body.appendChild(summary);

    const actions = document.createElement('div');
    actions.className = 'character-manage-actions';
    if (item.active) {
      const activeTag = document.createElement('span');
      activeTag.className = 'character-manage-active';
      activeTag.textContent = '当前激活';
      actions.appendChild(activeTag);
    } else {
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'subtle-danger';
      deleteBtn.textContent = '删除';
      deleteBtn.addEventListener('click', async () => {
        if (!window.confirm(`确定要删除角色卡“${item.name || item.character_id}”吗？此操作会删除该角色卡目录及其会话。`)) return;
        try {
          const data = await apiJson('/api/character/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({character_id: item.character_id}),
          });
          characterItems = data.characters || [];
          renderCharacterCard(data.character_card || null);
          renderCharacterSelect();
          renderCharacterManageGrid();
          if (characterManageNote) {
            characterManageNote.textContent = `已删除角色卡：${data.deleted_character_id}`;
            characterManageNote.dataset.kind = 'ok';
          }
        } catch (err) {
          if (characterManageNote) {
            characterManageNote.textContent = err.message;
            characterManageNote.dataset.kind = 'error';
          }
        }
      });
      actions.appendChild(deleteBtn);

      card.addEventListener('click', async (event) => {
        if (event.target instanceof HTMLElement && event.target.closest('button')) return;
        if (!window.confirm(`切换到角色卡“${item.name || item.character_id}”吗？`)) return;
        try {
          if (characterManageNote) {
            characterManageNote.textContent = `正在切换到：${item.name || item.character_id}`;
            characterManageNote.dataset.kind = '';
          }
          setStatus('切换角色卡中...', 'working');
          await selectCharacter(item.character_id);
          closeSettings();
          if (characterManageNote) {
            characterManageNote.textContent = `已切换到：${item.name || item.character_id}`;
            characterManageNote.dataset.kind = 'ok';
          }
          setStatus('角色卡已切换', 'ok');
        } catch (err) {
          setStatus(`切换失败：${err.message}`, 'error');
          if (characterManageNote) {
            characterManageNote.textContent = `切换失败：${err.message}`;
            characterManageNote.dataset.kind = 'error';
          }
        }
      });
    }

    card.appendChild(coverWrap);
    card.appendChild(body);
    card.appendChild(actions);
    characterManageGrid.appendChild(card);
  }
}

async function loadUserProfile() {
  const data = await apiJson('/api/user-profile');
  userProfile = data.profile || {};
  userAvatarUrl = data.avatar_url || null;
  renderUserProfileEditor();
  renderTopbarContext();
}

async function loadCharacterProfileOverride() {
  const data = await apiJson('/api/character/profile-override');
  currentCharacterProfileOverride = data.override || {};
}

async function saveUserProfile() {
  let profile;
  try {
    profile = JSON.parse(profileEditorInput?.value || '{}');
  } catch (err) {
    throw new Error(`用户设定 JSON 解析失败：${err.message}`);
  }
  const data = await apiJson('/api/user-profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({profile}),
  });
  userProfile = data.profile || {};
  userAvatarUrl = data.avatar_url || userAvatarUrl;
}

async function uploadUserAvatar() {
  const file = userAvatarFileInput?.files?.[0];
  if (!file) throw new Error('请选择头像文件');
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const data = await apiJson('/api/user-avatar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      filename: file.name,
      file_base64: btoa(binary),
    }),
  });
  userAvatarUrl = data.avatar_url ? `${data.avatar_url}?t=${Date.now()}` : null;
}

async function deleteUserAvatar() {
  const data = await apiJson('/api/user-avatar/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({}),
  });
  userAvatarUrl = data.avatar_url || null;
}

function renderMessages(items) {
  lastHistoryItems = items;
  messagesEl.innerHTML = '';
  const shouldShowLoadEarlierInline = shouldShowInlineLoadEarlier();
  inlineHistoryVisible = shouldShowLoadEarlierInline;

  if (shouldShowLoadEarlierInline && loadEarlierBtn) {
    const wrap = document.createElement('div');
    wrap.className = 'history-inline-wrap';
    const inlineBtn = loadEarlierBtn.cloneNode(true);
    inlineBtn.disabled = isLoadingEarlierHistory;
    inlineBtn.textContent = isLoadingEarlierHistory ? '加载中...' : '加载更早记录';
    inlineBtn.addEventListener('click', async () => {
      try {
        await loadEarlierHistory();
      } catch (err) {
        setStatus(`错误：${err.message}`, 'error');
      }
    });
    wrap.appendChild(inlineBtn);
    messagesEl.appendChild(wrap);
  }

  const allItems = [...items];
  if (pendingUserMessage) {
    allItems.push({role: 'user', content: pendingUserMessage, pending: true});
  }
  if (!allItems.length) {
    const empty = document.createElement('section');
    empty.className = 'empty-session-card';
    const title = document.createElement('h2');
    title.textContent = `${currentUserDisplayName()} · ${currentCharacterDisplayName()}`;
    const note = document.createElement('p');
    note.textContent = '当前角色卡下还没有可继续的会话。你可以直接开始新对话，或先导入已有聊天记录。';
    const actions = document.createElement('div');
    actions.className = 'empty-session-actions';
    const newBtn = document.createElement('button');
    newBtn.type = 'button';
    newBtn.textContent = '开始新对话';
    newBtn.addEventListener('click', async () => {
      try {
        await startNewGame();
        setStatus('已开始新对话', 'ok');
      } catch (err) {
        setStatus(`错误：${err.message}`, 'error');
      }
    });
    const importBtn = document.createElement('button');
    importBtn.type = 'button';
    importBtn.className = 'subtle-btn';
    importBtn.textContent = '导入聊天记录';
    importBtn.addEventListener('click', () => openSettings('world'));
    actions.appendChild(newBtn);
    actions.appendChild(importBtn);
    empty.appendChild(title);
    empty.appendChild(note);
    empty.appendChild(actions);
    messagesEl.appendChild(empty);
    return;
  }
  for (const item of allItems) {
    const article = document.createElement('article');
    article.className = `msg ${item.role}`;
    if (item.pending) article.classList.add('pending');
    const head = document.createElement('div');
    head.className = 'msg-head';
    const avatar = document.createElement(item.role === 'assistant' && lastCharacterCard?.cover_url ? 'img' : 'div');
    avatar.className = `msg-avatar ${item.role}`;
    if (avatar instanceof HTMLImageElement) {
      avatar.src = lastCharacterCard.cover_url;
      avatar.alt = currentCharacterDisplayName();
    } else {
      const text = item.role === 'user' ? currentUserDisplayName() : currentCharacterDisplayName();
      avatar.textContent = (text || '?').trim().slice(0, 1).toUpperCase();
      if (item.role === 'user' && userAvatarUrl) {
        avatar.style.backgroundImage = `url("${userAvatarUrl}")`;
        avatar.textContent = '';
        avatar.classList.add('has-image');
      }
    }
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = item.role === 'user' ? currentUserDisplayName() : currentCharacterDisplayName();
    head.appendChild(avatar);
    head.appendChild(label);
    const body = document.createElement('div');
    body.className = 'msg-body';
    if (item.role === 'assistant') {
      body.innerHTML = renderMarkdown(item.content);
    } else {
      body.textContent = item.content;
    }
    article.appendChild(head);
    article.appendChild(body);
    messagesEl.appendChild(article);
  }

  if (historyToolbar) historyToolbar.hidden = true;
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

function jumpToConversationEnd() {
  shouldStickToBottom = true;
  historyRevealAllowed = false;
  inlineHistoryVisible = false;
  focusLatestAssistant({ smooth: false });
  requestAnimationFrame(updateHistoryToolbarVisibility);
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
    if (!value || value === '待确认') continue;
    const tr = document.createElement('tr');
    const th = document.createElement('th');
    th.textContent = label;
    const td = document.createElement('td');
    td.textContent = value || '待确认';
    tr.appendChild(th);
    tr.appendChild(td);
    table.appendChild(tr);
  }
  if (table.children.length) {
    stateEl.appendChild(table);
  }

  const summaryWrap = document.createElement('div');
  summaryWrap.className = 'state-summary-block';

  if (state.main_event) {
    const summaryLine = document.createElement('div');
    summaryLine.className = 'state-summary-line';
    summaryLine.innerHTML = '<strong>主要事件</strong>';
    const _span1 = document.createElement('span'); _span1.textContent = state.main_event; summaryLine.appendChild(_span1);
    summaryWrap.appendChild(summaryLine);
  }

  if (state.immediate_goal && state.immediate_goal !== '待确认') {
    const summaryLine = document.createElement('div');
    summaryLine.className = 'state-summary-line';
    summaryLine.innerHTML = '<strong>下一步</strong>';
    const _span2 = document.createElement('span'); _span2.textContent = state.immediate_goal; summaryLine.appendChild(_span2);
    summaryWrap.appendChild(summaryLine);
  }

  const signals = Array.isArray(state.carryover_signals) ? state.carryover_signals : [];
  if (signals.length) {
    const signalLine = document.createElement('div');
    signalLine.className = 'state-summary-line';
    signalLine.innerHTML = '<strong>延续信号</strong>';
    const signalText = signals
      .slice(0, 4)
      .map(item => typeof item === 'string' ? item : [item?.type, item?.text].filter(Boolean).join('：'))
      .filter(Boolean)
      .join(' / ');
    const signalSpan = document.createElement('span');
    signalSpan.textContent = signalText;
    signalLine.appendChild(signalSpan);
    summaryWrap.appendChild(signalLine);
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
        const ownedObjects = Array.isArray(item?.owned_objects) ? item.owned_objects : [];
        if (ownedObjects.length) {
          const owned = document.createElement('div');
          owned.className = 'object-line muted-line';
          owned.textContent = `持有：${ownedObjects.slice(0, 3).map(obj => obj?.label || obj?.object_id).filter(Boolean).join(' / ')}`;
          td.appendChild(owned);
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

  const npcRows = [];
  const seenNpc = new Set();
  for (const group of [state.onstage_entities || [], state.relevant_entities || []]) {
    for (const item of group) {
      const key = `${item?.entity_id || ''}|${item?.name || ''}`;
      if (seenNpc.has(key)) continue;
      seenNpc.add(key);
      npcRows.push(item);
    }
  }
  for (const item of state.scene_entities || []) {
    const key = `${item?.entity_id || ''}|${item?.primary_label || ''}`;
    if (seenNpc.has(key) || !item?.primary_label) continue;
    seenNpc.add(key);
    npcRows.push({
      name: item.primary_label,
      entity_id: item.entity_id || null,
      role_label: item.role_label || '',
      ambiguous: false,
      owned_objects: item.owned_objects || [],
    });
  }
  for (const item of state.important_npcs || []) {
    const key = `important|${item?.primary_label || ''}`;
    if (seenNpc.has(key) || !item?.primary_label) continue;
    seenNpc.add(key);
    npcRows.push({
      name: item.primary_label,
      entity_id: null,
      role_label: item.role_label || '',
      ambiguous: false,
    });
  }
  npcTarget.appendChild(buildNpcTable('NPC 列表', npcRows));

  // --- Objects & Carryover Signals section ---
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
      const holder = item.owner || item.bound_entity_label || possessionById[item.object_id]?.holder || '未指明';
      const status = item.possession_status || possessionById[item.object_id]?.status || '未指明';
      const vis = visibilityById[item.object_id]?.visibility || '未指明';
      const kind = item?.kind || 'item';
      const lines = [
        `${item.label || item.object_id} / ${kind}`,
        `归属：${holder}`,
        `状态：${status}`,
        `可见：${vis}`,
      ];
      if (item.bound_entity_id) lines.push(`绑定：${item.bound_entity_label || holder} (${item.bound_entity_id})`);
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

  const signalWrap = document.createElement('div');
  signalWrap.className = 'npc-block';
  const signalHeading = document.createElement('strong');
  signalHeading.textContent = '延续信号';
  signalWrap.appendChild(signalHeading);

  const signalTable = document.createElement('table');
  signalTable.className = 'state-table npc-table';
  const signalBody = document.createElement('tbody');
  if (!signals.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 2;
    td.textContent = '暂无';
    td.className = 'empty-hint';
    tr.appendChild(td);
    signalBody.appendChild(tr);
  } else {
    signals.slice(0, 6).forEach((item, idx) => {
      const tr = document.createElement('tr');
      const th = document.createElement('th');
      th.textContent = `${idx + 1}`;
      const td = document.createElement('td');
      if (typeof item === 'string') {
        td.textContent = item;
      } else {
        const type = item?.type || 'mixed';
        const text = item?.text || '待确认';
        td.textContent = `${type} / ${text}`;
      }
      tr.appendChild(th);
      tr.appendChild(td);
      signalBody.appendChild(tr);
    });
  }
  signalTable.appendChild(signalBody);
  signalWrap.appendChild(signalTable);
  otTarget.appendChild(signalWrap);
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
  const selector = debug.selector || {};
  const eventSummaryItem = debug.event_summary_item || null;
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
  lines.push('Event Memory');
  lines.push(`Event Summary Count: ${debug.event_summary_count || 0}`);
  lines.push(`Inject Summary: ${selector.inject_summary ? 'yes' : 'no'}`);
  if (selector.event_hits?.length) {
    lines.push('Event Hits');
    for (const item of selector.event_hits) {
      lines.push(`- ${item.event_id} (${item.turn_id}) score=${item.score} reason=${item.reason}`);
    }
  } else {
    lines.push('Event Hits: none');
  }
  if (eventSummaryItem?.summary) {
    lines.push('Latest Event Summary');
    lines.push(`- ${eventSummaryItem.summary}`);
  }
  lines.push('');
  lines.push('Diagnostics');
  lines.push(JSON.stringify({
    arbiter_analysis: debug.arbiter_analysis || null,
    arbiter_results: debug.arbiter_results || [],
    state_keeper_diagnostics: debug.state_keeper_diagnostics || null,
    selector: selector,
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
    historyRevealAllowed = false;
    renderMessages([]);
    updateHistoryToolbarVisibility();
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
  updateHistoryToolbarVisibility();
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
    updateHistoryToolbarVisibility();
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
  await apiJson('/api/character/select', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({character_id: characterId}),
  });
  await loadCharacters();
  currentSessionId = '';
  renderCharacterSelect();
  await Promise.all([loadSessions(), loadCharacterProfileOverride()]);
  resetSidePanels();
  if (currentSessionId) {
    await loadHistory();
    await loadState();
    jumpToConversationEnd();
  } else {
    renderMessages([]);
    renderState({});
  }
  renderTopbarContext();
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
  await loadCharacterProfileOverride();
  hideCharacterProfileDraft();
  if (data.player_profile_override_draft && typeof data.player_profile_override_draft === 'object') {
    showCharacterProfileDraft(data.player_profile_override_draft);
  }
  if (characterImportFileInput) characterImportFileInput.value = '';
  if (characterImportNameInput) characterImportNameInput.value = '';
  await loadSessions();
  resetSidePanels();
  if (currentSessionId) {
    await loadHistory();
    await loadState();
    jumpToConversationEnd();
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
  renderDebug({new_game: {session_id: data.session_id || sessionId()}});
  updateSessionIndicator();
  jumpToConversationEnd();
}

async function deleteSession(targetSessionId = sessionId()) {
  const current = targetSessionId;
  const activeBeforeDelete = sessionId();
  const data = await apiJson('/api/delete-session', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: current})
  });
  const next = (data.sessions || []).find(item => !item.replay)?.session_id || '';
  if (current === activeBeforeDelete) {
    currentSessionId = next;
  }
  await loadSessions();
  if (current === activeBeforeDelete) {
    if (next) {
      await loadHistory();
      await loadState();
      jumpToConversationEnd();
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
  if (!shouldStickToBottom && messagesEl.scrollTop <= 24) {
    historyRevealAllowed = true;
  }
  const nextInlineVisible = shouldShowInlineLoadEarlier();
  if (nextInlineVisible !== inlineHistoryVisible) {
    renderMessages(lastHistoryItems);
    return;
  }
  updateHistoryToolbarVisibility();
});

settingsBtn?.addEventListener('click', () => {
  if (settingsPanel?.dataset.open === 'true') {
    closeSettings();
  } else {
    openSettings();
  }
});

brandSettingsTrigger?.addEventListener('click', (event) => {
  event.preventDefault();
  event.stopPropagation();
  openSettings('connection');
});

brandSettingsTrigger?.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  openSettings('connection');
});

topbarContext?.addEventListener('click', (event) => {
  event.preventDefault();
  event.stopPropagation();
  openSettings('world');
});

topbarContext?.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  openSettings('world');
});

sessionIndicator?.addEventListener('click', (event) => {
  event.preventDefault();
  event.stopPropagation();
  toggleSessionDock();
});

sessionBackdrop?.addEventListener('click', () => toggleSessionDock(false));
sessionDockCloseBtn?.addEventListener('click', () => toggleSessionDock(false));

document.addEventListener('click', (e) => {
  const target = e.target;
  if (!(target instanceof Node)) return;
  if (sessionDockPanel?.hidden) return;
  if (sessionDockPanel.contains(target) || sessionIndicator?.contains(target) || sessionBackdrop?.contains(target)) return;
  toggleSessionDock(false);
});

settingsCloseBtn?.addEventListener('click', closeSettings);
settingsBackdrop?.addEventListener('click', closeSettings);

// Settings Tab Navigation
(function initSettingsTabs() {
  const tabBtns = document.querySelectorAll('.settings-tabs .settings-tab-btn');
  const tabPanels = document.querySelectorAll('.settings-tab-panel');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      tabBtns.forEach(b => b.setAttribute('aria-selected', 'false'));
      tabPanels.forEach(p => p.dataset.active = 'false');
      btn.setAttribute('aria-selected', 'true');
      const panel = document.querySelector(`.settings-tab-panel[data-tab-panel="${target}"]`);
      if (panel) panel.dataset.active = 'true';
    });
  });
})();

function openDebugPanel() {
  if (debugFloatPanel) debugFloatPanel.dataset.open = 'true';
  if (debugBackdrop) debugBackdrop.hidden = false;
}

function closeDebugPanel() {
  if (debugFloatPanel) debugFloatPanel.dataset.open = 'false';
  if (debugBackdrop) debugBackdrop.hidden = true;
}

debugToggleBtn?.addEventListener('click', () => {
  if (debugFloatPanel?.dataset.open === 'true') closeDebugPanel();
  else openDebugPanel();
});
debugCloseBtn?.addEventListener('click', closeDebugPanel);
debugBackdrop?.addEventListener('click', closeDebugPanel);

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

editBaseUserProfileBtn?.addEventListener('click', () => {
  openProfileEditor('base', '维护基础设定', '当前用户基础设定（JSON）', userProfile);
});

editCharacterProfileOverrideBtn?.addEventListener('click', async () => {
  try {
    await loadCharacterProfileOverride();
    openProfileEditor('override', '维护当前角色卡强化设定', '当前角色卡强化设定（JSON）', currentCharacterProfileOverride);
  } catch (err) {
    if (userProfileNote) {
      userProfileNote.textContent = err.message;
      userProfileNote.dataset.kind = 'error';
    }
  }
});

uploadUserAvatarBtn?.addEventListener('click', () => {
  userAvatarFileInput?.click();
});

userAvatarFileInput?.addEventListener('change', async () => {
  try {
    await uploadUserAvatar();
    if (userProfileNote) {
      userProfileNote.textContent = '用户头像已上传';
      userProfileNote.dataset.kind = 'ok';
    }
    renderMessages(lastHistoryItems);
    setStatus('用户头像已上传', 'ok');
  } catch (err) {
    if (userProfileNote) {
      userProfileNote.textContent = err.message;
      userProfileNote.dataset.kind = 'error';
    }
    setStatus(`错误：${err.message}`, 'error');
  }
});

deleteUserAvatarBtn?.addEventListener('click', async () => {
  try {
    await deleteUserAvatar();
    if (userProfileNote) {
      userProfileNote.textContent = '用户头像已删除';
      userProfileNote.dataset.kind = 'ok';
    }
    renderMessages(lastHistoryItems);
    setStatus('用户头像已删除', 'ok');
  } catch (err) {
    if (userProfileNote) {
      userProfileNote.textContent = err.message;
      userProfileNote.dataset.kind = 'error';
    }
    setStatus(`错误：${err.message}`, 'error');
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
    closeDebugPanel();
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

settingsCharacterSelectEl?.addEventListener('change', async (e) => {
  try {
    setStatus('切换角色卡中...', 'working');
    await selectCharacter(e.target.value);
    closeSettings();
    setStatus('角色卡已切换', 'ok');
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
});

profileEditorSaveBtn?.addEventListener('click', async () => {
  try {
    if (profileEditorMode === 'base') {
      await saveUserProfile();
      if (userProfileNote) {
        userProfileNote.textContent = '基础设定已保存';
        userProfileNote.dataset.kind = 'ok';
      }
      renderMessages(lastHistoryItems);
    } else if (profileEditorMode === 'override') {
      await saveCharacterProfileDraft();
      await loadCharacterProfileOverride();
      if (userProfileNote) {
        userProfileNote.textContent = '当前卡强化设定已保存';
        userProfileNote.dataset.kind = 'ok';
      }
    }
    closeProfileEditor();
  } catch (err) {
    if (profileEditorNote) {
      profileEditorNote.textContent = err.message;
      profileEditorNote.dataset.kind = 'error';
    }
  }
});

profileEditorCancelBtn?.addEventListener('click', closeProfileEditor);
profileEditorCloseBtn?.addEventListener('click', closeProfileEditor);
profileEditorBackdrop?.addEventListener('click', closeProfileEditor);

charWizardStartBtn?.addEventListener('click', () => {
  if (charWizardStep1) charWizardStep1.hidden = true;
  if (charWizardStep2) charWizardStep2.hidden = false;
});

charWizardCancelBtn?.addEventListener('click', () => {
  if (charWizardStep2) charWizardStep2.hidden = true;
  if (charWizardStep1) charWizardStep1.hidden = false;
  if (characterImportFileInput) characterImportFileInput.value = '';
  if (characterImportNameInput) characterImportNameInput.value = '';
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
    if (charWizardStep2) charWizardStep2.hidden = true;
    setStatus('角色卡已导入', 'ok');
  } catch (err) {
    if (characterImportNote) {
      characterImportNote.textContent = err.message;
      characterImportNote.dataset.kind = 'error';
    }
    setStatus(`错误：${err.message}`, 'error');
  }
});

saveCharacterProfileDraftBtn?.addEventListener('click', async () => {
  try {
    await saveCharacterProfileDraft();
    setStatus('主角设定已保存', 'ok');
  } catch (err) {
    if (characterProfileDraftNote) {
      characterProfileDraftNote.textContent = err.message;
      characterProfileDraftNote.dataset.kind = 'error';
    }
    setStatus(`错误：${err.message}`, 'error');
  }
});

skipCharacterProfileDraftBtn?.addEventListener('click', () => {
  hideCharacterProfileDraft();
  setStatus('已跳过本次主角设定补充', 'ok');
});

/* --- 聊天记录导入 --- */
let _chatImportContentB64 = null;

chatWizardStartBtn?.addEventListener('click', () => {
  if (chatWizardStep1) chatWizardStep1.hidden = true;
  if (chatWizardStep2) chatWizardStep2.hidden = false;
});

chatWizardCancelBtn?.addEventListener('click', () => {
  if (chatWizardStep2) chatWizardStep2.hidden = true;
  if (chatWizardStep1) chatWizardStep1.hidden = false;
  if (chatImportFileInput) chatImportFileInput.value = '';
});

chatWizardBackBtn?.addEventListener('click', () => {
  if (chatWizardStep3) chatWizardStep3.hidden = true;
  if (chatWizardStep2) chatWizardStep2.hidden = false;
  _chatImportContentB64 = null;
  if (chatImportBtn) chatImportBtn.disabled = true;
});

chatImportPreviewBtn?.addEventListener('click', async () => {
  const file = chatImportFileInput?.files?.[0];
  if (!file) { _chatNote('请先选择 .jsonl 文件', 'error'); return; }
  try {
    _chatNote('校验中...', '');
    chatImportBtn.disabled = true;
    _chatImportContentB64 = null;
    const raw = await _readFileBase64(file);
    const resp = await apiJson('/api/chat/preview', { method: 'POST', body: JSON.stringify({ content_base64: raw }) });
    _chatImportContentB64 = raw;
    const p = chatImportPreview;
    if (p) {
      p.hidden = false;
      const ok = resp.match;
      p.dataset.kind = ok ? 'ok' : 'warning';
      p.textContent = '';
      const _ic = document.createElement('b'); _ic.textContent = resp.inferred_character || '未知';
      const _ec = document.createElement('b'); _ec.textContent = resp.expected_character || '当前角色';
      p.append('角色名：', _ic, ' | 期望：', _ec,
        ` | 消息：${resp.message_count || 0} 条` + (ok ? ' ✓ 匹配' : ' ⚠ 不匹配（名称不一致）'));
    }
    chatImportBtn.disabled = !resp.match;
    if (chatWizardStep2) chatWizardStep2.hidden = true;
    if (chatWizardStep3) chatWizardStep3.hidden = false;
    _chatNote(resp.match ? '校验通过，可以导入' : '角色名不匹配，请检查', resp.match ? 'ok' : 'warning');
  } catch (err) {
    _chatNote(err.message, 'error');
  }
});

chatImportBtn?.addEventListener('click', async () => {
  if (!_chatImportContentB64) { _chatNote('请先预览检查', 'error'); return; }
  try {
    _chatNote('导入中...', '');
    chatImportBtn.disabled = true;
    const file = chatImportFileInput?.files?.[0];
    const resp = await apiJson('/api/chat/import', {
      method: 'POST',
      body: JSON.stringify({
        content_base64: _chatImportContentB64,
        filename: file?.name || 'imported.jsonl',
      }),
    });
    _chatImportContentB64 = null;
    if (chatImportPreview) chatImportPreview.hidden = true;
    chatImportBtn.disabled = true;
    // Reset wizard to step 1
    if (chatWizardStep3) chatWizardStep3.hidden = true;
    if (chatWizardStep1) chatWizardStep1.hidden = false;
    if (chatImportFileInput) chatImportFileInput.value = '';
    const r = resp.report || {};
    _chatNote(`导入成功：${r.stats?.imported_message_count || 0} 条消息 → 会话 ${r.target_session || ''}`, 'ok');
    setStatus('聊天记录已导入', 'ok');
    await loadSessions();
    if (r.target_session) {
      currentSessionId = r.target_session;
      updateSessionIndicator();
      resetSidePanels();
      await loadHistory();
      await loadState();
      jumpToConversationEnd();
      renderSessionDock();
    }
  } catch (err) {
    chatImportBtn.disabled = false;
    _chatNote(err.message, 'error');
  }
});

function _chatNote(msg, kind) {
  if (chatImportNote) { chatImportNote.textContent = msg; chatImportNote.dataset.kind = kind || ''; }
}

function _readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = () => reject(new Error('文件读取失败'));
    reader.readAsDataURL(file);
  });
}

async function checkAuth() {
  try {
    const data = await apiJson('/api/auth/me');
    currentUserId = data.user_id || 'default-user';
  } catch (_err) {
    currentUserId = 'default-user';
  }
}

(async function init() {
  setStatus('初始化中...', 'working');
  try {
    await checkAuth();
    resetSidePanels();
    await Promise.all([
      loadSessions(),
      loadCharacters(),
      loadUserProfile(),
      loadSiteConfig(),
      loadModelConfig(),
    ]);
    await loadHistory();
    await loadState();
    closeSettings();
    toggleSessionDock(false);
    jumpToConversationEnd();

    // LLM 首次设置引导：检测未配置时自动弹出设置面板
    const needsSetup = !siteConfig.base_url || siteConfig.status !== 'ready';
    if (needsSetup) {
      openSettings('connection');
      const guide = document.getElementById('llmSetupGuide');
      if (guide) guide.hidden = false;
      setStatus('请先配置 LLM 连接', 'warning');
    } else {
      setStatus('就绪', 'ok');
    }
  } catch (err) {
    setStatus(`错误：${err.message}`, 'error');
  }
})();
