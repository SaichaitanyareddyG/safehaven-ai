"""Create the first admin on a server, or promote an existing account.

There is no sign-up on a shared server, so the first admin cannot come from
the dashboard. Prints ONLY the one-time password, so it can go straight to
the clipboard instead of a terminal log:

    python -m app.auth.create_admin --email you@hospital.org --name "Your Name" | pbcopy

Uses DATABASE_URL like the app. Promoting an existing account keeps its
password and prints nothing.
"""

import argparse
import sys

from app import models as _registered_models  # noqa: F401  (registers every model)
from app.auth.models import ROLE_ADMIN, User
from app.auth.security import generate_one_time_password, hash_password
from app.core.db import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    email = args.email.strip().lower()

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is not None:
            user.role, user.is_active = ROLE_ADMIN, True
            db.commit()
            print(f"{email} is now an admin (password unchanged).", file=sys.stderr)
            return

        password = generate_one_time_password()
        db.add(
            User(
                email=email,
                full_name=args.name.strip(),
                role=ROLE_ADMIN,
                hashed_password=hash_password(password),
                must_change_password=True,
            )
        )
        db.commit()
        print(f"Admin {email} created. One-time password on stdout.", file=sys.stderr)
        sys.stdout.write(password)


if __name__ == "__main__":
    main()
