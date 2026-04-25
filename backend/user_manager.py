#!/usr/bin/env python3
"""多用户管理模块：用户增删查、密码验证、会话令牌管理。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

import bcrypt

from paths import (
    RUNTIME_DATA_ROOT,
    DEFAULT_USER_ID,
    ensure_user_root,
)

logger = logging.getLogger(__name__)

USERS_FILE = RUNTIME_DATA_ROOT / '_system' / 'users.json'
SESSIONS_FILE = RUNTIME_DATA_ROOT / '_system' / 'sessions.json'
USER_ID_RE = re.compile(r'^[a-zA-Z0-9_\-\u4e00-\u9fff]{2,32}$')
TOKEN_TTL = 7 * 24 * 3600  # 7 天


# ── 内部辅助 ──────────────────────────────────────────────

def _ensure_system_dir() -> None:
    (RUNTIME_DATA_ROOT / '_system').mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: dict) -> None:
    """原子写入 JSON：先写临时文件再 rename，防止竞态损坏。"""
    _ensure_system_dir()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text('utf-8'))
    return {}


def _save_users(data: dict) -> None:
    _atomic_write(USERS_FILE, data)


def _load_sessions() -> dict:
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text('utf-8'))
    return {}


def _save_sessions(data: dict) -> None:
    _atomic_write(SESSIONS_FILE, data)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('ascii')


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('ascii'))
    except Exception as e:
        logger.warning('密码验证异常: %s', e)
        return False


def _validate_user_id(user_id: str) -> str:
    uid = str(user_id or '').strip()
    if not uid or not USER_ID_RE.fullmatch(uid):
        raise ValueError('用户名只允许字母、数字、下划线、中文，2-32 字符')
    return uid


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


# ── 用户管理 ──────────────────────────────────────────────

def ensure_admin_exists() -> None:
    """确保管理员用户 (default-user) 存在于用户列表中。"""
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
    if uid == DEFAULT_USER_ID:
        raise ValueError('不能创建与管理员同名的用户')
    users = _load_users()
    if uid in users:
        raise ValueError(f'用户 "{uid}" 已存在')
    users[uid] = {
        'role': role,
        'password_hash': _hash_password(password),
        'created_at': time.time(),
    }
    _save_users(users)
    ensure_user_root(uid)
    return {'user_id': uid, 'role': role}


def delete_user(user_id: str) -> None:
    uid = _validate_user_id(user_id)
    if uid == DEFAULT_USER_ID:
        raise ValueError('不能删除管理员用户')
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
    ensure_admin_exists()
    users = _load_users()
    return [
        {'user_id': uid, 'role': info.get('role', 'user'), 'has_password': bool(info.get('password_hash'))}
        for uid, info in users.items()
    ]


def set_admin_password(password: str) -> None:
    """设置/更新管理员密码。"""
    ensure_admin_exists()
    users = _load_users()
    users[DEFAULT_USER_ID]['password_hash'] = _hash_password(password)
    _save_users(users)


# ── 认证 ──────────────────────────────────────────────────

def login(user_id: str, password: str) -> str:
    """验证密码，返回会话令牌。"""
    uid = _validate_user_id(user_id)
    users = _load_users()
    user = users.get(uid)
    if not user:
        raise ValueError('用户不存在或密码错误')
    pw_hash = user.get('password_hash', '')
    if not pw_hash:
        # 管理员未设置密码时允许空密码登录（仅限单用户模式）
        if uid == DEFAULT_USER_ID and not password and not is_multi_user_enabled():
            pass
        elif uid == DEFAULT_USER_ID and not password and is_multi_user_enabled():
            raise ValueError('多用户模式下管理员必须设置密码后才能登录')
        elif password:
            raise ValueError('用户不存在或密码错误')
    else:
        if not _verify_password(password, pw_hash):
            raise ValueError('用户不存在或密码错误')
    token = secrets.token_urlsafe(32)
    sessions = _load_sessions()
    sessions[token] = {'user_id': uid, 'created_at': time.time()}
    _save_sessions(sessions)
    return token


def logout(token: str) -> None:
    sessions = _load_sessions()
    sessions.pop(token, None)
    _save_sessions(sessions)


def validate_token(token: str) -> str | None:
    """验证令牌，返回 user_id 或 None。"""
    if not token:
        return None
    sessions = _load_sessions()
    entry = sessions.get(token)
    if not entry:
        return None
    if time.time() - entry.get('created_at', 0) > TOKEN_TTL:
        del sessions[token]
        _save_sessions(sessions)
        return None
    return entry['user_id']


def resolve_user_from_request(headers: dict) -> str | None:
    """从请求头提取当前用户。

    - 多用户关闭时：返回 default-user（单用户产品面兼容）
    - 多用户开启时：仅在令牌有效时返回对应 user_id；否则返回 None
    """
    if not is_multi_user_enabled():
        return DEFAULT_USER_ID
    token = ''
    auth = headers.get('Authorization', headers.get('authorization', ''))
    if auth.startswith('Bearer '):
        token = auth[7:]
    if not token:
        cookie = headers.get('Cookie', headers.get('cookie', ''))
        for part in cookie.split(';'):
            part = part.strip()
            if part.startswith('session_token='):
                token = part[len('session_token='):]
                break
    return validate_token(token)
