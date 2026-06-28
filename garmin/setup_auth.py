#!/usr/bin/env python3
"""
Run this ONCE to authenticate with Garmin Connect and save tokens.
After this, garmin_server.py will reuse the tokens automatically.

Usage:
    python setup_auth.py
"""

import os
import getpass
import garminconnect

TOKEN_DIR = os.path.expanduser("~/.garminconnect")
os.makedirs(TOKEN_DIR, exist_ok=True)
os.chmod(TOKEN_DIR, 0o700)

print("Garmin Connect — first-time authentication")
print("=" * 45)
print("Tokens will be saved to ~/.garminconnect/")
print("Your password is NOT stored — only OAuth tokens.\n")

email = input("Garmin email: ").strip()
password = getpass.getpass("Garmin password: ")

# return_on_mfa=True makes login() return the client_state dict instead of
# raising an exception when MFA is needed, so we can prompt and resume cleanly.
client = garminconnect.Garmin(email=email, password=password, return_on_mfa=True)

print("\nAttempting login (this may take a few seconds)...")

try:
    result = client.login()
except garminconnect.GarminConnectTooManyRequestsError:
    print("\n❌ Garmin rate-limited this IP (429).")
    print("   Wait 5–10 minutes and try again.")
    exit(1)
except garminconnect.GarminConnectAuthenticationError as e:
    print(f"\n❌ Authentication error: {e}")
    exit(1)

# result is a client_state dict when MFA is required; None when login succeeded directly
if result is not None:
    print("\nMFA required.")
    mfa_code = input("Enter the code from your authenticator app: ").strip()
    try:
        client.resume_login(result, mfa_code)
    except Exception as e:
        print(f"\n❌ MFA verification failed: {e}")
        exit(1)

# Token dump — the garth client lives at client.client in this library version
client.client.dump(TOKEN_DIR)
os.chmod(TOKEN_DIR, 0o700)

print(f"\n✅ Authenticated. Tokens saved to {TOKEN_DIR}")
print("\nQuick sanity check — fetching your display name...")
try:
    name = client.get_full_name()
    print(f"   Logged in as: {name}")
except Exception:
    print("   (couldn't fetch name, but tokens look good)")

print("\nYou're all set. Add garmin_server.py to your Claude Desktop config (see README.md).\n")
