# Threadloom v0.3 Frontend Audit Report

**Date:** 2026-04-15  
**Files Audited:**
- `/root/Threadloom/frontend/index.html`
- `/root/Threadloom/frontend/app.js`
- `/root/Threadloom/frontend/styles.css`
- `/root/Threadloom/stitch.html`
- `/root/Threadloom/stitch-index.html`
- `/root/Threadloom/stitch-dashbord.html`

---

## CRITICAL — Security Holes, Data Loss Risks

### C1. XSS via `marked.parse()` on Server-Supplied Content (app.js:560)
**File:** `frontend/app.js`, `renderMarkdown()` function (line 560)  
**Issue:** `marked.parse(text, { breaks: true, gfm: true })` is called on assistant message content and the result is assigned via `innerHTML` (line 532). The `marked` library does **not** sanitize HTML by default — it passes through raw `<script>`, `<img onerror>`, `<a href="javascript:">`, etc. If the LLM or a compromised backend injects malicious HTML/JS, it will execute in the user's browser.  
**Suggested Fix:** Integrate DOMPurify (or use `marked`'s `sanitize` option / a custom `renderer` that escapes dangerous tags). Example: `body.innerHTML = DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));`. The CSP `script-src` policy mitigates inline scripts but does NOT block `<img onerror>`, `<iframe>`, DOM-clobbering, or CSS injection attacks.

### C2. XSS via Unsanitized State Data in `innerHTML` Template Literals (app.js:648, 653, 661)
**File:** `frontend/app.js`, `renderState()` function  
**Issue:** Three locations use `innerHTML` with string interpolation of server-supplied data:
- Line 648: `` `<strong>主要事件</strong><span>${mainThread.label}</span>` ``
- Line 653: `` `<strong>主要事件</strong><span>${state.main_event}</span>` ``
- Line 661: `` `<strong>关键人物</strong><span>${importantNpcs.slice(0, 4).map(...)...}</span>` ``

If `mainThread.label`, `state.main_event`, or NPC `primary_label`/`name` fields contain `<script>` or event handler attributes, they execute.  
**Suggested Fix:** Use `textContent` assignments or escape HTML entities before interpolation. E.g., create a helper `function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }` and wrap all interpolated values.

### C3. No Session Delete Confirmation (app.js:359)
**File:** `frontend/app.js`, `renderSessionDock()` delete button handler  
**Issue:** Clicking the delete (skull) button immediately sends a `DELETE` request with no confirmation dialog. This is a **data-loss risk** — a misclick permanently destroys a session's history.  
**Suggested Fix:** Add `if (!confirm('确定要删除此会话？此操作不可撤销。')) return;` before the delete call.

---

## HIGH — Significant Bugs Affecting UX or Reliability

### H1. Full Message List Re-render on Every Update (app.js:515-550)
**File:** `frontend/app.js`, `renderMessages()`  
**Issue:** `messagesEl.innerHTML = ''` followed by rebuilding every message DOM node runs on every message send, history load, and pending-message display. With hundreds of messages this causes visible flicker, layout thrash, and wasted CPU. Each re-render also re-parses markdown for all assistant messages.  
**Suggested Fix:** Use incremental DOM updates — append only new messages, or use a keyed virtual list. At minimum, cache rendered markdown output.

### H2. No Error Handling for Concurrent Async Operations / Race Conditions (app.js:1073-1120)
**File:** `frontend/app.js`, submit handler  
**Issue:** The submit button is disabled during send, but nothing prevents rapid double-submits via Enter key (the `keydown` handler at line 1123 calls `requestSubmit()` without checking `isWaitingForResponse`). If two submits fire before the first response arrives, `pendingUserMessage` gets overwritten and the UI state becomes inconsistent. Additionally, `loadHistory()` + `renderState()` calls after response can race with a simultaneous character switch or session switch.  
**Suggested Fix:** Guard the keydown submit with `if (isWaitingForResponse) return;`. Consider adding a request ID / cancellation token for in-flight API calls when sessions switch.

### H3. `loadEarlierHistory()` Scroll Position Restoration Is Fragile (app.js:849-887)
**File:** `frontend/app.js`, `loadEarlierHistory()`  
**Issue:** The function reads `messagesEl.scrollHeight` before the fetch, then after re-rendering uses `requestAnimationFrame` to set `scrollTop = nextHeight - previousHeight`. However, `renderMessages()` is called which does `messagesEl.innerHTML = ''` (destroying all nodes) then rebuilds everything. Between the innerHTML clear and the rAF callback, the browser may have already painted a blank state, causing a visible flash. Also, if images in messages haven't loaded, heights will shift after the rAF.  
**Suggested Fix:** Use a prepend-based approach that doesn't destroy existing DOM. Or apply `overflow: hidden` temporarily during the swap to prevent flash.

### H4. No WebSocket / Real-Time Communication (app.js)
**File:** `frontend/app.js` (entire file)  
**Issue:** The app uses pure HTTP request/response for all communication. The typing indicator (`showTypingIndicator`) is shown after sending but before the HTTP response, which means for long-running LLM generations the user sees a static "thinking" animation with no progress feedback and no streaming. If the server supports streaming responses, the frontend cannot consume them.  
**Suggested Fix:** If streaming is desired, implement SSE (`EventSource`) or WebSocket. Note the CSP `connect-src: 'self'` would need to be updated to include `wss:` for WebSocket.

### H5. `importCharacterCard()` Loads Entire File into Memory as String (app.js:1017-1040)
**File:** `frontend/app.js`, `importCharacterCard()`  
**Issue:** The function reads the file with `file.arrayBuffer()`, then converts byte-by-byte to a string via `String.fromCharCode(byte)` in a loop, then `btoa()`. For large character card PNGs (>5MB), this creates a huge intermediate string and can freeze the UI thread. The byte loop is also O(n) string concatenation (quadratic in many engines).  
**Suggested Fix:** Use `FileReader.readAsDataURL()` for base64 encoding, or use chunked array processing. At minimum, build the binary string with array join: `binary = Array.from(bytes, b => String.fromCharCode(b)).join('')`.

### H6. Session Dock Click-Outside Handler Doesn't Account for Touch Events (app.js:1156)
**File:** `frontend/app.js`, document click handler  
**Issue:** The click-outside-to-close handler for the session dock uses `document.addEventListener('click', ...)`. On mobile Safari, `click` events don't bubble from all elements. Touch users may not be able to dismiss the dock by tapping outside.  
**Suggested Fix:** Add a `touchend` listener or use `pointerdown` instead of `click`.

---

## MEDIUM — Code Quality, Missing Validation, Edge Cases

### M1. `setSelectOptions()` Uses `innerHTML = ''` to Clear Options (app.js:230)
**File:** `frontend/app.js`, `setSelectOptions()`  
**Issue:** Using `innerHTML = ''` to clear a `<select>` works but is slower than iterating and removing children, and bypasses any future event cleanup. Minor issue but contributes to the innerHTML-heavy pattern.  
**Suggested Fix:** Use `while (selectEl.firstChild) selectEl.removeChild(selectEl.firstChild);` or `selectEl.replaceChildren();`.

### M2. No Debounce on Scroll Listener (app.js:1140)
**File:** `frontend/app.js`, scroll handler on `messagesEl`  
**Issue:** `messagesEl.addEventListener('scroll', () => { shouldStickToBottom = isNearBottom(); });` fires on every scroll event (potentially 60+ times/second). While the callback is lightweight, it still reads `scrollHeight`, `scrollTop`, and `clientHeight` on each frame, which can trigger forced layout reflow.  
**Suggested Fix:** Wrap in a `requestAnimationFrame` guard or passive scroll listener: `{ passive: true }`.

### M3. `scrollToLatest()` Fires 3 Nested `requestAnimationFrame` Callbacks (app.js:587-597)
**File:** `frontend/app.js`, `scrollToLatest()`  
**Issue:** The function queues 3 rAF frames to force-scroll. This is a workaround for timing issues but is fragile and wastes frames. It also always scrolls even when content hasn't changed.  
**Suggested Fix:** Use `MutationObserver` on `messagesEl` to detect content changes and scroll once, or use `ResizeObserver`.

### M4. Event Listeners Accumulate in `renderSessionDock()` (app.js:324-392)
**File:** `frontend/app.js`, `renderSessionDock()`  
**Issue:** Each call to `renderSessionDock()` clears the dock list with `innerHTML = ''` and creates new DOM nodes with fresh `addEventListener` calls. The old handlers are GC'd with the old nodes (no leak per se), but this pattern runs on every session switch, delete, or new game. If the dock is rendered frequently, this creates unnecessary GC pressure.  
**Suggested Fix:** Consider event delegation — attach one listener on `sessionDockList` and use `e.target.closest()` to identify which button was clicked.

### M5. API Key Sent in JSON Body, Not Validated Client-Side (app.js:455)
**File:** `frontend/app.js`, `saveSiteConfig()`  
**Issue:** The raw API key is sent as `apiKey` in a JSON POST body over the same origin. While this avoids exposing it in URLs, the `siteApiKeyInput` field has `type="password"` which is good, but there's no client-side validation that the key isn't accidentally an empty string when `replace_api_key` is true.  
**Suggested Fix:** Validate: `if (draft.replace_api_key && !draft.apiKey) { error('API Key 不能为空'); return; }`

### M6. `coverLoadToken` Pattern Is Correct But Image `onload`/`onerror` Are Never Cleaned Up (app.js:162-199)
**File:** `frontend/app.js`, `renderCharacterCard()`  
**Issue:** `characterCoverEl.onload` and `characterCoverEl.onerror` are reassigned on each call. While the token check prevents stale callbacks from acting, the old handlers remain referenced until overwritten. This is a minor memory concern.  
**Suggested Fix:** Acceptable as-is; just noting the pattern.

### M7. `loadEntity()` Doesn't Use `apiJson()` Helper (app.js:1062-1069)
**File:** `frontend/app.js`, `loadEntity()`  
**Issue:** This function uses raw `fetch()` + manual `.json()` instead of the `apiJson()` helper used everywhere else. Error handling is inconsistent — on failure, it dumps the raw JSON error into `entityEl.textContent` rather than showing a user-friendly message.  
**Suggested Fix:** Use `apiJson()` and wrap in try/catch with a user-friendly error message.

### M8. `regenerateLast()` Has No Guard Against Double-Click (app.js:1130-1138)
**File:** `frontend/app.js`, regenerate button handler  
**Issue:** The regenerate button is shown/hidden based on `debug.completion_status === 'partial'`, but nothing prevents clicking it multiple times rapidly.  
**Suggested Fix:** Disable the button during the operation, re-enable on completion.

### M9. HTML Language Set to `zh-CN` but Content Is Mixed Chinese/English (index.html:2)
**File:** `frontend/index.html`, line 2  
**Issue:** `<html lang="zh-CN">` declares the page as Chinese, but the app contains significant English content (UI labels like "Character Card", "Player", "World", "Config"). This affects screen reader pronunciation.  
**Suggested Fix:** Consider `lang="zh"` or use `lang` attributes on specific English-text elements.

### M10. Missing `<meta name="description">` and `<meta name="robots">` (index.html)
**File:** `frontend/index.html`  
**Issue:** No description meta tag. Minor for an app, but affects SEO and link previews if the app is publicly accessible.  
**Suggested Fix:** Add `<meta name="description" content="Threadloom — The Living Manuscript">`.

### M11. Fallback Markdown Renderer Only Escapes `<` and `>` (app.js:562)
**File:** `frontend/app.js`, `renderMarkdown()` fallback  
**Issue:** When `marked` is not loaded, the fallback does `text.replace(/</g, '&lt;').replace(/>/g, '&gt;')`. This doesn't escape `&` or `"` which could lead to attribute injection if the result were placed in an attribute context. Currently it's only used in `innerHTML` of a `<div>`, so the risk is low.  
**Suggested Fix:** Also escape `&` → `&amp;` for correctness.

### M12. `deleteBtn.innerHTML` Uses Unescaped HTML String (app.js:358)
**File:** `frontend/app.js`, line 358  
**Issue:** `deleteBtn.innerHTML = '<span class="material-symbols-outlined">skull</span>';` — this is a static string with no user input, so it's safe, but it contributes to the innerHTML usage pattern. Using `textContent` with a `<span>` created via `document.createElement` would be more consistent.  
**Suggested Fix:** Low priority; refactor if doing a broader innerHTML cleanup.

---

## LOW — Style Issues, Minor Improvements

### L1. Stitch Files Are Legacy/Design Mockups — Not Connected to App (stitch-*.html)
**File:** `stitch.html`, `stitch-index.html`, `stitch-dashbord.html`  
**Issue:** All three stitch files are standalone HTML mockups using Tailwind CDN (`cdn.tailwindcss.com`), inline styles, external Google-hosted images, and hardcoded content. They are **not referenced** by the actual frontend (`index.html`/`app.js`), have no JavaScript interactivity, and appear to be design exploration prototypes. `stitch-dashbord.html` has a typo in the filename ("dashbord" → "dashboard"). These files load external images from `lh3.googleusercontent.com` and use the Tailwind CDN — they would fail under the main app's CSP.  
**Suggested Fix:** Archive or remove these files. They add confusion and are dead code. If kept for reference, move them to a `doc/design-mockups/` directory.

### L2. No `favicon.ico` Fallback (index.html)
**File:** `frontend/index.html`  
**Issue:** The page specifies `favicon.svg` only. Older browsers and some bookmark tools look for `favicon.ico`.  
**Suggested Fix:** Add a `favicon.ico` fallback or accept the limitation.

### L3. CSS `:has()` Selector Used (styles.css, line ~69)
**File:** `frontend/styles.css`  
**Issue:** `.app:has(.state-column[hidden])` uses the `:has()` pseudo-class. This is well-supported in modern browsers (Chrome 105+, Safari 15.4+, Firefox 121+) but will silently fail in older browsers, leaving the layout in a two-column state even when the state panel is hidden.  
**Suggested Fix:** Acceptable for modern-browser-only apps. Add a JS fallback if wider support is needed.

### L4. No `aria-live` Region for Status Bar (index.html)
**File:** `frontend/index.html`, `#statusBar`  
**Issue:** The status bar updates dynamically (e.g., "发送中...", "已更新", "错误：...") but has no `aria-live` attribute, so screen readers won't announce status changes.  
**Suggested Fix:** Add `aria-live="polite"` to the status bar element.

### L5. Messages Section Has No `aria-label` or Landmark Role (index.html)
**File:** `frontend/index.html`, `<section id="messages">`  
**Issue:** The main chat area is a `<section>` with no accessible name. Screen readers can't distinguish it from other sections.  
**Suggested Fix:** Add `aria-label="聊天消息"` or `role="log"` to the messages section.

### L6. Composer Submit Button Has Generic Label (index.html)
**File:** `frontend/index.html`  
**Issue:** The submit button text is "发送" which is fine visually, but the textarea lacks an associated `<label>` element (only has a `placeholder`).  
**Suggested Fix:** Add a visually-hidden `<label for="input">` element.

### L7. Responsive Design: State Column Disappears Entirely on Mobile (styles.css, @media max-width: 1024px)
**File:** `frontend/styles.css`, line ~639  
**Issue:** At ≤1024px, `.state-column { display: none; }` completely hides the state sidebar. There's no mobile-friendly alternative to view state, NPC details, or debug info.  
**Suggested Fix:** Consider a toggle/drawer mechanism for mobile users to access the state panel.

### L8. Inconsistent Button Styling Approach (styles.css)
**File:** `frontend/styles.css`  
**Issue:** The global `button` rule sets `background: var(--primary); color: #fff;` which affects ALL buttons including NPC links, dock items, and settings buttons. Many button variants then override this. A more maintainable approach would use a `.btn-primary` class.  
**Suggested Fix:** Refactor to opt-in button styles instead of global override.

### L9. `focusLatestAssistant()` Is Just an Alias for `scrollToLatest()` (app.js:603)
**File:** `frontend/app.js`  
**Issue:** `function focusLatestAssistant(options = {}) { scrollToLatest(options); }` — this function adds no behavior over `scrollToLatest`. It's called in 4 places. This is dead indirection.  
**Suggested Fix:** Replace all calls with `scrollToLatest()` directly, or add the intended "focus" behavior (e.g., keyboard focus for accessibility).

### L10. No `<noscript>` Fallback (index.html)
**File:** `frontend/index.html`  
**Issue:** If JavaScript is disabled or fails to load, the user sees an empty page with no explanation.  
**Suggested Fix:** Add `<noscript><p>此应用需要启用 JavaScript。</p></noscript>`.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3     |
| HIGH     | 6     |
| MEDIUM   | 12    |
| LOW      | 10    |

**Top Priority Actions:**
1. **Sanitize all `innerHTML` assignments** that involve server/LLM data (C1, C2) — integrate DOMPurify or escape HTML.
2. **Add session delete confirmation** (C3) to prevent accidental data loss.
3. **Guard Enter-key double-submit** (H2) with `isWaitingForResponse` check.
4. **Optimize file import** (H5) to avoid UI freeze on large files.
5. **Consider archiving stitch-*.html** (L1) — they are unused design mockups.
