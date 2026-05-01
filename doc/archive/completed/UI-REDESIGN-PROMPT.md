# Threadloom UI Redesign Prompt

你是一个高级前端设计师 + 资深前端工程师。请直接帮我重构这个 Web UI 的视觉与结构，但不要破坏现有功能。

## 项目背景

- 这是一个中文网页应用，名字叫 `Threadloom`
- 左侧是聊天区
- 右侧是状态区
- 顶部有 session / settings / character card 相关入口
- 设置面板里有模型配置、角色卡导入、聊天记录导入
- 现有 UI 主要问题是：太丑、太像原型、层次混乱、质感弱、排版普通、没有沉浸感

## 目标

- 做成“高级、克制、有设计感、适合中文 RP 产品”的界面
- 风格要有沉浸感，避免 AI 味模板化 UI
- 桌面端和移动端都要能正常使用
- 保留现有 DOM id，尽量不要改 JS 依赖的元素 id
- 可以调整结构层级、补 class、补包装容器
- 可以重写 CSS
- 如果必须改 JS，只做最小必要改动，并明确列出原因
- 不要删除任何已有功能区块
- 不要引入框架
- 不要依赖构建工具
- 不要引入新的外部 npm 包
- 允许继续使用原生 HTML/CSS/JS
- 保持和当前文件兼容，输出可直接替换的代码

## 设计要求

- 整体视觉更精致，不要“后台管理面板风”
- 更像“叙事工具 / 活的手稿 / 沉浸式角色扮演界面”
- 信息密度要可控，重点清楚
- 聊天区必须舒服、耐看、易读
- 状态区必须更有层次，但不要喧宾夺主
- 桌面端状态面板采用右侧抽屉，作为“旁注 / GM 面板”，不要压缩正文纵向阅读空间
- 移动端状态面板保留底部弹层，避免窄屏右侧抽屉挤压内容
- 移动端隐藏 header，主要控制入口收进输入区底部控制行
- 移动端输入框保持低高度，优先给聊天记录让出空间
- 移动端底部控制行尽量同时容纳：状态提示、session 管理、状态面板、设置入口；放不下时 session 管理使用图标按钮
- 设置面板要更清晰，像真正可用的产品，而不是调试面板
- 字体、边框、留白、卡片层次、交互反馈都要重新整理
- 深浅关系、hover、focus、移动端布局都要考虑
- 避免过度花哨，但也不要平庸

## 功能约束

现有这些 id 尽量保留并继续可用：

```text
messages
state
npcSection
objectThreadSection
entityDetail
debugDetail
composer
input
regenerateBtn
statusBar
debugPanel
stateColumn
mobileStateToggle
settingsBtn
settingsPanel
settingsBackdrop
settingsCloseBtn
sessionIndicator
sessionIndicatorLabel
characterScope
characterSelect
characterSubtitle
characterCover
characterCoverFallback
sessionDockPanel
sessionDockList
historyToolbar
loadEarlierBtn
saveModelConfigBtn
narratorModelSelect
stateKeeperModelSelect
siteBaseUrlInput
siteApiTypeSelect
siteApiKeyInput
saveSiteConfigBtn
discoverSiteModelsBtn
siteStatusNote
modelConfigNote
characterImportFileInput
characterImportNameInput
importCharacterBtn
characterImportNote
characterProfileDraftPanel
characterProfileDraftInput
saveCharacterProfileDraftBtn
skipCharacterProfileDraftBtn
characterProfileDraftNote
chatImportFileInput
chatImportPreviewBtn
chatImportBtn
chatImportPreview
chatImportNote
```

## 输出要求

- 先简短说明你的设计方向
- 然后直接输出完整可替换的：
  1. `index.html`
  2. `styles.css`
- 如果你认为 `app.js` 必须改，再单独输出最小改动版 `app.js`，并说明只改了哪些地方
- 不要只给思路，要给完整代码

## 重要限制

- 不要删除任何现有功能模块
- 不要重命名已有关键 id
- 不要把设置面板里的导入区、模型区、站点配置区删掉
- 不要把右侧状态区做成装饰品
- 不要把聊天消息结构改到现有 JS 无法工作

## 建议输入文件

第一轮优先给它：

1. `frontend/index.html`
2. `frontend/styles.css`

如果它明确说需要联动，再补：

3. `frontend/app.js`

## 推荐执行方式

- 第一轮只让它改 `index.html` 和 `styles.css`
- 尽量不要让它动 `app.js`
- 这样复制回项目时最稳
