"""
Interactive setup for sign-in code emails. Writes SMTP settings into backend/.env.access (git-ignored).

    cd backend && python3 -m app.access.configure_email

The password is read with getpass (not shown on screen, not stored in shell history) and never printed.
Other keys already in the file are kept.
"""

import getpass
import os
import re
import smtplib
import ssl
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env.access"

PRESETS = {
    "1": ("Gmail / Google Workspace", "smtp.gmail.com", "587", "starttls"),
    "2": ("Outlook / Microsoft 365", "smtp.office365.com", "587", "starttls"),
    "3": ("Zoho Mail (India)", "smtp.zoho.in", "465", "ssl"),
    "4": ("Other (enter host/port)", "", "", ""),
}


def read_env() -> list:
    return ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []


def write_env(lines: list, updates: dict) -> None:
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    if any(k not in seen for k in updates):
        out.append("")
        out.append("# Sign-in code email (set by app.access.configure_email)")
        out.extend(f"{k}={v}" for k, v in updates.items() if k not in seen)
    ENV_PATH.write_text("\n".join(out).rstrip() + "\n")
    os.chmod(ENV_PATH, 0o600)  # readable only by you


def test_login(host: str, port: int, security: str, user: str, password: str) -> str:
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
        with server:
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
            server.login(user, password)
        return ""
    except smtplib.SMTPAuthenticationError:
        return "The email server rejected the address/password. For Gmail, use an App Password (not your normal password)."
    except (smtplib.SMTPException, OSError) as exc:
        return f"Could not connect to {host}:{port} ({type(exc).__name__})."


def main() -> int:
    print("\nನಮ್ಮ Bus — sign-in code email setup")
    print("Your password is typed hidden and saved only in backend/.env.access on this Mac.\n")
    for k, (name, *_rest) in PRESETS.items():
        print(f"  {k}. {name}")
    choice = input("Choose your email provider [1]: ").strip() or "1"
    name, host, port, security = PRESETS.get(choice, PRESETS["1"])
    if not host:
        host = input("SMTP host: ").strip()
        port = input("SMTP port [587]: ").strip() or "587"
        security = (input("Security starttls/ssl/none [starttls]: ").strip() or "starttls").lower()
    address = input("Email address to send from: ").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
        print("That does not look like an email address. Nothing was changed.")
        return 1
    if choice == "1":
        print("For Gmail: Google Account → Security → 2-Step Verification → App passwords → create one.")
    password = getpass.getpass("App password (hidden while you type): ").replace(" ", "")
    if not password:
        print("No password entered. Nothing was changed.")
        return 1

    print("Checking the details with the email server…")
    error = test_login(host, int(port), security, address, password)
    if error:
        print(f"✗ {error}\nNothing was changed. Run this again when ready.")
        return 1

    write_env(read_env(), {
        "OTP_PROVIDER": "email",
        "ACCESS_LOGIN_EMAIL_CODE": "true",
        "SMTP_HOST": host,
        "SMTP_PORT": port,
        "SMTP_SECURITY": security,
        "SMTP_USERNAME": address,
        "SMTP_PASSWORD": password,
        "SMTP_FROM": address,
    })
    print(f"✓ Saved. Sign-in codes will be sent from {address} via {name}.")
    print("Restart the Namma Bus backend for this to take effect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
