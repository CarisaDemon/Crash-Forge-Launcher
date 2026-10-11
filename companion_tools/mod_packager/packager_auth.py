"""Single Forge Hub identity gate for native Mod Packager.

This runs inside the packager EXE, independently of Launcher buttons.
No local marker, user-editable INI or GitHub username grants access.
"""
from forge_account_client import (
    AccountClient, AccountError, AccountSessionExpired, AccountServiceUnavailable
)


def check_account(client=None):
    client = client if client is not None else AccountClient()
    if not client.signed_in:
        return False, "Sign in to Forge Hub through the launcher before using Mod Packager."
    try:
        profile = client.profile()   # Supabase validates identity server-side.
        if not profile.get("id"):
            return False, "Could not verify the Forge Hub account."
        return True, "Forge Hub account verified."
    except AccountSessionExpired:
        return False, "Your Forge Hub session expired. Sign in again through Launcher > My Account."
    except AccountServiceUnavailable:
        return False, "Forge Hub is temporarily unreachable. Check Internet and select RETRY."
    except (AccountError, ValueError, OSError):
        return False, "Forge Hub could not verify your account. Open Launcher > My Account."
