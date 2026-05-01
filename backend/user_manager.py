#!/usr/bin/env python3
"""多用户管理模块：用户增删查、密码验证、会话令牌管理。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

import bcrypt

from paths import (
    RUNTIME_DATA_ROOT,
    DEFAULT_USER_ID,
    ensure_user_root,
    normalize_user_id,
)

logger = logging.getLogger(__name__)

USERS_FILE = RUNTIME_DATA_ROOT / '_system' / 'users.json'
SESSIONS_FILE = RUNTIME_DATA_ROOT / '_system' / 'sessions.json'
TOKEN_TTL = 7 * 24 * 3600  # 7 天
MIN_PASSWORD_LENGTH = 12
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
# Pre-computed bcrypt hash of a random throwaway value, used to keep the
# response time of "user not found" comparable to "wrong password" so login
# cannot be turned into a username oracle. Generated with bcrypt.gensalt(12).
_DUMMY_PASSWORD_HASH = (
    '$2b$12$0gOqcL9nz3HQfq3r81T2lePot0ufLfYOkH9N6ip5TwjFxXMP5Z5UC'
)
_SYSTEM_FILE_LOCK = threading.RLock()


# ── 内部辅助 ──────────────────────────────────────────────

def _ensure_system_dir() -> None:
    (RUNTIME_DATA_ROOT / '_system').mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: dict) -> None:
    """原子写入 JSON：先写临时文件再 rename，防止竞态损坏。"""
    with _SYSTEM_FILE_LOCK:
        _ensure_system_dir()
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, str(path))
            os.chmod(path, 0o600)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _load_users() -> dict:
    with _SYSTEM_FILE_LOCK:
        if USERS_FILE.exists():
            return json.loads(USERS_FILE.read_text('utf-8'))
        return {}


def _save_users(data: dict) -> None:
    _atomic_write(USERS_FILE, data)


def _load_sessions() -> dict:
    with _SYSTEM_FILE_LOCK:
        if SESSIONS_FILE.exists():
            return json.loads(SESSIONS_FILE.read_text('utf-8'))
        return {}


def _prune_expired_sessions(sessions: dict) -> dict:
    """Drop entries whose absolute TTL has passed.

    Called inline before every persistent write so sessions.json does not
    grow unboundedly with abandoned but never-revisited tokens.
    """
    if not isinstance(sessions, dict):
        return {}
    now = time.time()
    cleaned: dict = {}
    for key, entry in sessions.items():
        if not isinstance(entry, dict):
            continue
        try:
            expires_at = float(entry.get('expires_at') or 0)
            created_at = float(entry.get('created_at') or 0)
        except (TypeError, ValueError):
            continue
        if expires_at <= now or now - created_at > TOKEN_TTL:
            continue
        cleaned[key] = entry
    return cleaned


def _save_sessions(data: dict) -> None:
    _atomic_write(SESSIONS_FILE, _prune_expired_sessions(data))


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('ascii')


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('ascii'))
    except Exception as e:
        logger.warning('密码验证异常: %s', e)
        return False


def _validate_user_id(user_id: str) -> str:
    try:
        return normalize_user_id(user_id)
    except ValueError as err:
        raise ValueError('用户名只允许字母、数字、下划线、短横线，1-64 字符') from err


def _validate_password(password: str) -> str:
    value = str(password or '')
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'密码至少需要 {MIN_PASSWORD_LENGTH} 个字符')
    if not value.strip():
        raise ValueError('密码必须包含至少一个非空白字符')
    return value


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


# ── 多用户开关 ────────────────────────────────────────────

def is_multi_user_enabled() -> bool:
    """检查是否启用了多用户模式（读 default-user 的 site.json）。"""
    site_json = RUNTIME_DATA_ROOT / DEFAULT_USER_ID / 'config' / 'site.json'
    if site_json.exists():
        try:
            cfg = json.loads(site_json.read_text('utf-8'))
            return bool(cfg.get('multi_user_enabled', False))
        except Exception as e:
            logger.warning('读取多用户配置失败: %s', e)
    return False


def set_multi_user_enabled(enabled: bool) -> None:
    with _SYSTEM_FILE_LOCK:
        ensure_admin_exists()
        users = _load_users()
        if enabled and not users.get(DEFAULT_USER_ID, {}).get('password_hash'):
            raise ValueError('启用多用户前必须先设置管理员密码')
        site_json = RUNTIME_DATA_ROOT / DEFAULT_USER_ID / 'config' / 'site.json'
        cfg = {}
        if site_json.exists():
            try:
                cfg = json.loads(site_json.read_text('utf-8'))
            except Exception:
                pass
        cfg['multi_user_enabled'] = enabled
        site_json.parent.mkdir(parents=True, exist_ok=True)
        site_json.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), 'utf-8')
        # Wipe sessions on every transition. Disabling needs a clean slate so
        # multi-user-issued tokens cannot survive into single-user mode; enabling
        # is what closes the bootstrap window where default-user could log in
        # with an empty password and carry that token into multi-user state.
        _save_sessions({})


# ── 用户管理 ──────────────────────────────────────────────

def ensure_admin_exists() -> None:
    """确保管理员用户 (default-user) 存在于用户列表中。"""
    with _SYSTEM_FILE_LOCK:
        users = _load_users()
        if DEFAULT_USER_ID not in users:
            users[DEFAULT_USER_ID] = {
                'role': 'admin',
                'password_hash': '',
                'created_at': time.time(),
            }
            _save_users(users)


def create_user(user_id: str, password: str, role: str = 'user') -> dict:
    uid = _validate_user_id(user_id)
    pwd = _validate_password(password)
    if uid == DEFAULT_USER_ID:
        raise ValueError('不能创建与管理员同名的用户')
    with _SYSTEM_FILE_LOCK:
        users = _load_users()
        if uid in users:
            raise ValueError(f'用户 "{uid}" 已存在')
        users[uid] = {
            'role': role,
            'password_hash': _hash_password(pwd),
            'created_at': time.time(),
        }
        _save_users(users)
    ensure_user_root(uid)
    return {'user_id': uid, 'role': role}


def delete_user(user_id: str) -> None:
    uid = _validate_user_id(user_id)
    if uid == DEFAULT_USER_ID:
        raise ValueError('不能删除管理员用户')
    with _SYSTEM_FILE_LOCK:
        users = _load_users()
        if uid not in users:
            raise ValueError(f'用户 "{uid}" 不存在')
        del users[uid]
        _save_users(users)
        # 清除该用户的所有登录令牌
        sessions = _load_sessions()
        sessions = {k: v for k, v in sessions.items() if v.get('user_id') != uid}
        _save_sessions(sessions)


def list_users() -> list[dict]:
    with _SYSTEM_FILE_LOCK:
        ensure_admin_exists()
        users = _load_users()
        return [
            {
                'user_id': uid,
                'role': info.get('role', 'user'),
                'created_at': info.get('created_at', 0),
                'has_password': bool(info.get('password_hash')),
            }
            for uid, info in users.items()
        ]


def admin_has_password() -> bool:
    with _SYSTEM_FILE_LOCK:
        ensure_admin_exists()
        users = _load_users()
        return bool(users.get(DEFAULT_USER_ID, {}).get('password_hash'))


def reset_user_password(user_id: str, password: str) -> None:
    uid = _validate_user_id(user_id)
    if uid == DEFAULT_USER_ID:
        raise ValueError('请使用 set_admin_password 更新管理员密码')
    pwd = _validate_password(password)
    with _SYSTEM_FILE_LOCK:
        users = _load_users()
        if uid not in users:
            raise ValueError(f'用户 "{uid}" 不存在')
        users[uid]['password_hash'] = _hash_password(pwd)
        users[uid]['failed_logins'] = 0
        users[uid]['lockout_until'] = 0
        _save_users(users)
        sessions = _load_sessions()
        sessions = {k: v for k, v in sessions.items() if v.get('user_id') != uid}
        _save_sessions(sessions)


def set_admin_password(password: str) -> None:
    """设置/更新管理员密码。"""
    pwd = _validate_password(password)
    with _SYSTEM_FILE_LOCK:
        ensure_admin_exists()
        users = _load_users()
        users[DEFAULT_USER_ID]['password_hash'] = _hash_password(pwd)
        users[DEFAULT_USER_ID]['failed_logins'] = 0
        users[DEFAULT_USER_ID]['lockout_until'] = 0
        _save_users(users)
        sessions = _load_sessions()
        sessions = {k: v for k, v in sessions.items() if v.get('user_id') != DEFAULT_USER_ID}
        _save_sessions(sessions)


def change_own_password(user_id: str, old_password: str, new_password: str, *, keep_token: str | None = None) -> None:
    """Authenticated self-service password change.

    The caller is the user changing *their own* password — verified via
    ``old_password``. ``keep_token`` (if provided) keeps that single token
    alive while every other session belonging to this user is revoked, so a
    password change on one device kicks everyone else out.
    """
    uid = _validate_user_id(user_id)
    pwd = _validate_password(new_password)
    with _SYSTEM_FILE_LOCK:
        users = _load_users()
        user = users.get(uid)
        if not isinstance(user, dict):
            # Should not happen for an authenticated request, but stay
            # constant-time anyway.
            _verify_password(old_password, _DUMMY_PASSWORD_HASH)
            raise ValueError('用户不存在或密码错误')
        pw_hash = user.get('password_hash', '')
        if not pw_hash:
            # default-user without a password is only valid in single-user
            # mode; the caller passes empty old_password.
            if uid == DEFAULT_USER_ID and not old_password and not is_multi_user_enabled():
                pass
            else:
                _verify_password(old_password, _DUMMY_PASSWORD_HASH)
                raise ValueError('用户不存在或密码错误')
        else:
            if not _verify_password(old_password, pw_hash):
                raise ValueError('用户不存在或密码错误')

        user['password_hash'] = _hash_password(pwd)
        user['failed_logins'] = 0
        user['lockout_until'] = 0
        users[uid] = user
        _save_users(users)

        sessions = _load_sessions()
        keep_key = _hash_token(keep_token) if keep_token else None
        sessions = {
            k: v for k, v in sessions.items()
            if v.get('user_id') != uid or k == keep_key
        }
        _save_sessions(sessions)


# ── 认证 ──────────────────────────────────────────────────

def login(user_id: str, password: str) -> str:
    """验证密码，返回会话令牌。"""
    uid = _validate_user_id(user_id)
    with _SYSTEM_FILE_LOCK:
        users = _load_users()
        user = users.get(uid)
        now = time.time()
        # Lockout window applies before the bcrypt path so an attacker cannot
        # use the slow comparison itself as a workload check.
        if isinstance(user, dict):
            lockout_until = float(user.get('lockout_until') or 0)
            if lockout_until > now:
                logger.warning('login blocked for %s, lockout active for %.0fs', uid, lockout_until - now)
                raise ValueError('账户暂时锁定，请稍后再试')
        # Always run bcrypt against *some* hash so the response time of an
        # unknown user matches the response time of a known user with a wrong
        # password. The dummy hash never matches a real password.
        pw_hash = user.get('password_hash', '') if isinstance(user, dict) else ''
        password_ok = False
        if user is None:
            _verify_password(password, _DUMMY_PASSWORD_HASH)
        elif not pw_hash:
            if uid == DEFAULT_USER_ID and not password and not is_multi_user_enabled():
                password_ok = True
            else:
                _verify_password(password, _DUMMY_PASSWORD_HASH)
        else:
            password_ok = _verify_password(password, pw_hash)

        if not password_ok:
            if isinstance(user, dict):
                failed = int(user.get('failed_logins') or 0) + 1
                user['failed_logins'] = failed
                if failed >= LOGIN_FAILURE_LIMIT:
                    user['lockout_until'] = now + LOGIN_LOCKOUT_SECONDS
                    user['failed_logins'] = 0
                    logger.warning('login lockout engaged for %s after %d failed attempts', uid, failed)
                users[uid] = user
                _save_users(users)
            raise ValueError('用户不存在或密码错误')

        if isinstance(user, dict) and (user.get('failed_logins') or user.get('lockout_until')):
            user['failed_logins'] = 0
            user['lockout_until'] = 0
            users[uid] = user
            _save_users(users)

        token = secrets.token_urlsafe(32)
        sessions = _load_sessions()
        sessions[_hash_token(token)] = {
            'user_id': uid,
            'created_at': now,
            'last_seen_at': now,
            'expires_at': now + TOKEN_TTL,
        }
        _save_sessions(sessions)
    return token


def logout(token: str) -> None:
    with _SYSTEM_FILE_LOCK:
        sessions = _load_sessions()
        sessions.pop(_hash_token(token), None)
        _save_sessions(sessions)


def validate_token(token: str) -> str | None:
    """验证令牌，返回 user_id 或 None。"""
    if not token:
        return None
    with _SYSTEM_FILE_LOCK:
        sessions = _load_sessions()
        token_key = _hash_token(token)
        entry = sessions.get(token_key)
        if not entry:
            legacy_entry = sessions.pop(token, None)
            if isinstance(legacy_entry, dict):
                sessions[token_key] = legacy_entry
                entry = legacy_entry
                _save_sessions(sessions)
        if not entry:
            return None
        now = time.time()
        expires_at = float(entry.get('expires_at') or 0)
        created_at = float(entry.get('created_at') or 0)
        if expires_at <= now or now - created_at > TOKEN_TTL:
            del sessions[token_key]
            _save_sessions(sessions)
            return None
        entry['last_seen_at'] = now
        sessions[token_key] = entry
        _save_sessions(sessions)
        return entry['user_id']


def resolve_user_from_request(headers: dict, *, allow_cookie: bool = True) -> str | None:
    """从请求头提取当前用户。

    - 多用户关闭时：返回 default-user（单用户产品面兼容）
    - 多用户开启时：仅在令牌有效时返回对应 user_id；否则返回 None

    ``allow_cookie`` 默认 True 仅供 GET / EventSource 等无法定制 header 的场景；
    state-changing 请求 (POST/DELETE/PUT) 应传 ``allow_cookie=False``，强制
    Bearer 头，以避免浏览器自动附 Cookie 触发 CSRF。
    """
    if not is_multi_user_enabled():
        return DEFAULT_USER_ID
    token = ''
    auth = headers.get('Authorization', headers.get('authorization', ''))
    if auth.startswith('Bearer '):
        token = auth[7:]
    if not token and allow_cookie:
        cookie = headers.get('Cookie', headers.get('cookie', ''))
        for part in cookie.split(';'):
            part = part.strip()
            if part.startswith('session_token='):
                token = part[len('session_token='):]
                break
    return validate_token(token)
