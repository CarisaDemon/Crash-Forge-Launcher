"""v0.3.50: token rotation, GoTrue 400 and real account state regression."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

import forge_account_client as account

class SessionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def fake_http_error(self, code, response):
        contents=json.dumps(response).encode("utf-8")
        return urllib.error.HTTPError(
            account.SUPABASE+"/auth/v1/token?grant_type=refresh_token",
            code, "failed", {}, BytesIO(contents))

    def test_gotrue_http_400_invalid_refresh_is_expired_not_reconnecting(self):
        client=account.AccountClient(root=self.temp.name,persist=False)
        fake=self.fake_http_error(
            400,{"code":"refresh_token_not_found",
                 "msg":"Invalid Refresh Token: Refresh Token Not Found"})
        with mock.patch.object(account.urllib.request,"build_opener") as opener:
            opener.return_value.open.side_effect=fake
            with self.assertRaises(account.AccountSessionExpired):
                client._request(
                    account.SUPABASE+"/auth/v1/token?grant_type=refresh_token",
                    {"refresh_token":"dummy"})
        self.assertEqual(opener.return_value.open.call_count,1)

    def test_bad_password_http_400_is_not_false_refresh_expiry(self):
        client=account.AccountClient(root=self.temp.name,persist=False)
        err=self.fake_http_error(400,{"msg":"Invalid login credentials"})
        with mock.patch.object(account.urllib.request,"build_opener") as opener:
            opener.return_value.open.side_effect=err
            with self.assertRaises(account.AccountError) as errinfo:
                client._request(account.SUPABASE+"/auth/v1/token?grant_type=password",
                                {"email":"demo@example.invalid","password":"wrong"})
        self.assertNotIsInstance(errinfo.exception,account.AccountSessionExpired)

    def test_two_processes_adopt_the_latest_encrypted_token_before_renewal(self):
        with mock.patch.object(account,"_dpapi",side_effect=lambda data,decrypt=False:data):
            first=account.AccountClient(root=self.temp.name,persist=True)
            first._save_session({"access_token":"old-access","refresh_token":"old-refresh",
                                 "expires_in":1800})
            second=account.AccountClient(root=self.temp.name,persist=True)
            self.assertTrue(second.signed_in)
            first._save_session({"access_token":"new-access","refresh_token":"new-refresh",
                                 "expires_in":1800})
            with mock.patch.object(second,"_request",return_value={
                "access_token":"next-access","refresh_token":"next-refresh",
                "expires_in":1800}) as req:
                access=second.token()
            self.assertEqual(access,"next-access")
            self.assertEqual(req.call_args.args[1]["refresh_token"],"new-refresh")
            stored=json.loads((Path(self.temp.name)/"session.dat").read_bytes())
            self.assertEqual(stored["refresh_token"],"next-refresh")

    def test_retry_once_when_legacy_launcher_rotates_during_refresh(self):
        with mock.patch.object(account,"_dpapi",side_effect=lambda data,decrypt=False:data):
            client=account.AccountClient(root=self.temp.name,persist=True)
            client._save_session({"access_token":"old-access",
                                  "refresh_token":"old-refresh","expires_in":1800})
            client._expires_at = 0  # Force a real rotation attempt.
            def fake_request(url,payload,**kwargs):
                if payload["refresh_token"]=="old-refresh":
                    (Path(self.temp.name)/"session.dat").write_text(json.dumps({
                        "schema":1,"refresh_token":"new-refresh","profile":{}}),
                        encoding="utf-8")
                    raise account.AccountSessionExpired("Session expired")
                self.assertEqual(payload["refresh_token"],"new-refresh")
                return {"access_token":"good-access","refresh_token":"good-refresh",
                        "expires_in":3600}
            with mock.patch.object(client,"_request",side_effect=fake_request) as req:
                self.assertEqual(client.token(),"good-access")
                self.assertEqual(req.call_count,2)

    def test_irrevocably_revoked_token_does_not_spin_and_session_is_preserved(self):
        with mock.patch.object(account,"_dpapi",side_effect=lambda data,decrypt=False:data):
            client=account.AccountClient(root=self.temp.name,persist=True)
            client._save_session({"access_token":"old-access",
                                  "refresh_token":"revoked","expires_in":1800})
            client._expires_at = 0  # Force a real rotation attempt.
            before=(Path(self.temp.name)/"session.dat").read_bytes()
            with mock.patch.object(client,"_request",
                side_effect=account.AccountSessionExpired("Sign in again")) as request:
                with self.assertRaises(account.AccountSessionExpired):
                    client.token()
            self.assertEqual(request.call_count,1)
            self.assertTrue(client.signed_in)
            self.assertEqual((Path(self.temp.name)/"session.dat").read_bytes(),before)

if __name__=="__main__":
    unittest.main()
