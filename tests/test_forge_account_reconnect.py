"""Forge Hub account badge connection state regression tests."""
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from forge_account_badge import account_label
from forge_account_client import AccountError, AccountSessionExpired, AccountServiceUnavailable
from launcher import Launcher


class AccountConnectionRetryTests(unittest.TestCase):
    def fake_launcher(self, failure):
        client=Mock()
        client.signed_in=True
        client.profile.side_effect=failure
        app=SimpleNamespace(
            account_client=client,
            _account_badge_generation=0,
            _account_badge_busy=False,
            _account_badge_retry_failures=0,
            _account_badge_pending=False,
            _account_badge_problem=None,
            _account_badge_connected=False,
            _account_badge_profile={"username":"racer_name"},
            _account_badge_avatar_url="",
            _account_badge_avatar_photo=None,
            _account_badge_queue=queue.Queue(),
            _paint_floating_header=Mock(),
            after=Mock(),
        )
        app._account_badge_refresh_async=lambda: Launcher._account_badge_refresh_async(app)
        app._account_badge_poll=lambda: Launcher._account_badge_poll(app)
        return app

    def test_saved_account_not_guest_during_network_outage(self):
        label=account_label({"username":"racer_name"},
                            signed_in=True,connected=False,problem="connection")
        self.assertEqual(label["name"],"racer_name")
        self.assertEqual(label["status"],"Reconnecting...")
        self.assertFalse(label["online"])

    def test_invalid_session_requires_signin_but_never_erases_display_name(self):
        label=account_label({"username":"racer_name"},
                            signed_in=True,connected=False,problem="expired")
        self.assertEqual(label["name"],"racer_name")
        self.assertEqual(label["status"],"Sign in again")

    def test_temporary_server_failure_schedules_background_retry(self):
        app=self.fake_launcher(AccountServiceUnavailable("Could not contact Forge Hub account service"))
        Launcher._account_badge_refresh_async(app)
        kind,payload,generation=app._account_badge_queue.get(timeout=5)
        app._account_badge_queue.put((kind,payload,generation))
        self.assertEqual(payload,(None,False,"connection"))
        Launcher._account_badge_poll(app)
        self.assertFalse(app._account_badge_busy)
        self.assertTrue(app.account_client.signed_in)
        self.assertEqual(app._account_badge_profile["username"],"racer_name")
        self.assertEqual(app._account_badge_problem,"connection")
        self.assertFalse(app._account_badge_connected)
        self.assertIn(25000,[call.args[0] for call in app.after.call_args_list])

    def test_expired_session_never_queues_network_retry(self):
        app=self.fake_launcher(AccountSessionExpired("Forge Hub session expired. Sign in again."))
        Launcher._account_badge_refresh_async(app)
        kind,payload,generation=app._account_badge_queue.get(timeout=5)
        app._account_badge_queue.put((kind,payload,generation))
        Launcher._account_badge_poll(app)
        self.assertEqual(app._account_badge_problem,"expired")
        self.assertNotIn(25000,[call.args[0] for call in app.after.call_args_list])
        self.assertTrue(app.account_client.signed_in)


if __name__=="__main__":
    unittest.main()
