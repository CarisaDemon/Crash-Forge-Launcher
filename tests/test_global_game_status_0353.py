"""Global GAME status must reflect public releases, not the installed PC files."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

import forge_live_ui as live

ROOT = Path(__file__).resolve().parents[1]


class GlobalGameStatusTests(TestCase):
    def _app(self, **changes):
        app = SimpleNamespace(
            build_state_label=mock.Mock(), build_indicator=mock.Mock(),
            latest_game_release=None, release_check_busy=False,
            _global_release_checked=False, _global_release_error=False,
            local_game_status={"installed": True},
        )
        for key, value in changes.items():
            setattr(app, key, value)
        return app

    def _label(self, app):
        live.ForgeLiveMixin._refresh_global_game_status(app)
        return app.build_state_label.configure.call_args.kwargs["text"]

    def test_installed_pc_game_does_not_imply_public_release(self):
        self.assertEqual(self._label(self._app()), "CHECKING RELEASES")
        self.assertEqual(self._label(self._app(
            _global_release_checked=True)), "NO PUBLIC RELEASE")

    def test_valid_public_package_shows_global_version(self):
        app = self._app(
            latest_game_release={"version": "2.1.0",
                                 "verified_package": True})
        self.assertEqual(self._label(app), "PUBLIC v2.1.0")
        self.assertEqual(
            app.build_indicator.configure.call_args.kwargs["fg"], "#56C47A")

    def test_listed_release_without_verified_zip_is_not_ready(self):
        self.assertEqual(self._label(self._app(
            latest_game_release={"version": "2.1.0",
                                 "verified_package": False})),
            "RELEASE LISTED")

    def test_failed_public_check_is_not_no_release(self):
        self.assertEqual(self._label(self._app(
            _global_release_error=True)), "STATUS UNAVAILABLE")

    def test_local_installation_status_stays_separate(self):
        source = (ROOT / "launcher.py").read_text(encoding="utf-8")
        live_code = (ROOT / "forge_live_ui.py").read_text(encoding="utf-8")
        self.assertIn('text="GLOBAL GAME STATUS"', source)
        self.assertIn('"INSTALLED" if status["installed"] else "NOT INSTALLED"', live_code)
        self.assertIn('ForgeLiveMixin._refresh_global_game_status(self)', live_code)


if __name__ == "__main__":
    import unittest
    unittest.main()
