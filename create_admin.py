"""One-off script to create an admin account, or promote an existing one.

Run: python create_admin.py
"""
import getpass
from datetime import datetime

from werkzeug.security import generate_password_hash

from app import app, get_db, init_db, query_db


def main():
    with app.app_context():
        init_db()

        email = input("Admin email: ").strip().lower()
        existing = query_db("SELECT id, is_admin FROM users WHERE email = %s", (email,), fetchone=True)

        if existing:
            if existing["is_admin"]:
                print(f"{email} is already an admin.")
                return
            query_db("UPDATE users SET is_admin = 1 WHERE email = %s", (email,))
            get_db().commit()
            print(f"{email} is now an admin.")
            return

        name = input("Name: ").strip()
        phone = input("Phone: ").strip()
        password = getpass.getpass("Password (min 8 chars): ")
        if len(password) < 8:
            print("Password must be at least 8 characters. Aborted.")
            return

        query_db(
            """INSERT INTO users (name, email, phone, password_hash, created_at, is_admin)
               VALUES (%s, %s, %s, %s, %s, 1)""",
            (name, email, phone, generate_password_hash(password), datetime.now().isoformat(timespec="seconds")),
        )
        get_db().commit()
        print(f"Admin account created for {email}.")


if __name__ == "__main__":
    main()
