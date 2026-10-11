"""Crash Forge Launcher account client. Forge Hub Supabase auth, no new identity silo.

Auth and pairing use HTTPS; GitHub passwords never enter this process. Tokens
are in RAM and the refresh token is persisted only with Windows DPAPI.
"""
from __future__ import annotations

import ctypes
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
        self._pending = None
        if self.persist:
            self.restore()

    @property
    def signed_in(self):
        return bool(self._refresh or self._access)

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
            return True
        except (OSError, AccountError, ValueError, TypeError, UnicodeError):
            return False

    def _persist(self):
        if not self.persist:
            return
        if not self._refresh:
            return
        data = json.dumps({"schema": 1, "refresh_token": self._refresh},
                          separators=(",", ":")).encode("utf-8")
        encoded = _dpapi(data)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "session.dat.tmp"
        try:
            tmp.write_bytes(encoded)
            os.replace(tmp, self.root / "session.dat")
        finally:
            if tmp.exists():
                tmp.unlink()

    def _request(self, url: str, payload=None, *, token=None, method="POST"):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "mjvpkerobjgoldmimyxz.supabase.co"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.fragment or
                not parsed.path.startswith(("/auth/v1/", "/rest/v1/forge_accounts",
                                            "/functions/v1/forge-launcher-auth"))):
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
            if exc.code == 401:
                raise AccountError("Invalid credentials or expired session") from None
            if exc.code == 409:
                raise AccountError(message[:160] or "Account is already linked") from None
            if exc.code == 429:
                raise AccountError("Too many attempts; try again later") from None
            if exc.code == 422:
                raise AccountError("Account details could not be accepted") from None
            if exc.code in (400, 403):
                raise AccountError(message[:160] or "Authorization was rejected") from None
            raise AccountError("Forge Hub server returned HTTP " + str(exc.code)) from None
        except (OSError, TimeoutError) as exc:
            raise AccountError("Could not contact Forge Hub account service") from exc

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

    def token(self):
        with self._lock:
            if self._access and time.time() < self._expires_at:
                return self._access
            if not self._refresh:
                raise AccountError("Not signed in")
            response = self._request(
                SUPABASE + "/auth/v1/token?grant_type=refresh_token",
                {"refresh_token": self._refresh})
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
        self._user = user
        return {
            "id": uid,
            "email": str(user.get("email") or ""),
            "username": str(account.get("username") or ""),
            "display_name": str(account.get("display_name") or ""),
            "github_linked": "github" in providers,
            "avatar_url": str(github_avatar)[:512],
            "providers": sorted(providers),
        }

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
            self._pending = None
            try:
                (self.root / "session.dat").unlink(missing_ok=True)
            except OSError:
                pass
        if old:
            try:
                self._request(SUPABASE + "/auth/v1/logout", token=old)
            except AccountError:
                pass