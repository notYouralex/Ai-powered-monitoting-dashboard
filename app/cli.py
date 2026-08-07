import argparse
import getpass
import sys

from sqlalchemy import select

from app.auth.security import hash_password
from app.auth.service import normalize_username, record_auth_event
from app.db.models import User
from app.db.session import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitoring platform administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_admin = subparsers.add_parser("create-admin", help="Create a local administrator")
    create_admin.add_argument("--username", required=True)
    create_admin.set_defaults(handler=_create_admin)
    return parser


def _create_admin(args: argparse.Namespace) -> int:
    username = normalize_username(args.username)
    if not username:
        print("Username is required.", file=sys.stderr)
        return 2

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.username == username)) is not None:
            print("Username already exists.", file=sys.stderr)
            return 1

        user = User(
            username=username,
            password_hash=hash_password(password),
            is_active=True,
            is_admin=True,
        )
        db.add(user)
        db.flush()
        record_auth_event(
            db,
            event_type="bootstrap_admin_create",
            username=username,
            user_id=user.id,
            success=True,
        )
        db.commit()

    print(f"Administrator '{username}' created.")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
