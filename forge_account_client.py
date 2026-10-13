"""Crash Forge Launcher account client. Forge Hub Supabase auth, no new identity silo.

Auth and pairing use HTTPS; GitHub passwords never enter this process. Tokens
are in RAM and the refresh token is persisted only with Windows DPAPI.
"""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SUPABASE = "https://mjvpkerobjgoldmimyxz.supabase.co"
PUBLISHABLE = "sb_publishable_r_LvI1SCEoK0WKd0y--REg_uMbe_930"
BRIDGE = SUPABASE + "/functions/v1/forge-launcher-auth"
WEB_ACCOUNT = "https://carisademon.github.io/Crash-Forge-Racing/forge-hub/account.html"
USERNAME = re.compile(r"^[a-z][a-z0-9_]{2,23}$")
RESERVED = frozenset({
    "admin", "moderator", "support", "official", "system", "forge_hub",
    "crash_forge", "carisademon", "github", "supabase",
})
UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$", re.I)
SHA = re.compile(r"^[a-f0-9]{64}$")
MAX_RESPONSE_BYTES = 128 * 1024


class AccountError(ValueError):
    pass


class AccountSessionExpired(AccountError):
    """Refresh token is invalid/revoked; only a fresh sign-in can replace it."""


class AccountServiceUnavailable(AccountError):
    """Network, rate-limit, or transient backend failure (not sign-out)."""


@contextmanager
def _account_refresh_mutex_disabled():
    yield


@contextmanager
def _account_refresh_mutex(root):
    """Serialize refresh-token rotation across independently launched GUI EXEs."""
    if os.name != "nt":
        yield
        return
    kernel = ctypes.windll.kernel32
    create = kernel.CreateMutexW
    create.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.c_wchar_p]
    create.restype = ctypes.c_void_p
    wait = kernel.WaitForSingleObject
    wait.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    release = kernel.ReleaseMutex
    release.argtypes = [ctypes.c_void_p]
    release.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = wintypes.BOOL
    # Never place a token or a user's path itself in a named kernel object.
    mutex_name = "Local\\CrashForge.Auth." + hashlib.sha256(
        str(Path(root).resolve()).casefold().encode("utf-8")).hexdigest()[:24]
    handle = create(None, False, mutex_name)
    if not handle:
        raise AccountServiceUnavailable("Account session is temporarily busy")
    locked = False
    try:
        result = wait(handle, 35000)
        if result not in (0, 0x80):  # WAIT_OBJECT_0 or WAIT_ABANDONED
            raise AccountServiceUnavailable("Account verification is temporarily busy")
        locked = True
        yield
    finally:
        if locked:
            release(handle)
        close(handle)


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccountError("Authentication server redirected unexpectedly")


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    """OS-bound encryption; secrets never fall back to plaintext storage."""
    if os.name != "nt":
        raise AccountError("Account persistence requires Windows")
    class Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]
    payload = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), payload)
    result = Blob()
    crypto = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    operation = crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    operation.argtypes = (
        [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
         ctypes.POINTER(Blob)]
        if decrypt else
        [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p,
         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
         ctypes.POINTER(Blob)]
    )
    operation.restype = wintypes.BOOL
    try:
        if not operation(ctypes.byref(source), None, None, None, None,
                         0x1, ctypes.byref(result)):
            raise AccountError("Windows could not unlock saved account")
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        if result.pbData:
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            kernel.LocalFree(result.pbData)


def _default_state():
    return Path(os.environ.get("LOCALAPPDATA") or
                (Path.home() / "AppData" / "Local")) / "CrashForgeLauncher" / "accounts"


class AccountClient:
    def __init__(self, root=None, *, persist=True):
        self.root = Path(root) if root else _default_state()
        self.persist = bool(persist)
        self._lock = threading.RLock()
        self._access = ""
        self._refresh = ""
        self._expires_at = 0.0
        self._user = {}
        self._cached_profile = {}  # Display-safe identity, NOT a second token store.
        self._pending = None
        if self.persist:
            self.restore()

    @property
    def signed_in(self):
        return bool(self._refresh or self._access)

    def cached_profile(self):
        """Previous validated public identity, bound to the encrypted session."""
        with self._lock:
            return dict(self._cached_profile) if self.signed_in else {}

    def restore(self):
        path = self.root / "session.dat"
        try:
            if not path.is_file() or path.stat().st_size > 16384:
                return False
            data = json.loads(_dpapi(path.read_bytes(), decrypt=True))
            value = data.get("refresh_token")
            if data.get("schema") != 1 or not isinstance(value, str) or not value:
                return False
            self._refresh = value
            self._access = ""
            self._expires_at = 0
            cached = data.get("profile")
            if isinstance(cached, dict):
                self._cached_profile = {
                    field: str(cached.get(field) or "")[:limit]
                    for field, limit in (("username", 24),
                                         ("display_name", 60),
                                         ("avatar_url", 512))
                    if isinstance(cached.get(field, ""), str)
                }
            return True
        except (OSError, AccountError, ValueError, TypeError, UnicodeError):
            return False

    def _persist(self, *, profile_only=False):
        """Never overwrite a newer encrypted refresh token with stale profile data.

        Two separate EXEs (launcher and editor) may hold valid access tokens at
        the same time. Refresh tokens rotate, so a late avatar/name update from
        the older EXE must not save its *previous* refresh token back to disk.
        Serialize both writers and compare against the latest encrypted token.
        """
        if not self.persist or not self._refresh:
            return
        with _account_refresh_mutex(self.root):
            path = self.root / "session.dat"
            if profile_only:
                try:
                    if not path.is_file() or path.stat().st_size > 16384:
                        return
                    saved = json.loads(_dpapi(path.read_bytes(), decrypt=True))
                    if (saved.get("schema") != 1 or
                            saved.get("refresh_token") != self._refresh):
                        # Another EXE refreshed or replaced the session.
                        # Keep its token and profile; our display cache is local.
                        return
                except (OSError, ValueError, TypeError, AccountError, UnicodeError):
                    return
            data = json.dumps({"schema": 1, "refresh_token": self._refresh,
                               "profile": self._cached_profile},
                              separators=(",", ":")).encode("utf-8")
            encoded = _dpapi(data)
            self.root.mkdir(parents=True, exist_ok=True)
            # A unique temporary name avoids collisions with older launchers.
            tmp = self.root / ("session.dat.tmp." + secrets.token_hex(8))
            try:
                tmp.write_bytes(encoded)
                os.replace(tmp, path)
            finally:
                if tmp.exists():
                    tmp.unlink()

    def _request(self, url: str, payload=None, *, token=None, method="POST", prefer=None):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "mjvpkerobjgoldmimyxz.supabase.co"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.fragment or
                not parsed.path.startswith(("/auth/v1/", "/rest/v1/forge_accounts",
                                            "/functions/v1/forge-launcher-auth",
                                            "/rest/v1/forge_mod_profiles"))):
            raise AccountError("Unexpected authentication endpoint")
        headers = {
            "apikey": PUBLISHABLE,
            "User-Agent": "CrashForgeLauncher/Accounts",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        }
        if token:
            headers["Authorization"] = "Bearer " + str(token)
        if prefer is not None:
            if prefer != "return=representation":
                raise AccountError("Unexpected REST response preference")
            headers["Prefer"] = prefer
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url, data=body, headers=headers, method=method,
        )
        try:
            with urllib.request.build_opener(_RejectRedirects()).open(
                    request, timeout=16) as response:
                if int(response.headers.get("Content-Length", 0) or 0) > MAX_RESPONSE_BYTES:
                    raise AccountError("Server response too large")
                data = response.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise AccountError("Server response too large")
                return json.loads(data.decode("utf-8")) if data.strip() else {}
        except urllib.error.HTTPError as exc:
            try:
                error = json.loads(exc.read(2048).decode("utf-8"))
                message = str(error.get("error_description") or error.get("msg")
                              or error.get("error") or "")
            except (UnicodeError, ValueError, AttributeError):
                message = ""
            is_refresh = (parsed.path == "/auth/v1/token" and
                          urllib.parse.parse_qs(parsed.query).get("grant_type")
                          == ["refresh_token"])
            if is_refresh and exc.code in (400, 401):
                # GoTrue returns HTTP 400 for invalid/rotated refresh tokens.
                # That is NOT a network outage and must never loop forever.
                raise AccountSessionExpired("Forge Hub session expired. Sign in again.") from None
            if exc.code == 401:
                raise AccountSessionExpired("Forge Hub session expired. Sign in again.") from None
            if exc.code == 409:
                raise AccountError(message[:160] or "Account is already linked") from None
            if exc.code == 429:
                raise AccountServiceUnavailable("Too many attempts; try again later") from None
            if exc.code == 422:
                raise AccountError("Account details could not be accepted") from None
            if exc.code in (400, 403):
                raise AccountError(message[:160] or "Authorization was rejected") from None
            if exc.code >= 500:
                raise AccountServiceUnavailable(
                    "Forge Hub server is temporarily unavailable") from None
            raise AccountError("Forge Hub server returned HTTP " + str(exc.code)) from None
        except (OSError, TimeoutError) as exc:
            raise AccountServiceUnavailable(
                "Could not contact Forge Hub account service") from exc

    def _save_session(self, data):
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        expires = data.get("expires_in", 3600)
        if (not isinstance(access, str) or not access or
                not isinstance(refresh, str) or not refresh or
                not isinstance(expires, (int, float))):
            raise AccountError("Invalid authentication response")
        with self._lock:
            self._access = access
            self._refresh = refresh
            self._expires_at = time.time() + min(86400, max(60, int(expires))) - 45
            self._persist()

    def _adopt_newer_saved_refresh(self):
        """Recover after another launcher/editor rotated the shared DPAPI token.

        Called only while holding _account_refresh_mutex. Never overwrite the
        encrypted file with an older token. Do not log or expose token values.
        """
        if not self.persist:
            return False
        try:
            path = self.root / "session.dat"
            if not path.is_file() or path.stat().st_size > 16384:
                return False
            data = json.loads(_dpapi(path.read_bytes(), decrypt=True))
            fresh = data.get("refresh_token")
            if data.get("schema") != 1 or not isinstance(fresh, str) or not fresh:
                return False
            if fresh == self._refresh:
                return False
            self._refresh = fresh
            self._access = ""
            self._expires_at = 0
            profile = data.get("profile")
            if isinstance(profile, dict):
                self._cached_profile = {
                    key: str(profile.get(key) or "")[:limit]
                    for key, limit in (("username", 24), ("display_name", 60),
                                       ("avatar_url", 512))
                    if isinstance(profile.get(key, ""), str)
                }
            return True
        except (OSError, ValueError, AccountError, UnicodeError, TypeError):
            return False

    def token(self):
        with self._lock:
            if self._access and time.time() < self._expires_at:
                return self._access
            if not self._refresh:
                raise AccountSessionExpired("Sign in to your Forge Hub account.")
            with (_account_refresh_mutex(self.root) if self.persist
                  else _account_refresh_mutex_disabled()):
                # Another process may have refreshed while we waited.
                self._adopt_newer_saved_refresh()
                refresh = SUPABASE + "/auth/v1/token?grant_type=refresh_token"
                try:
                    response = self._request(refresh, {"refresh_token": self._refresh})
                except AccountSessionExpired:
                    # A legacy launcher may still be running without mutex.
                    # Recover once from a refresh token saved by that process.
                    if not self._adopt_newer_saved_refresh():
                        raise
                    response = self._request(refresh, {"refresh_token": self._refresh})
                self._save_session(response)
                return self._access

    def sign_in(self, identifier, password):
        identity = str(identifier or "").strip()
        if not identity or not isinstance(password, str) or not password:
            raise AccountError("Enter your username/email and password")
        if len(password) > 256:
            raise AccountError("Password is too long")
        if "@" in identity:
            payload = {"email": identity, "password": password}
            data = self._request(SUPABASE + "/auth/v1/token?grant_type=password", payload)
        else:
            username = identity.lower()
            if not USERNAME.fullmatch(username):
                raise AccountError("Invalid username or email")
            data = self._request(BRIDGE, {
                "action": "username_login", "identifier": username, "password": password})
        with self._lock:
            self._cached_profile = {}  # A different account may be signing in.
        self._save_session(data)
        return self.profile()

    def sign_up(self, username, email, password):
        username = str(username or "").strip().lower()
        email = str(email or "").strip()
        if not USERNAME.fullmatch(username) or username in RESERVED:
            raise AccountError("Username must be 3-24 letters, digits or underscores")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise AccountError("Enter a valid email address")
        if not isinstance(password, str) or len(password) < 8 or len(password) > 256:
            raise AccountError("Password must contain at least eight characters")
        response = self._request(SUPABASE + "/auth/v1/signup", {
            "email": email, "password": password,
            "data": {"forge_username_request": username},
        })
        signed = response.get("session") or (response if response.get("access_token") else None)
        if signed:
            with self._lock:
                self._cached_profile = {}
            self._save_session(signed)
            self.save_username(username)
            return {"requires_confirmation": False}
        return {"requires_confirmation": True,
                "message": "Confirm the email from Forge Hub, then sign in and choose your username."}

    def profile(self):
        token = self.token()
        user = self._request(SUPABASE + "/auth/v1/user", token=token, method="GET")
        if not isinstance(user, dict) or not UUID.fullmatch(str(user.get("id") or "")):
            raise AccountError("Invalid Forge Hub account identity")
        uid = user["id"]
        uri = SUPABASE + "/rest/v1/forge_accounts?user_id=eq." + uid + "&select=username,display_name"
        rows = self._request(uri, token=token, method="GET")
        if not isinstance(rows, list):
            raise AccountError("Invalid account profile")
        account = rows[0] if rows else {}
        if not account:
            # Deferred username choice from email-signup metadata. Identity is
            # already verified by Supabase; never reserve names for anonymous users.
            proposed = str((user.get("user_metadata") or {}).get(
                "forge_username_request") or "").strip().lower()
            if USERNAME.fullmatch(proposed) and proposed not in RESERVED:
                try:
                    self._request(
                        SUPABASE + "/rest/v1/forge_accounts",
                        {"user_id": uid, "username": proposed,
                         "display_name": proposed}, token=token)
                    account = {"username": proposed, "display_name": proposed}
                except AccountError:
                    pass  # Username taken or email not yet verified.
        identities = user.get("identities") or []
        providers = {str(x.get("provider")) for x in identities if isinstance(x, dict)}
        github_identity = next((
            x.get("identity_data") or {} for x in identities
            if isinstance(x, dict) and x.get("provider") == "github"
        ), {})
        if not isinstance(github_identity, dict):
            github_identity = {}
        raw_metadata = user.get("user_metadata") or {}
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        github_avatar = (
            github_identity.get("avatar_url") or raw_metadata.get("avatar_url") or ""
        ) if "github" in providers else ""
        result = {
            "id": uid,
            "email": str(user.get("email") or ""),
            "username": str(account.get("username") or ""),
            "display_name": str(account.get("display_name") or ""),
            "github_linked": "github" in providers,
            "avatar_url": str(github_avatar)[:512],
            "providers": sorted(providers),
        }
        with self._lock:
            self._user = user
            self._cached_profile = {
                key: result[key]
                for key in ("username", "display_name", "avatar_url")
            }
            try:
                self._persist(profile_only=True)  # Never roll back a rotated token.
            except (OSError, AccountError):
                pass  # Account stays signed in even if the name cannot be cached.
        return result

    def save_username(self, username, display_name=""):
        username = str(username or "").strip().lower()
        if not USERNAME.fullmatch(username) or username in RESERVED:
            raise AccountError("Username must be 3-24 letters, digits or underscores")
        display_name = str(display_name or username).strip()[:60]
        current = self.profile()
        data = {"username": username, "display_name": display_name}
        token = self.token()
        if current["username"]:
            path = SUPABASE + "/rest/v1/forge_accounts?user_id=eq." + current["id"]
            self._request(path, data, token=token, method="PATCH")
        else:
            path = SUPABASE + "/rest/v1/forge_accounts"
            self._request(path, dict(user_id=current["id"], **data), token=token)
        return self.profile()

    def begin_browser(self, mode="github"):
        if mode not in ("github", "connect", "link"):
            raise AccountError("Invalid connection mode")
        verifier = secrets.token_hex(32)
        challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
        token = self.token() if mode == "link" else None
        result = self._request(BRIDGE, {
            "action": "pair_start", "challenge": challenge, "mode": mode,
        }, token=token)
        request_id = str(result.get("id") or "")
        code = str(result.get("display_code") or "")
        url = str(result.get("url") or "")
        link = urllib.parse.urlsplit(url)
        if (not UUID.fullmatch(request_id) or
                not re.fullmatch(r"[A-HJ-NP-Z2-9]{8}", code) or
                link.scheme != "https" or link.hostname != "carisademon.github.io"
                or link.path != "/Crash-Forge-Racing/forge-hub/account.html"
                or urllib.parse.parse_qs(link.query).get("pair") != [request_id]
                or urllib.parse.parse_qs(link.query).get("code") != [code]):
            raise AccountError("Forge Hub returned an unexpected browser link")
        self._pending = {
            "id": request_id, "code": code, "verifier": verifier,
            "expires_at": time.time() + 300, "mode": mode,
        }
        return {"url": url, "code": code, "mode": mode}

    def finish_browser(self):
        pending = self._pending
        if not pending:
            raise AccountError("No browser authorization in progress")
        if time.time() >= pending["expires_at"]:
            self._pending = None
            raise AccountError("Connection expired; try again")
        result = self._request(BRIDGE, {
            "action": "pair_claim", "id": pending["id"],
            "verifier": pending["verifier"],
        })
        if result.get("status") == "pending":
            return None
        digest = str(result.get("token_hash") or "")
        if result.get("status") != "approved" or not digest:
            raise AccountError("Browser authorization was not completed")
        session = self._request(SUPABASE + "/auth/v1/verify", {
            "type": "magiclink", "token_hash": digest,
        })
        if pending["mode"] == "link" and self.signed_in:
            before = self.profile()["id"]
            after = str(session.get("user", {}).get("id") or "")
            if after != before:
                raise AccountError("The browser authorized a different Forge Hub account")
        if pending["mode"] != "link":
            with self._lock:
                self._cached_profile = {}
        self._save_session(session)
        self._pending = None
        return self.profile()

    def sign_out(self):
        with self._lock:
            old = self._access
            self._access = ""
            self._refresh = ""
            self._expires_at = 0
            self._user = {}
            self._cached_profile = {}
            self._pending = None
            try:
                (self.root / "session.dat").unlink(missing_ok=True)
            except OSError:
                pass
        if old:
            try:
                # GoTrue defaults to scope=global. Global logout revokes
                # *all* active Forge Hub sessions (including GitHub web tabs),
                # making the website display a cached signed-in profile that
                # the launcher bridge then rejects as session_not_found.
                # Logout from this Windows EXE must revoke only its own token.
                self._request(SUPABASE + "/auth/v1/logout?scope=local", token=old)
            except AccountError:
                pass