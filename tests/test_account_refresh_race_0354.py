"""v0.3.54: two independent Windows EXEs must not revoke each other's login."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import forge_account_client as account

USER = {"id": "12345678-1234-1234-1234-123456789abc",
        "email": "user@example.invalid", "identities": [], "user_metadata": {}}


def result(token):
    return {"access_token": "access-" + token,
            "refresh_token": token, "expires_in": 3600}


class RefreshTokenRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch_dpapi = patch.object(
            account, "_dpapi", side_effect=lambda data, decrypt=False: data)
        self.patch_dpapi.start()
        self.addCleanup(self.patch_dpapi.stop)
        self.path = Path(self.temp.name) / "session.dat"

    def stored(self):
        return json.loads(self.path.read_bytes().decode("utf-8"))

    def fake_profile(self, client, name):
        def request(url, payload=None, *, token=None, method="POST"):
            if "/auth/v1/user" in url:
                return dict(USER)
            if "/rest/v1/forge_accounts?" in url:
                return [{"username": name, "display_name": name}]
            raise AssertionError("Unexpected endpoint")
        client._request = request
        return client.profile()

    def test_stale_profile_cannot_restore_revoked_refresh_token(self):
        first = account.AccountClient(self.temp.name, persist=True)
        first._save_session(result("initial"))
        stale = account.AccountClient(self.temp.name, persist=True)
        fresh = account.AccountClient(self.temp.name, persist=True)
        fresh._save_session(result("rotated"))
        # The older EXE may still have a valid access token for fetching a
        # public username/avatar; its refresh token is no longer valid.
        stale._access = "still-valid-access"
        stale._expires_at = time.time() + 300
        self.assertEqual(self.fake_profile(stale, "older_profile")["username"],
                         "older_profile")
        self.assertEqual(self.stored()["refresh_token"], "rotated")
        self.assertNotEqual(self.stored().get("profile", {}).get("username"),
                            "older_profile")

        # At the next renewal the older EXE adopts the new encrypted token.
        stale._expires_at = 0
        calls = []
        def renew(url, payload, **kwargs):
            calls.append(payload["refresh_token"])
            return result("newest")
        stale._request = renew
        self.assertEqual(stale.token(), "access-newest")
        self.assertEqual(calls, ["rotated"])
        self.assertEqual(self.stored()["refresh_token"], "newest")

    def test_matching_profile_stays_cached_without_rotating_login(self):
        client = account.AccountClient(self.temp.name, persist=True)
        client._save_session(result("same"))
        self.fake_profile(client, "live_profile")
        self.assertEqual(self.stored()["refresh_token"], "same")
        self.assertEqual(self.stored()["profile"]["username"], "live_profile")

    def test_stale_profile_never_recreates_a_signed_out_session(self):
        signed_out = account.AccountClient(self.temp.name, persist=True)
        signed_out._save_session(result("session"))
        stale = account.AccountClient(self.temp.name, persist=True)
        stale._access = "valid-cached-access"
        stale._expires_at = time.time() + 300
        signed_out._request = lambda *_args, **_kwargs: {}
        signed_out.sign_out()
        self.assertFalse(self.path.exists())
        self.fake_profile(stale, "old_profile")
        self.assertFalse(self.path.exists())

    def test_session_file_write_uses_private_atomic_temporary_name(self):
        client = account.AccountClient(self.temp.name, persist=True)
        client._save_session(result("session"))
        self.assertEqual(self.stored()["refresh_token"], "session")
        self.assertEqual(list(Path(self.temp.name).glob("session.dat.tmp*")), [])


if __name__ == "__main__":
    unittest.main()
