"""Provision a TrustGate account for a trusted administrator in a local/single-tenant deployment."""
import argparse
import getpass
import secrets
import sys

import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True, help="Login username or email")
    parser.add_argument("--name", required=True, help="Display name")
    parser.add_argument("--role", choices=("creator", "reviewer", "admin"), required=True)
    args = parser.parse_args()
    username = args.username.strip().lower()
    name = " ".join(args.name.split())[:40]
    password = getpass.getpass("New password (8-128 characters): ")
    if len(password) < 8 or len(password) > 128 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        print("Password must be 8-128 characters and include a letter and a number.", file=sys.stderr)
        return 2
    if app.one("SELECT 1 FROM users WHERE username=? OR lower(name)=?", (username, name.lower())):
        print("That username or display name already exists.", file=sys.stderr)
        return 2
    salt = secrets.token_bytes(16)
    app.ins("INSERT INTO users(username,name,role,salt,pwd_hash) VALUES(?,?,?,?,?)",
            (username, name, args.role, salt.hex(), app.hash_pw(password, salt)))
    app.log(name, args.role, "account provisioned", "Created using create_user.py")
    print(f"Created {args.role} account for {name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
