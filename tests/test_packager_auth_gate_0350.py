"""Gate native Mod Packager through the authenticated Forge Hub profile."""
import unittest
from types import SimpleNamespace
from unittest import mock

from companion_tools.mod_packager.packager_auth import check_account
from launcher import Launcher
from forge_account_client import AccountSessionExpired, AccountServiceUnavailable

class ModPackagerAccountGateTests(unittest.TestCase):
    def test_guest_cannot_open_native_exporter(self):
        client=mock.Mock(signed_in=False)
        ok,message=check_account(client)
        self.assertFalse(ok)
        self.assertIn("Sign in",message)
        client.profile.assert_not_called()

    def test_saved_token_is_not_sufficient_without_server_confirmation(self):
        for failure in (
            AccountSessionExpired("Expired token"),
            AccountServiceUnavailable("Temporary internet failure"),
        ):
            with self.subTest(failure=type(failure).__name__):
                client=mock.Mock(signed_in=True)
                client.profile.side_effect=failure
                ok,message=check_account(client)
                self.assertFalse(ok)
                self.assertTrue(message)

    def test_server_verified_profile_unlocks_packager(self):
        client=mock.Mock(signed_in=True)
        client.profile.return_value={"id":"12345678-1234-1234-1234-123456789012"}
        ok,message=check_account(client)
        self.assertTrue(ok)
        self.assertIn("verified",message)

    def test_launcher_prompts_for_account_instead_of_spawning_packager(self):
        app=SimpleNamespace(
            account_client=mock.Mock(signed_in=False),
            _account_badge_problem=None,
            status_label=mock.Mock(),
            _close_editor_selector=mock.Mock(),
            _open_account_dialog=mock.Mock(),
        )
        with mock.patch("launcher.subprocess.Popen") as popen:
            Launcher._launch_editor_tool(app,r"C:\stub\CrashForgeModPackager.exe")
        app._open_account_dialog.assert_called_once()
        app._close_editor_selector.assert_called_once()
        popen.assert_not_called()

    def test_expired_saved_account_also_routes_to_account_dialog(self):
        app=SimpleNamespace(
            account_client=mock.Mock(signed_in=True),
            _account_badge_problem="expired",
            status_label=mock.Mock(),
            _close_editor_selector=mock.Mock(),
            _open_account_dialog=mock.Mock(),
        )
        Launcher._launch_editor_tool(app,r"C:\stub\CrashForgeModPackager.exe")
        app._open_account_dialog.assert_called_once()


if __name__=="__main__":
    unittest.main()
