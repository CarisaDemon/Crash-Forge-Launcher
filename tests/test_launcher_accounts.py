"""Offline security and integration checks for Forge Hub launcher accounts."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import forge_account_client as auth

UUID = "12345678-1234-1234-1234-123456789abc"
CODE = "ABCDEFGH"
URL = (auth.WEB_ACCOUNT + "?pair=" + UUID +
       "&code=" + CODE + "&mode=github")
SESSION = {"access_token":"fake-jwt-not-valid-online",
           "refresh_token":"fake-refresh-token", "expires_in":3600}
USER = {"id":UUID, "email":"test@example.invalid","identities":[],
        "user_metadata":{}}


class AccountClientTests(unittest.TestCase):
    def make(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        return auth.AccountClient(self.temp.name,persist=False)

    def test_email_signin_uses_official_gotrue_endpoint_only(self):
        c=self.make()
        seen=[]
        def request(url,payload=None,*,token=None,method="POST"):
            seen.append((url,payload,token,method))
            if "/auth/v1/token?" in url:return dict(SESSION)
            if "/auth/v1/user" in url:return dict(USER)
            if "/rest/v1/forge_accounts?" in url:return []
            raise AssertionError(url)
        c._request=request
        account=c.sign_in("test@example.invalid","correct-password")
        self.assertEqual(account["id"],UUID)
        self.assertEqual(seen[0][0],auth.SUPABASE+"/auth/v1/token?grant_type=password")
        self.assertEqual(seen[0][1],{"email":"test@example.invalid","password":"correct-password"})
        self.assertFalse((Path(self.temp.name)/"session.dat").exists())

    def test_username_signin_uses_secure_backend_not_public_email_lookup(self):
        c=self.make()
        seen=[]
        def request(url,payload=None,*,token=None,method="POST"):
            seen.append((url,payload))
            if url==auth.BRIDGE:return dict(SESSION)
            if "/auth/v1/user" in url:return dict(USER)
            if "/rest/v1/forge_accounts?" in url:return []
            raise AssertionError(url)
        c._request=request
        c.sign_in("Test_Name","secret")
        self.assertEqual(seen[0][0],auth.BRIDGE)
        self.assertEqual(seen[0][1]["identifier"],"test_name")
        self.assertFalse(any("getUserById" in u for u,_ in seen))

    def test_linked_github_avatar_is_returned_in_profile(self):
        client=self.make()
        client._save_session(SESSION)
        github_url="https://avatars.githubusercontent.com/u/12345?v=4"
        github_user=dict(USER,identities=[
            {"provider":"github","identity_data":{"avatar_url":github_url}}
        ])
        def request(url,payload=None,*,token=None,method="POST"):
            if "/auth/v1/user" in url:
                return github_user
            if "/rest/v1/forge_accounts?" in url:
                return [{"username":"online_racer","display_name":"Online Racer"}]
            raise AssertionError(url)
        client._request=request
        profile=client.profile()
        self.assertEqual(profile["avatar_url"],github_url)
        self.assertTrue(profile["github_linked"])
        self.assertEqual(profile["username"],"online_racer")

    def test_email_only_account_has_no_forged_github_avatar(self):
        client=self.make()
        client._save_session(SESSION)
        other=dict(USER,user_metadata={
            "avatar_url":"https://avatars.githubusercontent.com/u/456?v=4"
        })
        client._request=lambda url,*args,**kwargs: (
            other if "/auth/v1/user" in url else
            [{"username":"email_racer","display_name":"Email Racer"}]
        )
        profile=client.profile()
        self.assertFalse(profile["github_linked"])
        self.assertEqual(profile["avatar_url"],"")

    def test_signup_respects_email_verification_and_private_data(self):
        c=self.make()
        calls=[]
        def request(url,payload=None,*,token=None,method="POST"):
            calls.append((url,payload))
            return {"user":{"id":UUID},"session":None}
        c._request=request
        result=c.sign_up("modder_name","test@example.invalid","12345678")
        self.assertTrue(result["requires_confirmation"])
        self.assertFalse(c.signed_in)
        self.assertEqual(calls[0][1]["data"]["forge_username_request"],"modder_name")
        with self.assertRaises(auth.AccountError):
            c.sign_up("admin","test@example.invalid","12345678")

    def test_browser_pair_uses_256_bit_verifier_not_token_in_url(self):
        c=self.make()
        captured=[]
        def request(url,payload=None,*,token=None,method="POST"):
            captured.append((url,payload,token))
            if payload["action"]=="pair_start":
                return {"id":UUID,"display_code":CODE,"url":URL}
            if payload["action"]=="pair_claim":
                return {"status":"pending"}
            raise AssertionError(url)
        c._request=request
        info=c.begin_browser("github")
        self.assertEqual(info["code"],CODE)
        challenge=captured[0][1]["challenge"]
        self.assertEqual(len(challenge),64)
        self.assertNotIn(c._pending["verifier"],info["url"])
        self.assertEqual(hashlib.sha256(c._pending["verifier"].encode()).hexdigest(),challenge)
        self.assertIsNone(c.finish_browser())

    def test_browser_pair_exchanges_one_time_link_for_regular_session(self):
        c=self.make()
        requests=[]
        def request(url,payload=None,*,token=None,method="POST"):
            requests.append((url,payload,token))
            if payload and payload.get("action")=="pair_start":
                return {"id":UUID,"display_code":CODE,"url":URL}
            if payload and payload.get("action")=="pair_claim":
                return {"status":"approved","token_hash":"opaque-otp","verify_type":"magiclink"}
            if "/auth/v1/verify" in url:return dict(SESSION)
            if "/auth/v1/user" in url:return dict(USER)
            if "/rest/v1/forge_accounts?" in url:return []
            raise AssertionError(url)
        c._request=request
        c.begin_browser()
        account=c.finish_browser()
        self.assertEqual(account["email"],"test@example.invalid")
        self.assertIsNone(c._pending)
        self.assertEqual([x[0] for x in requests].count(auth.BRIDGE),2)
        self.assertEqual(requests[2][1]["token_hash"],"opaque-otp")

    def test_browser_refuses_untrusted_web_redirect(self):
        c=self.make()
        c._request=lambda *_args,**_kw: {
            "id":UUID,"display_code":CODE,
            "url":"https://evil.invalid/forge-hub/account.html?pair="+UUID+"&code="+CODE
        }
        with self.assertRaises(auth.AccountError):
            c.begin_browser()

    def test_user_registration_hint_claims_only_after_authentication(self):
        c=self.make()
        c._save_session(SESSION)
        calls=[]
        person=dict(USER,user_metadata={"forge_username_request":"modder_name"})
        def request(url,payload=None,*,token=None,method="POST"):
            calls.append((url,payload,method))
            if "/auth/v1/user" in url:return person
            if "/rest/v1/forge_accounts?" in url:return []
            if url.endswith("/rest/v1/forge_accounts"):return {}
            raise AssertionError(url)
        c._request=request
        result=c.profile()
        self.assertEqual(result["username"],"modder_name")
        self.assertEqual(calls[-1][1]["user_id"],UUID)

    def test_desktop_logout_keeps_browser_and_packager_sessions(self):
        client=self.make()
        client._save_session(SESSION)
        seen=[]
        def fake_request(url,payload=None,*,token=None,method="POST"):
            seen.append((url,token,method))
            return {}
        client._request=fake_request
        client.sign_out()
        self.assertFalse(client.signed_in)
        self.assertEqual(seen,[(
            auth.SUPABASE+"/auth/v1/logout?scope=local",
            SESSION["access_token"],"POST")])

    @unittest.skipUnless(os.name=="nt","DPAPI is Windows-only")
    def test_session_is_encrypted_at_rest_and_can_be_restored(self):
        with tempfile.TemporaryDirectory() as path:
            client=auth.AccountClient(path,persist=True)
            client._save_session(SESSION)
            raw=(Path(path)/"session.dat").read_bytes()
            self.assertNotIn(b"fake-refresh-token",raw)
            copy=auth.AccountClient(path,persist=True)
            self.assertTrue(copy.signed_in)
            self.assertFalse(copy._access)
            self.assertEqual(copy._refresh,SESSION["refresh_token"])
            copy._request=lambda *_a,**_k: {}
            copy.sign_out()
            self.assertFalse((Path(path)/"session.dat").exists())


if __name__ == "__main__":
    unittest.main()