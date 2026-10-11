"""
Access module administration commands.

  python -m app.access.cli migrate                  # apply database migrations
  python -m app.access.cli create-superadmin --name "Ops Admin" --email admin@example.org
      (password read from ACCESS_SUPERADMIN_PASSWORD or prompted; never passed on the command line)
  python -m app.access.cli purge-face-audit         # delete face-verification audit rows past retention
  python -m app.access.cli seed-demo [--reset-passwords]
      (development only: 3 buses + the 3 dev conductors, demo colleges and demo passengers; any new password is
       written to backend/.env.access.accounts, which is git-ignored, and never printed)
"""

import argparse
import getpass
import os
import sys
from pathlib import Path


def main() -> int:
    from .api import load_local_env

    load_local_env()
    parser = argparse.ArgumentParser(prog="app.access.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sa = sub.add_parser("create-superadmin")
    sa.add_argument("--name", required=True)
    sa.add_argument("--email", required=True)
    sub.add_parser("purge-face-audit")
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--reset-passwords", action="store_true")
    args = parser.parse_args()

    from . import config

    config.settings.__dict__.update(config.AccessSettings().__dict__)

    if args.cmd == "migrate":
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic_access.ini"))
        command.upgrade(cfg, "head")
        print("Access module database is up to date.")
        return 0

    from .db import configure, get_db

    configure()
    gen = get_db()
    db = next(gen)
    try:
        if args.cmd == "create-superadmin":
            from sqlalchemy import select

            from .models import Role, User
            from .security import hash_password, password_policy_error

            password = os.getenv("ACCESS_SUPERADMIN_PASSWORD") or getpass.getpass("Super admin password: ")
            err = password_policy_error(password)
            if err:
                print(err, file=sys.stderr)
                return 2
            if db.scalars(select(User).where(User.email == args.email.lower())).first():
                print("A user with this email already exists.", file=sys.stderr)
                return 1
            db.add(User(name=args.name, email=args.email.lower(), password_hash=hash_password(password), role=Role.SUPER_ADMIN))
            db.commit()
            print(f"Super admin created: {args.email.lower()}")
        elif args.cmd == "seed-demo":
            from .seed import seed_demo

            if config.settings.env == "production":
                print("seed-demo is for development only.", file=sys.stderr)
                return 2
            for line in seed_demo(db, reset_passwords=args.reset_passwords):
                print(line)
        elif args.cmd == "purge-face-audit":
            from .routers.identity import purge_expired_face_attempts

            n = purge_expired_face_attempts(db)
            db.commit()
            print(f"Deleted {n} face-verification audit rows past retention.")
    finally:
        gen.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
