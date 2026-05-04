const AUTH_TOKEN_KEY = 'tl_session_token';
const loginFormEl = document.getElementById('loginForm');
const loginUserIdEl = document.getElementById('loginUserId');
const loginPasswordEl = document.getElementById('loginPassword');
const loginErrorEl = document.getElementById('loginError');

function setAuthToken(token) {
  try { localStorage.setItem(AUTH_TOKEN_KEY, token); } catch (_e) {}
}

async function login(userId, password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, password }),
  });
  let data = null;
  try { data = await res.json(); } catch (_e) { data = null; }
  if (!res.ok) {
    throw new Error(data?.error?.message || '登录失败');
  }
  return data;
}

loginFormEl?.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (loginErrorEl) loginErrorEl.textContent = '';
  const userId = (loginUserIdEl?.value || '').trim();
  const password = loginPasswordEl?.value || '';
  if (!userId || !password) {
    if (loginErrorEl) loginErrorEl.textContent = '请输入用户名和密码';
    return;
  }
  try {
    const data = await login(userId, password);
    setAuthToken(data.token);
    window.location.reload();
  } catch (err) {
    if (loginErrorEl) loginErrorEl.textContent = err.message || '登录失败';
  }
});

loginUserIdEl?.focus();
