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
const topbarSessionMenu = document.getElementById('topbarSessionMenu');
const brandSettingsTrigger = document.getElementById('brandSettingsTrigger');
const debugFloatPanel = document.getElementById('debugFloatPanel');
const debugBackdrop = document.getElementById('debugBackdrop');
const debugCloseBtn = document.getElementById('debugCloseBtn');
const debugToggleBtn = document.getElementById('debugToggleBtn');
const settingsBtn = document.getElementById('settingsBtn');
const settingsPanel = document.getElementById('settingsPanel');
const settingsBackdrop = document.getElementById('settingsBackdrop');
const settingsCloseBtn = document.getElementById('settingsCloseBtn');
const characterScopeEl = document.getElementById('characterScope');
const characterSelectEl = document.getElementById('characterSelect');
const settingsCharacterSelectEl = document.getElementById('settingsCharacterSelect');
const characterSubtitleEl = document.getElementById('characterSubtitle');
const characterCoverEl = document.getElementById('characterCover');
const characterCoverFallbackEl = document.getElementById('characterCoverFallback');
const sessionDockPanel = document.getElementById('sessionDockPanel');
const sessionDockList = document.getElementById('sessionDockList');
const mobileSessionMenu = document.getElementById('mobileSessionMenu');
const mobileSessionToggle = document.getElementById('mobileSessionToggle');
const mobileSessionPanel = document.getElementById('mobileSessionPanel');
const mobileSessionList = document.getElementById('mobileSessionList');
const historyToolbar = document.getElementById('historyToolbar');
const loadEarlierBtn = document.getElementById('loadEarlierBtn');
const saveModelConfigBtn = document.getElementById('saveModelConfigBtn');
const narratorModelSelect = document.getElementById('narratorModelSelect');
const stateKeeperModelSelect = document.getElementById('stateKeeperModelSelect');
const narratorPresetSelect = document.getElementById('narratorPresetSelect');
const editNarratorPresetBtn = document.getElementById('editNarratorPresetBtn');
const deleteNarratorPresetBtn = document.getElementById('deleteNarratorPresetBtn');
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

let lastCharacterCard = null;
let shouldStickToBottom = true;
let pendingUserMessage = null;
let lastHistoryItems = [];
let historyHasMore = false;
let historyNextBefore = null;
let isLoadingEarlierHistory = false;
let historyRevealAllowed = false;
let inlineHistoryVisible = false;
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
  active_preset: 'world-sim-core',
  presets: [],
  narrator: {
    model: '',
  },
  state_keeper: {
    model: '',
  },
};
let characterItems = [];
let userProfile = {};
let userAvatarUrl = null;
let currentCharacterProfileOverride = {};
let profileEditorMode = '';
let presetEditorId = '';
let _chatImportContentB64 = null;

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
  } catch {
    const targetNote = profileEditorMode === 'override' ? profileEditorNote : characterProfileDraftNote;
    const message = `JSON 解析失败：${err.message}`;
    if (targetNote) {
      targetNote.textContent = message;
      targetNote.dataset.kind = 'error';
    }
    throw new Error(message);
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
  tabBtns.forEach((b) => {
    b.setAttribute('aria-selected', String(b.dataset.tab === tabName));
  });
  tabPanels.forEach((p) => {
    p.dataset.active = String(p.dataset.tabPanel === tabName);
  });
}

function toggleSessionDock(forceOpen) {
  if (!sessionDockPanel) return;
  const isOpen = sessionDockPanel.getAttribute('aria-hidden') !== 'true';
  const nextOpen = typeof forceOpen === 'boolean' ? forceOpen : !isOpen;
  if (nextOpen && topbarSessionMenu?.dataset.suppressed === 'true') return;
  sessionDockPanel.setAttribute('aria-hidden', String(!nextOpen));
  topbarContext?.setAttribute('aria-expanded', String(nextOpen));
}

function toggleMobileSessionDock(forceOpen) {
  if (!mobileSessionPanel) return;
  const isOpen = mobileSessionPanel.getAttribute('aria-hidden') !== 'true';
  const nextOpen = typeof forceOpen === 'boolean' ? forceOpen : !isOpen;
  mobileSessionPanel.setAttribute('aria-hidden', String(!nextOpen));
  mobileSessionToggle?.setAttribute('aria-expanded', String(nextOpen));
}

let sessionDockCloseTimer = null;

function openSessionDock() {
  if (sessionDockCloseTimer) {
    clearTimeout(sessionDockCloseTimer);
    sessionDockCloseTimer = null;
  }
  toggleSessionDock(true);
}

function closeSessionDockSoon() {
  if (sessionDockCloseTimer) clearTimeout(sessionDockCloseTimer);
  sessionDockCloseTimer = setTimeout(() => {
    sessionDockCloseTimer = null;
    topbarSessionMenu?.removeAttribute('data-suppressed');
    toggleSessionDock(false);
  }, 180);
}

function updateSessionIndicator() {
  topbarContext?.setAttribute('aria-label', `${currentUserDisplayName()} · ${currentCharacterDisplayName()} · ${currentSessionId || '未选择会话'}`);
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

function fallbackSessionId() {
  const user = (lastCharacterCard?.user_id || 'default_user').trim() || 'default_user';
  const character = (lastCharacterCard?.character_id || lastCharacterCard?.name || 'story').trim() || 'story';
  const safeUser = user.replace(/[^0-9A-Za-z_\-\u4e00-\u9fff]/g, '-');
  const safeCharacter = character.replace(/[^0-9A-Za-z_\-\u4e00-\u9fff]/g, '-');
  return `${safeCharacter}-${safeUser}`.slice(0, 100) || 'story-live';
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
    const sameCard = lastCharacterCard
      && incomingCard.user_id === lastCharacterCard.user_id
      && incomingCard.character_id === lastCharacterCard.character_id;
    lastCharacterCard = sameCard ? {...lastCharacterCard, ...incomingCard} : {...incomingCard};
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
  const presets = (modelConfig.presets || []).map(item => ({
    value: item.id,
    label: item.id,
  }));
  setSelectOptions(narratorModelSelect, models, modelConfig.narrator?.model, item => item.label);
  setSelectOptions(stateKeeperModelSelect, models, modelConfig.state_keeper?.model, item => item.label);
  setSelectOptions(narratorPresetSelect, presets, modelConfig.active_preset, item => item.label);
  if (modelConfigNote && !modelConfigNote.dataset.kind) {
    modelConfigNote.textContent = '温度和最大输出长度已固定到默认配置；叙事预设只影响 narrator 提示词。';
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
  const presetIds = new Set((modelConfig.presets || []).map(item => item.id));
  if (!draft.narrator.model) return 'Narrator 模型不能为空';
  if (!draft.state_keeper.model) return 'State Keeper 模型不能为空';
  if (!draft.active_preset) return '叙事预设不能为空';
  if (available.size === 0) return '当前还没有模型列表，请先点击“获取模型”';
  if (!available.has(draft.narrator.model)) return 'Narrator 模型不在当前站点模型列表中';
  if (!available.has(draft.state_keeper.model)) return 'State Keeper 模型不在当前站点模型列表中';
  if (presetIds.size > 0 && !presetIds.has(draft.active_preset)) return '叙事预设不存在';
  return '';
}

// 401 from these endpoints is a business-level credential error (wrong
// password, locked account, missing old password). The caller wants to
// surface backend's actual message — do NOT auto-clear token / hop to
// login screen.
const AUTH_BUSINESS_PATHS = new Set([
  '/api/auth/login',
  '/api/auth/change-password',
]);

async function apiJson(url, options = {}) {
  if (options.body && !options.headers?.['Content-Type']) {
    options.headers = { ...options.headers, 'Content-Type': 'application/json' };
  }
  const token = getAuthToken();
  if (token) {
    options.headers = { ...options.headers, 'Authorization': `Bearer ${token}` };
  }
  const res = await fetch(url, options);
  let data = null;
  try { data = await res.json(); } catch (_e) { data = null; }
  if (res.status === 401) {
    if (AUTH_BUSINESS_PATHS.has(url)) {
      // Pass the backend message through (e.g. "账户暂时锁定...").
      throw new Error(data?.error?.message || '认证失败');
    }
    clearAuthToken();
    clearClientUserState();
    showLoginScreen();
    throw new Error(data?.error?.message || '请先登录');
  }
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
  renderSessionList(sessionDockList, { closeDockOnSelect: false, noteEl: null, activeLimit: 5 });
  renderSessionList(mobileSessionList, { closeDockOnSelect: true, noteEl: null, activeLimit: 5 });
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
        if (closeDockOnSelect) {
          toggleSessionDock(false);
          toggleMobileSessionDock(false);
        }
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
      if (closeDockOnSelect) {
        toggleSessionDock(false);
        toggleMobileSessionDock(false);
      }
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
    active_preset: narratorPresetSelect.value,
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

async function loadNarratorPresetContent(presetId) {
  if (!presetId) throw new Error('叙事预设不能为空');
  return apiJson(`/api/narrator-preset?preset_id=${encodeURIComponent(presetId)}`);
}

async function openNarratorPresetEditor() {
  const presetId = narratorPresetSelect?.value || modelConfig.active_preset;
  const data = await loadNarratorPresetContent(presetId);
  presetEditorId = data.id || presetId;
  openProfileEditor('preset', `编辑叙事预设：${presetEditorId}.json`, '叙事预设 JSON', data.content || {});
}

async function saveNarratorPresetEditor() {
  if (!presetEditorId) throw new Error('叙事预设不能为空');
  let content;
  try {
    content = JSON.parse(profileEditorInput.value || '{}');
  } catch (err) {
    throw new Error(`JSON 解析失败：${err.message}`);
  }
  await apiJson('/api/narrator-preset', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'save', preset_id: presetEditorId, content}),
  });
  await loadModelConfig();
}

async function deleteSelectedNarratorPreset() {
  const presetId = narratorPresetSelect?.value || modelConfig.active_preset;
  if (!presetId) throw new Error('叙事预设不能为空');
  const ok = window.confirm(`删除叙事预设 ${presetId}.json？此操作不可撤销。`);
  if (!ok) return;
  const data = await apiJson('/api/narrator-preset', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'delete', preset_id: presetId}),
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
  renderModelConfig();
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
  presetEditorId = '';
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
    const rebuildBtn = document.createElement('button');
    rebuildBtn.type = 'button';
    rebuildBtn.className = 'subtle-btn';
    rebuildBtn.textContent = '重生成世界书';
    rebuildBtn.addEventListener('click', async () => {
      if (!window.confirm(`重新生成角色卡“${item.name || item.character_id}”的瘦身世界书吗？`)) return;
      rebuildBtn.disabled = true;
      const previousText = rebuildBtn.textContent;
      rebuildBtn.textContent = '生成中...';
      try {
        if (characterManageNote) {
          characterManageNote.textContent = `正在重新生成世界书：${item.name || item.character_id}`;
          characterManageNote.dataset.kind = '';
        }
        const data = await apiJson('/api/character/rebuild-lorebook', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({character_id: item.character_id}),
        });
        characterItems = data.characters || characterItems;
        renderCharacterSelect();
        const report = data.lorebook_distillation || {};
        if (characterManageNote) {
          characterManageNote.textContent = `世界书已重生成：foundation ${report.foundation_rules ?? 0} 条，index ${report.index_items ?? 0} 条（${report.provider || 'unknown'}）`;
          characterManageNote.dataset.kind = 'ok';
        }
      } catch (err) {
        if (characterManageNote) {
          characterManageNote.textContent = `世界书重生成失败：${err.message}`;
          characterManageNote.dataset.kind = 'error';
        }
      } finally {
        rebuildBtn.disabled = false;
        rebuildBtn.textContent = previousText;
      }
    });
    actions.appendChild(rebuildBtn);
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
      newBtn.disabled = true;
      setStatus('新游戏初始化中...', 'working');
      try {
        await startNewGame();
        setStatus('已开始新对话', 'ok');
      } catch (err) {
        setStatus(`错误：${err.message}`, 'error');
      } finally {
        newBtn.disabled = false;
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
    const root = document.createElement('div');
    const escaped = String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    root.innerHTML = marked.parse(escaped, { breaks: true, gfm: true });
    root.querySelectorAll('script, iframe, object, embed, link, meta, style, form').forEach((node) => {
      node.remove();
    });
    root.querySelectorAll('*').forEach(node => {
      for (const attr of [...node.attributes]) {
        const name = attr.name.toLowerCase();
        const value = attr.value.trim().toLowerCase();
        if (name.startsWith('on') || name === 'style') {
          node.removeAttribute(attr.name);
        } else if ((name === 'href' || name === 'src') && value && !value.startsWith('#') && !value.startsWith('/') && !value.startsWith('http://') && !value.startsWith('https://')) {
          node.removeAttribute(attr.name);
        }
      }
    });
    return root.innerHTML;
  }
  return text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
        const entityId = item?.entity_id || item?.actor_id || null;
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
  const seenNpcNames = new Set();
  const actors = state.actors && typeof state.actors === 'object' ? state.actors : {};
  const actorIndex = state.actor_context_index && typeof state.actor_context_index === 'object' ? state.actor_context_index : {};
  const activeActorIds = Array.isArray(actorIndex.active_actor_ids) ? actorIndex.active_actor_ids : Object.keys(actors);
  for (const actorId of activeActorIds) {
    if (actorId === 'protagonist') continue;
    const actor = actors[actorId];
    if (!actor || typeof actor !== 'object' || actor.kind === 'protagonist') continue;
    const name = actor.name || actor.aliases?.[0] || '';
    if (!name) continue;
    const key = `actor|${actorId}`;
    if (seenNpc.has(key) || seenNpcNames.has(name)) continue;
    seenNpc.add(key);
    seenNpcNames.add(name);
    npcRows.push({
      name,
      entity_id: actorId,
      actor_id: actorId,
      role_label: actor.identity || 'actor registry',
      ambiguous: false,
    });
  }
  for (const group of [state.onstage_entities || [], state.relevant_entities || []]) {
    for (const item of group) {
      const key = `${item?.entity_id || ''}|${item?.name || ''}`;
      if (seenNpc.has(key) || seenNpcNames.has(item?.name || '')) continue;
      seenNpc.add(key);
      if (item?.name) seenNpcNames.add(item.name);
      npcRows.push(item);
    }
  }
  for (const item of state.scene_entities || []) {
    const key = `${item?.entity_id || ''}|${item?.primary_label || ''}`;
    if (seenNpc.has(key) || !item?.primary_label || seenNpcNames.has(item.primary_label)) continue;
    seenNpc.add(key);
    seenNpcNames.add(item.primary_label);
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
    if (seenNpc.has(key) || !item?.primary_label || seenNpcNames.has(item.primary_label)) continue;
    seenNpc.add(key);
    seenNpcNames.add(item.primary_label);
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
  const previousSessionId = sessionId() || fallbackSessionId();
  const data = await apiJson('/api/new-game', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: previousSessionId})
  });
  currentSessionId = data.session_id || previousSessionId;
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
  const data = await apiJson(`/api/entity?session_id=${encodeURIComponent(sessionId())}&entity_id=${encodeURIComponent(entityId)}`);
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
  } catch {
    pendingUserMessage = null;
    input.value = originalText;
    renderMessages(lastHistoryItems);
    setStatus('发送失败', 'error');
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
  if (sessionDockCloseTimer) {
    clearTimeout(sessionDockCloseTimer);
    sessionDockCloseTimer = null;
  }
  topbarSessionMenu?.setAttribute('data-suppressed', 'true');
  toggleSessionDock(false);
  openSettings('world');
});

topbarContext?.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  if (sessionDockCloseTimer) {
    clearTimeout(sessionDockCloseTimer);
    sessionDockCloseTimer = null;
  }
  topbarSessionMenu?.setAttribute('data-suppressed', 'true');
  toggleSessionDock(false);
  openSettings('world');
});

topbarSessionMenu?.addEventListener('mouseenter', openSessionDock);
topbarSessionMenu?.addEventListener('mouseleave', closeSessionDockSoon);
sessionDockPanel?.addEventListener('mouseenter', openSessionDock);
sessionDockPanel?.addEventListener('mouseleave', closeSessionDockSoon);
topbarSessionMenu?.addEventListener('focusin', openSessionDock);
topbarSessionMenu?.addEventListener('focusout', (event) => {
  const nextTarget = event.relatedTarget;
  if (nextTarget instanceof Node && topbarSessionMenu.contains(nextTarget)) return;
  toggleSessionDock(false);
});

mobileSessionToggle?.addEventListener('click', (event) => {
  event.preventDefault();
  event.stopPropagation();
  toggleMobileSessionDock();
});

mobileSessionMenu?.addEventListener('click', (event) => {
  event.stopPropagation();
});

document.addEventListener('click', (event) => {
  const target = event.target;
  if (target instanceof Node && mobileSessionMenu?.contains(target)) return;
  toggleMobileSessionDock(false);
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
      tabBtns.forEach((b) => {
        b.setAttribute('aria-selected', 'false');
      });
      tabPanels.forEach((p) => {
        p.dataset.active = 'false';
      });
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

editNarratorPresetBtn?.addEventListener('click', async () => {
  try {
    await openNarratorPresetEditor();
  } catch (err) {
    if (modelConfigNote) {
      modelConfigNote.textContent = err.message;
      modelConfigNote.dataset.kind = 'error';
    }
  }
});

deleteNarratorPresetBtn?.addEventListener('click', async () => {
  try {
    await deleteSelectedNarratorPreset();
    if (modelConfigNote) {
      modelConfigNote.textContent = '叙事预设已删除';
      modelConfigNote.dataset.kind = 'ok';
    }
  } catch (err) {
    if (modelConfigNote) {
      modelConfigNote.textContent = err.message;
      modelConfigNote.dataset.kind = 'error';
    }
  }
});

narratorPresetSelect?.addEventListener('change', () => {
  if (modelConfigNote) {
    modelConfigNote.textContent = '预设已切换，点击“保存模型配置”后生效。';
    modelConfigNote.dataset.kind = '';
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
    toggleMobileSessionDock(false);
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
      setStatus('当前卡强化设定已保存', 'ok');
      if (userProfileNote) {
        userProfileNote.textContent = '当前卡强化设定已保存';
        userProfileNote.dataset.kind = 'ok';
      }
    } else if (profileEditorMode === 'preset') {
      await saveNarratorPresetEditor();
      setStatus('叙事预设已保存', 'ok');
      if (modelConfigNote) {
        modelConfigNote.textContent = '叙事预设已保存';
        modelConfigNote.dataset.kind = 'ok';
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
        ` | 消息：${resp.message_count || 0} 条${ok ? ' ✓ 匹配' : ' ⚠ 不匹配（名称不一致）'}`);
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
    authState.userId = data.user_id || 'default-user';
    authState.role = data.role || 'admin';
    authState.multiUserEnabled = !!data.multi_user_enabled;
    authState.adminHasPassword = !!data.admin_has_password;
    return data;
  } catch (_err) {
    authState.userId = '';
    authState.role = 'admin';
    authState.multiUserEnabled = false;
    authState.adminHasPassword = false;
    return null;
  }
}

(async function init() {
  setStatus('初始化中...', 'working');
  try {
    await checkAuth();
    // multi-user enabled but unauthenticated → defer the rest of the boot to
    // the login flow; runMainBoot() picks up after a successful login.
    if (authState.multiUserEnabled && !authState.userId) {
      showLoginScreen();
      return;
    }
    await runMainBoot();
  } catch (err) {
    console.error('init failed', err);
    setStatus('初始化失败', 'error');
  }
})();

async function runMainBoot() {
  // Self-heal: if the user is in single-user mode, clear any stale token
  // left over from an earlier multi-user session and make sure we are not
  // sitting on the login overlay. checkAuth() has already run by the time
  // we get here so authState is authoritative.
  if (!authState.multiUserEnabled) {
    if (getAuthToken()) clearAuthToken();
  }
  clearClientUserState();
  applyRoleBasedUI();
  setStatus('初始化中...', 'working');
  try {
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
    hideLoginScreen();
    closeSettings();
    toggleSessionDock(false);
    jumpToConversationEnd();

    const needsSetup = !siteConfig.base_url || siteConfig.status !== 'ready';
    // Only the admin can fix a missing site config; for ordinary users the
    // setup wizard is meaningless because the controls are read-only.
    if (needsSetup && authState.role === 'admin') {
      openSettings('connection');
      const guide = document.getElementById('llmSetupGuide');
      if (guide) guide.hidden = false;
      setStatus('请先配置 LLM 连接', 'warning');
    } else if (needsSetup) {
      setStatus('管理员尚未配置站点连接', 'warning');
    } else {
      setStatus('就绪', 'ok');
    }
  } catch (err) {
    console.error('boot failed', err);
    setStatus(`载入失败：${err?.message || err}`, 'error');
  }
}

// ─────────────────────────────────────────────────────────────
// Multi-user auth + settings glue
// ─────────────────────────────────────────────────────────────

const AUTH_TOKEN_KEY = 'tl_session_token';

const authState = {
  userId: '',
  role: 'admin',
  multiUserEnabled: false,
  adminHasPassword: false,
};

function getAuthToken() {
  try { return localStorage.getItem(AUTH_TOKEN_KEY) || ''; } catch (_e) { return ''; }
}
function setAuthToken(token) {
  try { localStorage.setItem(AUTH_TOKEN_KEY, token); } catch (_e) {}
}
function clearAuthToken() {
  try { localStorage.removeItem(AUTH_TOKEN_KEY); } catch (_e) {}
}

function clearClientUserState() {
  pendingUserMessage = null;
  lastHistoryItems = [];
  historyHasMore = false;
  historyNextBefore = null;
  historyTotalCount = 0;
  isLoadingEarlierHistory = false;
  historyRevealAllowed = false;
  inlineHistoryVisible = false;
  currentSessionId = '';
  sessionItems = [];
  isWaitingForResponse = false;
  coverLoadToken += 1;
  lastCharacterCard = null;
  lastCharacterCoverUrl = null;
  characterItems = [];
  userProfile = {};
  userAvatarUrl = null;
  currentCharacterProfileOverride = {};
  profileEditorMode = '';
  presetEditorId = '';
  _chatImportContentB64 = null;
  if (messagesEl) messagesEl.innerHTML = '';
  resetSidePanels();
  renderState({});
  updateSessionIndicator();
  if (profileEditorInput) profileEditorInput.value = '';
  if (profileEditorNote) profileEditorNote.textContent = '';
  closeProfileEditor();
  if (chatImportPreview) {
    chatImportPreview.textContent = '';
    chatImportPreview.hidden = true;
  }
  if (chatImportBtn) chatImportBtn.disabled = true;
  if (chatImportFileInput) chatImportFileInput.value = '';
  if (characterImportFileInput) characterImportFileInput.value = '';
  if (characterImportNameInput) characterImportNameInput.value = '';
  if (loginErrorEl) loginErrorEl.textContent = '';
}

const loginScreenEl = document.getElementById('loginScreen');
const appShellEl = document.getElementById('appShell');
const loginFormEl = document.getElementById('loginForm');
const loginUserIdEl = document.getElementById('loginUserId');
const loginPasswordEl = document.getElementById('loginPassword');
const loginErrorEl = document.getElementById('loginError');
const authIndicatorEl = document.getElementById('authIndicator');
const authIndicatorLabelEl = document.getElementById('authIndicatorLabel');
const logoutBtnEl = document.getElementById('logoutBtn');

function showLoginScreen() {
  clearClientUserState();
  if (loginScreenEl) loginScreenEl.hidden = false;
  if (appShellEl) appShellEl.hidden = true;
  if (loginUserIdEl) loginUserIdEl.value = '';
  if (loginPasswordEl) loginPasswordEl.value = '';
  if (loginErrorEl) loginErrorEl.textContent = '';
  if (loginUserIdEl) loginUserIdEl.focus();
}
function hideLoginScreen() {
  if (loginScreenEl) loginScreenEl.hidden = true;
  if (appShellEl) appShellEl.hidden = false;
}

function applyRoleBasedUI() {
  // In single-user mode the admin (default-user) is always implicit, so no
  // login indicator and no role-based gating is necessary.
  if (!authState.multiUserEnabled) {
    if (authIndicatorEl) authIndicatorEl.hidden = true;
    document.querySelectorAll('.admin-only').forEach(el => { el.hidden = false; });
    document.querySelectorAll('[data-admin-disable]').forEach(el => { el.disabled = false; });
    return;
  }
  if (authIndicatorEl) authIndicatorEl.hidden = false;
  if (authIndicatorLabelEl) {
    const tag = authState.role === 'admin' ? '管理员' : '用户';
    authIndicatorLabelEl.textContent = `${tag} · ${authState.userId}`;
  }
  if (logoutBtnEl) logoutBtnEl.hidden = false;

  const isAdmin = authState.role === 'admin';
  document.querySelectorAll('.admin-only').forEach(el => { el.hidden = !isAdmin; });
  document.querySelectorAll('[data-admin-disable]').forEach(el => { el.disabled = !isAdmin; });
  // 站点连接 / provider 是 admin-only 写。普通用户看到只读字段。
  const adminWriteFields = [
    'siteBaseUrl', 'siteApiKey', 'siteApiType',
    'saveSiteConfigBtn', 'discoverSiteModelsBtn',
  ];
  adminWriteFields.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.tagName === 'BUTTON') {
      el.hidden = !isAdmin;
    } else {
      el.disabled = !isAdmin;
      if (!isAdmin) el.classList.add('readonly-input'); else el.classList.remove('readonly-input');
    }
  });
}

if (loginFormEl) {
  loginFormEl.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (loginErrorEl) loginErrorEl.textContent = '';
    const userId = (loginUserIdEl?.value || '').trim();
    const password = loginPasswordEl?.value || '';
    if (!userId || !password) {
      if (loginErrorEl) loginErrorEl.textContent = '请输入用户名和密码';
      return;
    }
    try {
      const data = await apiJson('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, password }),
      });
      setAuthToken(data.token);
      await checkAuth();
      await runMainBoot();
    } catch (err) {
      if (loginErrorEl) loginErrorEl.textContent = err.message || '登录失败';
    }
  });
}

if (logoutBtnEl) {
  logoutBtnEl.addEventListener('click', async () => {
    try { await apiJson('/api/auth/logout', { method: 'POST', body: '{}' }); } catch (_e) {}
    clearAuthToken();
    clearClientUserState();
    showLoginScreen();
  });
}

// ── Change-password ─────────────────────────────────────────
const changePasswordFormEl = document.getElementById('changePasswordForm');
const changePasswordOldEl = document.getElementById('changePasswordOld');
const changePasswordNewEl = document.getElementById('changePasswordNew');
const changePasswordConfirmEl = document.getElementById('changePasswordConfirm');
const changePasswordNoteEl = document.getElementById('changePasswordNote');

if (changePasswordFormEl) {
  changePasswordFormEl.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (changePasswordNoteEl) changePasswordNoteEl.textContent = '';
    const oldPwd = changePasswordOldEl?.value || '';
    const newPwd = changePasswordNewEl?.value || '';
    const confirmPwd = changePasswordConfirmEl?.value || '';
    if (newPwd !== confirmPwd) {
      if (changePasswordNoteEl) changePasswordNoteEl.textContent = '两次输入的新密码不一致';
      return;
    }
    if (newPwd.length < 12) {
      if (changePasswordNoteEl) changePasswordNoteEl.textContent = '新密码至少需要 12 个字符';
      return;
    }
    try {
      await apiJson('/api/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
      });
      if (changePasswordNoteEl) changePasswordNoteEl.textContent = '密码已更新；其他设备已被注销。';
      changePasswordFormEl.reset();
    } catch (err) {
      if (changePasswordNoteEl) changePasswordNoteEl.textContent = err.message || '更新失败';
    }
  });
}

// ── Multi-user toggle wizard ────────────────────────────────
const multiUserStatusEl = document.getElementById('multiUserStatus');
const multiUserToggleBtnEl = document.getElementById('multiUserToggleBtn');
const multiUserNoteEl = document.getElementById('multiUserNote');

function renderMultiUserStatus() {
  if (!multiUserStatusEl || !multiUserToggleBtnEl) return;
  if (authState.multiUserEnabled) {
    multiUserStatusEl.textContent = '当前为多用户模式。';
    multiUserToggleBtnEl.textContent = '关闭多用户模式';
  } else if (authState.adminHasPassword) {
    multiUserStatusEl.textContent = '当前为单用户模式。点击下方按钮启用多用户。';
    multiUserToggleBtnEl.textContent = '启用多用户模式';
  } else {
    multiUserStatusEl.textContent = '尚未设置管理员密码；启用多用户前需要设置。';
    multiUserToggleBtnEl.textContent = '设置管理员密码并启用多用户';
  }
}

async function silentReLogin(password) {
  try {
    const data = await apiJson('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ user_id: 'default-user', password }),
    });
    setAuthToken(data.token);
    await checkAuth();
    return true;
  } catch (err) {
    console.warn('silent re-login failed', err);
    return false;
  }
}

// ── Password modal (replaces window.prompt) ────────────────
const passwordPromptBackdrop = document.getElementById('passwordPromptBackdrop');
const passwordPromptModal = document.getElementById('passwordPromptModal');
const passwordPromptForm = document.getElementById('passwordPromptForm');
const passwordPromptTitle = document.getElementById('passwordPromptTitle');
const passwordPromptHint = document.getElementById('passwordPromptHint');
const passwordPromptInput1 = document.getElementById('passwordPromptInput1');
const passwordPromptInput2 = document.getElementById('passwordPromptInput2');
const passwordPromptField2 = document.getElementById('passwordPromptField2');
const passwordPromptLabel1 = document.getElementById('passwordPromptLabel1');
const passwordPromptLabel2 = document.getElementById('passwordPromptLabel2');
const passwordPromptError = document.getElementById('passwordPromptError');
const passwordPromptCancelBtn = document.getElementById('passwordPromptCancelBtn');

let _activePasswordPrompt = null;

function showPasswordPrompt({ title, hint, label1 = '密码', label2 = '', requireConfirm = false, minLength = 0 }) {
  return new Promise((resolve) => {
    if (_activePasswordPrompt) {
      _activePasswordPrompt(null);
      _activePasswordPrompt = null;
    }
    if (passwordPromptTitle) passwordPromptTitle.textContent = title || '输入密码';
    if (passwordPromptHint) passwordPromptHint.textContent = hint || '';
    if (passwordPromptLabel1) passwordPromptLabel1.textContent = label1;
    if (passwordPromptLabel2) passwordPromptLabel2.textContent = label2 || '确认密码';
    if (passwordPromptInput1) passwordPromptInput1.value = '';
    if (passwordPromptInput2) passwordPromptInput2.value = '';
    if (passwordPromptError) passwordPromptError.textContent = '';
    if (passwordPromptField2) passwordPromptField2.hidden = !requireConfirm;
    if (passwordPromptBackdrop) passwordPromptBackdrop.hidden = false;
    if (passwordPromptModal) passwordPromptModal.hidden = false;
    setTimeout(() => passwordPromptInput1?.focus(), 0);
    _activePasswordPrompt = (value) => {
      if (passwordPromptBackdrop) passwordPromptBackdrop.hidden = true;
      if (passwordPromptModal) passwordPromptModal.hidden = true;
      _activePasswordPrompt = null;
      resolve(value);
    };
    passwordPromptForm._validateAndSubmit = () => {
      const pwd1 = passwordPromptInput1?.value || '';
      const pwd2 = passwordPromptInput2?.value || '';
      if (!pwd1) {
        if (passwordPromptError) passwordPromptError.textContent = '密码不能为空';
        return;
      }
      if (minLength && pwd1.length < minLength) {
        if (passwordPromptError) passwordPromptError.textContent = `密码至少需要 ${minLength} 位`;
        return;
      }
      if (requireConfirm && pwd1 !== pwd2) {
        if (passwordPromptError) passwordPromptError.textContent = '两次输入不一致';
        return;
      }
      if (_activePasswordPrompt) _activePasswordPrompt(pwd1);
    };
  });
}

if (passwordPromptForm) {
  passwordPromptForm.addEventListener('submit', (event) => {
    event.preventDefault();
    if (typeof passwordPromptForm._validateAndSubmit === 'function') {
      passwordPromptForm._validateAndSubmit();
    }
  });
}
if (passwordPromptCancelBtn) {
  passwordPromptCancelBtn.addEventListener('click', () => {
    if (_activePasswordPrompt) _activePasswordPrompt(null);
  });
}
if (passwordPromptBackdrop) {
  passwordPromptBackdrop.addEventListener('click', () => {
    if (_activePasswordPrompt) _activePasswordPrompt(null);
  });
}

async function enableMultiUserWizard() {
  if (multiUserNoteEl) multiUserNoteEl.textContent = '';
  // Re-fetch authState so the bootstrap branch decision uses live data.
  await checkAuth();
  let password = '';
  if (!authState.adminHasPassword) {
    password = await showPasswordPrompt({
      title: '设置管理员密码',
      hint: '启用多用户前必须先设置管理员密码（至少 12 位）。请妥善保存：忘记后只能停服后手动改 users.json 重置。',
      label1: '新密码',
      label2: '确认新密码',
      requireConfirm: true,
      minLength: 12,
    });
    if (!password) return;
    try {
      await apiJson('/api/users', {
        method: 'POST',
        body: JSON.stringify({ action: 'set_admin_password', password }),
      });
    } catch (err) {
      if (multiUserNoteEl) multiUserNoteEl.textContent = `设置密码失败：${err.message}`;
      return;
    }
    // Refresh authState so a follow-up retry in the same session knows the
    // password is now set.
    await checkAuth();
  } else {
    password = await showPasswordPrompt({
      title: '确认启用多用户',
      hint: '请输入管理员密码确认。启用后所有用户必须重新登录。',
      label1: '管理员密码',
    });
    if (!password) return;
    // Verify the password BEFORE flipping the toggle so a wrong/forgotten
    // password cannot lock the admin out. /api/multi-user only checks the
    // admin token, not the password — without this gate the wizard would
    // happily enable multi-user with garbage input and the silent re-login
    // would then fail, stranding the user on the login screen.
    try {
      const data = await apiJson('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ user_id: 'default-user', password }),
      });
      // Adopt the freshly issued token so subsequent state-changing calls
      // stay authenticated even if some intermediate logic invalidated the
      // previous one.
      setAuthToken(data.token);
    } catch (err) {
      if (multiUserNoteEl) multiUserNoteEl.textContent = `密码错误：${err.message}`;
      return;
    }
  }
  try {
    await apiJson('/api/multi-user', {
      method: 'POST',
      body: JSON.stringify({ enabled: true, password }),
    });
  } catch (err) {
    if (multiUserNoteEl) multiUserNoteEl.textContent = `启用失败：${err.message}`;
    return;
  }
  // 后端清空所有 sessions 包含当前 admin token；用刚输入的密码静默重登。
  const ok = await silentReLogin(password);
  if (!ok) {
    clearAuthToken();
    showLoginScreen();
    return;
  }
  await runMainBoot();
}

async function disableMultiUserWizard() {
  if (multiUserNoteEl) multiUserNoteEl.textContent = '';
  const password = await showPasswordPrompt({
    title: '关闭多用户模式',
    hint: '关闭后所有其他用户立即注销，他们的 sessions 与 token 全部清空。请输入管理员密码确认。',
    label1: '管理员密码',
  });
  if (!password) return;
  // Verify password first; same reason as enable — /api/multi-user does not
  // re-check it, and a wrong password would strand the admin on the login
  // page after the toggle wipes sessions.
  try {
    const data = await apiJson('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ user_id: 'default-user', password }),
    });
    setAuthToken(data.token);
  } catch (err) {
    if (multiUserNoteEl) multiUserNoteEl.textContent = `密码错误：${err.message}`;
    return;
  }
  try {
    await apiJson('/api/multi-user', {
      method: 'POST',
      body: JSON.stringify({ enabled: false, password }),
    });
  } catch (err) {
    if (multiUserNoteEl) multiUserNoteEl.textContent = `关闭失败：${err.message}`;
    return;
  }
  // sessions 已被清空；single-user mode 下 admin 仍有密码 → silent re-login 仍走密码校验。
  const ok = await silentReLogin(password);
  if (!ok) {
    clearAuthToken();
    showLoginScreen();
    return;
  }
  await runMainBoot();
}

if (multiUserToggleBtnEl) {
  multiUserToggleBtnEl.addEventListener('click', async () => {
    if (authState.multiUserEnabled) {
      await disableMultiUserWizard();
    } else {
      await enableMultiUserWizard();
    }
  });
}

// ── User management (admin only) ────────────────────────────
const userListContainerEl = document.getElementById('userListContainer');
const createUserBtnEl = document.getElementById('createUserBtn');
const refreshUsersBtnEl = document.getElementById('refreshUsersBtn');
const userManagementNoteEl = document.getElementById('userManagementNote');

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

async function loadUsersList() {
  if (!userListContainerEl) return;
  if (!authState.multiUserEnabled || authState.role !== 'admin') {
    userListContainerEl.innerHTML = '';
    return;
  }
  try {
    const data = await apiJson('/api/users');
      const users = Array.isArray(data.users) ? data.users : [];
      const storage = data.storage || {};
      const storageNote = [
        ...(Array.isArray(storage.orphan_dirs) && storage.orphan_dirs.length ? [`孤儿目录：${storage.orphan_dirs.map(escapeHtml).join(', ')}`] : []),
        ...(Array.isArray(storage.deleted_archives) && storage.deleted_archives.length ? [`已归档删除用户：${storage.deleted_archives.length}`] : []),
      ].join('；');
      userListContainerEl.innerHTML = users.map(user => {
        const roleTag = user.role === 'admin' ? '<span class="user-role-tag admin">管理员</span>' : '<span class="user-role-tag">普通用户</span>';
        const statusTag = user.disabled ? '<span class="user-role-tag">已禁用</span>' : '';
        const created = user.created_at ? new Date(user.created_at * 1000).toLocaleString('zh-CN') : '';
        const userId = escapeHtml(user.user_id);
        const isAdminRow = user.user_id === 'default-user';
        const lifecycleAction = user.disabled
          ? `<button type="button" class="subtle-btn" data-user-action="enable" data-user-id="${userId}">启用</button>`
          : `<button type="button" class="subtle-btn" data-user-action="disable" data-user-id="${userId}">禁用</button>`;
        const actions = isAdminRow
          ? `<button type="button" class="subtle-btn" data-user-action="reset" data-user-id="${userId}">重置密码</button>`
          : `<button type="button" class="subtle-btn" data-user-action="reset" data-user-id="${userId}">重置密码</button>${lifecycleAction}<button type="button" class="subtle-danger" data-user-action="delete" data-user-id="${userId}">归档删除</button>`;
        return `
        <div class="user-list-row">
          <div class="user-meta">
            <span class="user-id">${userId}</span>
            ${roleTag}
            ${statusTag}
            <span class="muted small">${created}</span>
          </div>
          <div class="user-actions">${actions}</div>
        </div>
      `;
      }).join('') + (storageNote ? `<p class="muted small">${storageNote}</p>` : '');
      if (userManagementNoteEl) userManagementNoteEl.textContent = storageNote || '';
  } catch (err) {
    if (userManagementNoteEl) userManagementNoteEl.textContent = `加载失败：${err.message}`;
  }
}

if (userListContainerEl) {
  userListContainerEl.addEventListener('click', async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.getAttribute('data-user-action');
    const userId = target.getAttribute('data-user-id');
    if (!action || !userId) return;
    if (userManagementNoteEl) userManagementNoteEl.textContent = '';
    try {
      if (action === 'delete') {
        if (!window.confirm(`确认归档删除用户 "${userId}"？该用户会从账号列表移除，数据目录会移动到 _system/deleted-users。通常请优先使用“禁用”。`)) return;
        await apiJson('/api/users', {
          method: 'POST',
          body: JSON.stringify({ action: 'delete', user_id: userId }),
        });
      } else if (action === 'disable') {
        if (!window.confirm(`确认禁用用户 "${userId}"？该用户将立即注销，但数据目录会保留。`)) return;
        await apiJson('/api/users', {
          method: 'POST',
          body: JSON.stringify({ action: 'disable', user_id: userId }),
        });
      } else if (action === 'enable') {
        await apiJson('/api/users', {
          method: 'POST',
          body: JSON.stringify({ action: 'enable', user_id: userId }),
        });
      } else if (action === 'reset') {
        const password = await showPasswordPrompt({
          title: `重置 ${userId} 的密码`,
          hint: '请输入至少 12 位的新密码。',
          label1: '新密码',
          label2: '确认新密码',
          requireConfirm: true,
          minLength: 12,
        });
        if (!password) return;
        if (password.length < 12) {
          if (userManagementNoteEl) userManagementNoteEl.textContent = '密码至少需要 12 位';
          return;
        }
        if (userId === 'default-user') {
          await apiJson('/api/users', {
            method: 'POST',
            body: JSON.stringify({ action: 'set_admin_password', password }),
          });
        } else {
          await apiJson('/api/users', {
            method: 'POST',
            body: JSON.stringify({ action: 'reset_password', user_id: userId, password }),
          });
        }
      }
      await loadUsersList();
    } catch (err) {
      if (userManagementNoteEl) userManagementNoteEl.textContent = err.message;
    }
  });
}

if (createUserBtnEl) {
  createUserBtnEl.addEventListener('click', async () => {
    const userId = window.prompt('新用户名（字母/数字/下划线/短横线，1-64 位）');
    if (!userId) return;
    const password = await showPasswordPrompt({
      title: `为 ${userId} 设置初始密码`,
      hint: '请输入至少 12 位的初始密码。',
      label1: '初始密码',
      label2: '确认密码',
      requireConfirm: true,
      minLength: 12,
    });
    if (!password) return;
    if (password.length < 12) {
      if (userManagementNoteEl) userManagementNoteEl.textContent = '密码至少需要 12 位';
      return;
    }
    if (userManagementNoteEl) userManagementNoteEl.textContent = '';
    try {
      await apiJson('/api/users', {
        method: 'POST',
        body: JSON.stringify({ action: 'create', user_id: userId, password }),
      });
      await loadUsersList();
    } catch (err) {
      if (userManagementNoteEl) userManagementNoteEl.textContent = err.message;
    }
  });
}

if (refreshUsersBtnEl) {
  refreshUsersBtnEl.addEventListener('click', () => loadUsersList());
}

// 切到"账号"tab 时刷新多用户状态与用户列表（仅 admin 看得到这两个 section）
document.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (!target.matches('.settings-tab-btn')) return;
  const tab = target.getAttribute('data-tab');
  if (tab === 'account') {
    renderMultiUserStatus();
    if (authState.role === 'admin' && authState.multiUserEnabled) {
      loadUsersList();
    }
  }
});

// Character Carousel Controls
const charCarouselPrev = document.getElementById('charCarouselPrev');
const charCarouselNext = document.getElementById('charCarouselNext');

if (charCarouselPrev && characterManageGrid) {
  charCarouselPrev.addEventListener('click', () => {
    characterManageGrid.scrollBy({ left: -300, behavior: 'smooth' });
  });
}
if (charCarouselNext && characterManageGrid) {
  charCarouselNext.addEventListener('click', () => {
    characterManageGrid.scrollBy({ left: 300, behavior: 'smooth' });
  });
}
