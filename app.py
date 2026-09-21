"""Bluegrass Dry Ice - Flask site.

Run locally:
    pip install -r requirements.txt
    python app.py
    -> http://127.0.0.1:5000
"""

from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
import json
import os
import secrets
import smtplib
import sqlite3
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
import pymysql
from pymysql.cursors import DictCursor
import stripe
from werkzeug.security import check_password_hash, generate_password_hash
from content import BAGS, BUSINESS, CONTAINERS, FAQS, GUIDES, SAFETY_RULES, USE_CASES, WONT_DO

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-development-secret-change-me")

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "dryice_user"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "dryice"),
    "cursorclass": DictCursor,
    "autocommit": False,
}
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()
SQLITE_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "bluegrass.db"))

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "smtp").lower()
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

# Pounds of dry ice consumed per day, per use case, before the container multiplier.
USE_RATES = {"ship": 8, "cooler": 6, "fog": 10, "freezer": 10}


def send_email(to_addr, subject, body):
    if EMAIL_BACKEND == "console":
        print(f"\n----- EMAIL (console backend) -----\nTo: {to_addr}\nSubject: {subject}\n\n{body}\n------------------------------------\n", flush=True)
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg.set_content(body)
    smtp_class = smtplib.SMTP_SSL if SMTP_USE_SSL else smtplib.SMTP
    with smtp_class(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        if not SMTP_USE_SSL:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


def send_otp_email(to_addr, code):
    send_email(
        to_addr,
        f"Your {BUSINESS['name']} verification code",
        f"Your verification code is {code}.\n\nIt expires in {OTP_TTL_MINUTES} minutes. "
        "If you didn't request this, you can ignore this email.",
    )


def column_exists(cursor, table, column):
    if DB_BACKEND == "mysql":
        cursor.execute(
            "SELECT COUNT(*) AS c FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
            (table, column),
        )
        row = cursor.fetchone()
        return (row["c"] if isinstance(row, dict) else row[0]) > 0
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cursor.fetchall())

def get_db():
    if "db" not in g:
        if DB_BACKEND == "mysql":
            g.db = pymysql.connect(**DB_CONFIG)
        else:
            g.db = sqlite3.connect(SQLITE_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def query_db(sql, params=(), fetchone=False, fetchall=False):
    if DB_BACKEND != "mysql":
        sql = sql.replace("%s", "?")
    cursor = get_db().cursor()
    cursor.execute(sql, params)
    if fetchone:
        return cursor.fetchone()
    if fetchall:
        return cursor.fetchall()
    return cursor


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    cursor = db.cursor()
    if DB_BACKEND == "mysql":
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                phone VARCHAR(30) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at VARCHAR(30) NOT NULL,
                is_admin TINYINT(1) NOT NULL DEFAULT 0
            )
        """)
        if not column_exists(cursor, "users", "phone"):
            cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(30) NOT NULL DEFAULT ''")
        if not column_exists(cursor, "users", "is_admin"):
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id VARCHAR(20) PRIMARY KEY,
                user_id INT NOT NULL,
                placed_at VARCHAR(30) NOT NULL,
                items_json TEXT NOT NULL,
                total_lbs INT NOT NULL,
                container VARCHAR(255) NOT NULL,
                payment_method VARCHAR(50) NOT NULL,
                payment_status VARCHAR(50) NOT NULL,
                total DECIMAL(10, 2) NOT NULL,
                pickup_date VARCHAR(20) NOT NULL DEFAULT '',
                notes VARCHAR(500) NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        if not column_exists(cursor, "orders", "pickup_date"):
            cursor.execute("ALTER TABLE orders ADD COLUMN pickup_date VARCHAR(20) NOT NULL DEFAULT ''")
        if not column_exists(cursor, "orders", "notes"):
            cursor.execute("ALTER TABLE orders ADD COLUMN notes VARCHAR(500) NOT NULL DEFAULT ''")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS addresses (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                label VARCHAR(50) NOT NULL,
                line1 VARCHAR(255) NOT NULL,
                line2 VARCHAR(255) NOT NULL DEFAULT '',
                city VARCHAR(100) NOT NULL,
                state VARCHAR(50) NOT NULL,
                zip VARCHAR(20) NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
    else:
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                placed_at TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_lbs INTEGER NOT NULL,
                container TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                total REAL NOT NULL,
                pickup_date TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
            CREATE TABLE IF NOT EXISTS addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                line1 TEXT NOT NULL,
                line2 TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL,
                state TEXT NOT NULL,
                zip TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
        """)
        if not column_exists(cursor, "users", "phone"):
            cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
        if not column_exists(cursor, "users", "is_admin"):
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if not column_exists(cursor, "orders", "pickup_date"):
            cursor.execute("ALTER TABLE orders ADD COLUMN pickup_date TEXT NOT NULL DEFAULT ''")
        if not column_exists(cursor, "orders", "notes"):
            cursor.execute("ALTER TABLE orders ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
    db.commit()


@app.context_processor
def inject_user():
    user = None
    if session.get("user_id"):
        user = query_db(
            "SELECT id, name, email, phone, is_admin FROM users WHERE id = %s", (session["user_id"],), fetchone=True
        )
    return {"current_user": user}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Please sign in before placing an order."), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        user = query_db("SELECT is_admin FROM users WHERE id = %s", (session["user_id"],), fetchone=True)
        if not user or not user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@app.before_request
def ensure_database():
    init_db()


@app.route("/")
def home():
    use_cases_with_images = [
        {
            **use_case,
            "image_exists": os.path.exists(
                os.path.join(app.static_folder, "images", use_case["image"])
            ),
        }
        for use_case in USE_CASES
    ]
    return render_template(
        "index.html",
        bags=BAGS,
        containers=CONTAINERS,
        use_cases=use_cases_with_images,
        safety_rules=SAFETY_RULES,
        wont_do=WONT_DO,
        guides=GUIDES,
        faqs=FAQS,
        biz=BUSINESS,
        year=datetime.now().year,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        form = {"name": name, "email": email, "phone": phone}

        if not name or not email or len(phone) < 7 or len(password) < 8:
            return render_template(
                "auth.html", mode="register", form=form,
                error="Enter your name, email, phone number, and a password of at least 8 characters.",
            )

        existing = query_db("SELECT id FROM users WHERE email = %s", (email,), fetchone=True)
        if existing:
            return render_template("auth.html", mode="register", form=form, error="An account with that email already exists.")

        code = f"{secrets.randbelow(1_000_000):06d}"
        session["pending_registration"] = {
            "name": name,
            "email": email,
            "phone": phone,
            "password_hash": generate_password_hash(password),
            "code": code,
            "expires_at": (datetime.now() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat(),
            "attempts": 0,
        }

        try:
            send_otp_email(email, code)
        except Exception:
            app.logger.exception("Could not send registration OTP email to %s", email)
            session.pop("pending_registration", None)
            return render_template(
                "auth.html", mode="register", form=form,
                error="We couldn't send a verification email right now. Please try again in a moment.",
            )

        return redirect(url_for("verify_otp"))
    return render_template("auth.html", mode="register")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    pending = session.get("pending_registration")
    if not pending:
        return redirect(url_for("register"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        if datetime.now() > datetime.fromisoformat(pending["expires_at"]):
            session.pop("pending_registration", None)
            return render_template("auth.html", mode="register", error="That code expired. Please register again.")

        if code != pending["code"]:
            pending["attempts"] += 1
            if pending["attempts"] >= OTP_MAX_ATTEMPTS:
                session.pop("pending_registration", None)
                return render_template("auth.html", mode="register", error="Too many incorrect attempts. Please register again.")
            session["pending_registration"] = pending
            return render_template("verify_otp.html", email=pending["email"], error="Incorrect code. Please try again.")

        try:
            cursor = query_db(
                "INSERT INTO users (name, email, phone, password_hash, created_at) VALUES (%s, %s, %s, %s, %s)",
                (pending["name"], pending["email"], pending["phone"], pending["password_hash"],
                 datetime.now().isoformat(timespec="seconds")),
            )
            get_db().commit()
        except (pymysql.err.IntegrityError, sqlite3.IntegrityError):
            session.pop("pending_registration", None)
            return render_template("auth.html", mode="register", error="An account with that email already exists.")

        session.pop("pending_registration", None)
        session["user_id"] = cursor.lastrowid
        return redirect(url_for("account"))

    return render_template("verify_otp.html", email=pending["email"])


@app.post("/verify-otp/resend")
def resend_otp():
    pending = session.get("pending_registration")
    if not pending:
        return redirect(url_for("register"))

    code = f"{secrets.randbelow(1_000_000):06d}"
    pending["code"] = code
    pending["expires_at"] = (datetime.now() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
    pending["attempts"] = 0
    session["pending_registration"] = pending

    try:
        send_otp_email(pending["email"], code)
    except Exception:
        app.logger.exception("Could not resend registration OTP email to %s", pending["email"])
        return render_template("verify_otp.html", email=pending["email"], error="Couldn't resend the code. Please try again in a moment.")

    return render_template("verify_otp.html", email=pending["email"], notice="A new code was sent.")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = query_db("SELECT * FROM users WHERE email = %s", (email,), fetchone=True)
        if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            return render_template("auth.html", mode="login", error="Email or password is incorrect.")
        session.clear()
        session["user_id"] = user["id"]
        return redirect(request.form.get("next") or url_for("account"))
    return render_template("auth.html", mode="login", next=request.args.get("next", ""))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/account")
@login_required
def account():
    return render_template("account.html", active="dashboard")


@app.get("/orders")
@login_required
def order_history():
    orders = query_db(
        "SELECT * FROM orders WHERE user_id = %s ORDER BY placed_at DESC", (session["user_id"],), fetchall=True
    )
    return render_template("orders.html", orders=orders, active="orders")


@app.route("/account/addresses", methods=["GET", "POST"])
@login_required
def addresses():
    error = None
    if request.method == "POST":
        label = request.form.get("label", "").strip()
        line1 = request.form.get("line1", "").strip()
        line2 = request.form.get("line2", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        zip_code = request.form.get("zip", "").strip()

        if not label or not line1 or not city or not state or not zip_code:
            error = "Please fill in label, address line 1, city, state, and ZIP."
        else:
            query_db(
                """INSERT INTO addresses (user_id, label, line1, line2, city, state, zip)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (session["user_id"], label, line1, line2, city, state, zip_code),
            )
            get_db().commit()

    rows = query_db(
        "SELECT * FROM addresses WHERE user_id = %s ORDER BY id DESC", (session["user_id"],), fetchall=True
    )
    return render_template("addresses.html", addresses=rows, error=error, active="addresses")


@app.post("/account/addresses/<int:address_id>/delete")
@login_required
def delete_address(address_id):
    query_db(
        "DELETE FROM addresses WHERE id = %s AND user_id = %s", (address_id, session["user_id"])
    )
    get_db().commit()
    return redirect(url_for("addresses"))


@app.get("/account/payment-methods")
@login_required
def payment_methods():
    return render_template("payment_methods.html", active="payment")


@app.route("/account/details", methods=["GET", "POST"])
@login_required
def account_details():
    error = None
    success = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or len(phone) < 7:
            error = "Name, email, and phone are required."
        elif new_password and new_password != confirm_password:
            error = "New password and confirmation don't match."
        elif new_password and len(new_password) < 8:
            error = "New password must be at least 8 characters."
        else:
            existing = query_db(
                "SELECT id FROM users WHERE email = %s AND id != %s", (email, session["user_id"]), fetchone=True
            )
            if existing:
                error = "Another account already uses that email."
            else:
                try:
                    if new_password:
                        query_db(
                            "UPDATE users SET name = %s, email = %s, phone = %s, password_hash = %s WHERE id = %s",
                            (name, email, phone, generate_password_hash(new_password), session["user_id"]),
                        )
                    else:
                        query_db(
                            "UPDATE users SET name = %s, email = %s, phone = %s WHERE id = %s",
                            (name, email, phone, session["user_id"]),
                        )
                    get_db().commit()
                    success = "Your account details were updated."
                except (pymysql.err.IntegrityError, sqlite3.IntegrityError):
                    error = "Another account already uses that email."

    return render_template("account_details.html", error=error, success=success, active="details")


def estimate_pounds(use: str, days: float, size: float) -> dict:
    """Return a practical starting range plus the closest bag we stock."""
    rate = USE_RATES.get(use, 8)
    raw = max(5.0, rate * days * size)

    low = max(5, int(round(raw / 5.0) * 5))
    high = low + max(5, int(round(low * 0.15 / 5.0) * 5))

    bag = next((b for b in BAGS if b["lbs"] >= high), BAGS[-1])
    return {
        "low": low,
        "high": high,
        "range_label": f"{low}–{high} lb",
        "bag": bag,
    }


@app.post("/api/estimate")
def api_estimate():
    data = request.get_json(silent=True) or {}
    try:
        days = float(data.get("days", 1))
        size = float(data.get("size", 1.4))
    except (TypeError, ValueError):
        return jsonify(error="days and size must be numbers"), 400

    result = estimate_pounds(str(data.get("use", "ship")), days, size)
    result["copy"] = (
        "A practical starting range for this use and duration. The "
        f"{result['bag']['name']} (${result['bag']['price']}) is the closest size we stock — "
        "choose the next size up if you want a safety margin."
    )
    return jsonify(result)


@app.post("/api/order")
@login_required
def api_order():
    """Validate a pickup order. Wire a real payment provider in here before launch."""
    data = request.get_json(silent=True) or {}
    raw_items = data.get("items") or {}

    items, bag_total, total_lbs = [], 0, 0
    for index, bag in enumerate(BAGS):
        try:
            count = int(raw_items.get(str(index), 0))
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            line = count * bag["price"]
            bag_total += line
            total_lbs += count * bag["lbs"]
            items.append({"name": bag["name"], "qty": count, "line_total": line})

    if not items:
        return jsonify(ok=False, error="Add at least one bag first."), 400

    if not all(data.get(key) for key in ("age", "airtight", "safety")):
        return jsonify(ok=False, error="Please confirm all three safety checkboxes."), 400

    container = next(
        (c for c in CONTAINERS if str(c["price"]) == str(data.get("container", "0"))),
        CONTAINERS[0],
    )
    payment = "online" if data.get("payment") == "online" else "pickup"
    pickup_date = str(data.get("pickup_date", ""))[:20]
    notes = str(data.get("notes", ""))[:500]
    billing = {
        "line1": str(data.get("billing_line1", "")).strip()[:255],
        "line2": str(data.get("billing_line2", "")).strip()[:255],
        "city": str(data.get("billing_city", "")).strip()[:100],
        "state": str(data.get("billing_state", "")).strip()[:50],
        "zip": str(data.get("billing_zip", "")).strip()[:20],
    }
    if payment == "online" and not all(billing[key] for key in ("line1", "city", "state", "zip")):
        return jsonify(ok=False, error="Billing address is required for online payment."), 400

    order_id = "BDI-" + uuid4().hex[:6].upper()
    order = {
        "id": order_id,
        "placed_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "total_lbs": total_lbs,
        "container": container["label"],
        "payment": payment,
        "payment_status": "unpaid",
        "total": round(bag_total + container["price"], 2),
        "pickup_date": pickup_date,
        "notes": notes,
    }
    query_db(
        """INSERT INTO orders
           (id, user_id, placed_at, items_json, total_lbs, container,
            payment_method, payment_status, total, pickup_date, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (order_id, session["user_id"], order["placed_at"], json.dumps(items),
         total_lbs, order["container"], payment, order["payment_status"], order["total"],
         pickup_date, notes),
    )
    if data.get("save_billing") and all(billing[key] for key in ("line1", "city", "state", "zip")):
        query_db(
            """INSERT INTO addresses (user_id, label, line1, line2, city, state, zip)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (session["user_id"], "Billing", billing["line1"], billing["line2"],
             billing["city"], billing["state"], billing["zip"]),
        )
    get_db().commit()

    return jsonify(
        ok=True,
        order=order,
        message=f"Order {order_id} reserved. Total ${order['total']:.2f}.",
    )


@app.get("/api/orders")
def api_orders():
    """Return orders for the signed-in user."""
    rows = query_db(
        "SELECT * FROM orders WHERE user_id = %s ORDER BY placed_at DESC", (session["user_id"],), fetchall=True
    )
    orders = []
    for row in rows:
        orders.append({
            "id": row["id"],
            "placed_at": row["placed_at"],
            "items": json.loads(row["items_json"]),
            "total_lbs": row["total_lbs"],
            "container": row["container"],
            "payment": row["payment_method"],
            "payment_status": row["payment_status"],
            "total": row["total"],
        })
    return jsonify(count=len(orders), orders=orders)


@app.get("/admin")
@app.get("/admin/")
@admin_required
def admin_dashboard():
    counts = {
        "users": query_db("SELECT COUNT(*) AS c FROM users", fetchone=True)["c"],
        "orders": query_db("SELECT COUNT(*) AS c FROM orders", fetchone=True)["c"],
        "addresses": query_db("SELECT COUNT(*) AS c FROM addresses", fetchone=True)["c"],
    }
    return render_template("admin_dashboard.html", counts=counts, active="dashboard")


@app.get("/admin/users")
@admin_required
def admin_users():
    rows = query_db("SELECT * FROM users ORDER BY id DESC", fetchall=True)
    return render_template("admin_users.html", users=rows, active="users")


@app.post("/admin/users/<int:user_id>/delete")
@admin_required
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        abort(400)
    query_db("DELETE FROM addresses WHERE user_id = %s", (user_id,))
    query_db("DELETE FROM orders WHERE user_id = %s", (user_id,))
    query_db("DELETE FROM users WHERE id = %s", (user_id,))
    get_db().commit()
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/toggle-admin")
@admin_required
def admin_toggle_user_admin(user_id):
    if user_id == session["user_id"]:
        abort(400)
    user = query_db("SELECT is_admin FROM users WHERE id = %s", (user_id,), fetchone=True)
    if user:
        query_db("UPDATE users SET is_admin = %s WHERE id = %s", (0 if user["is_admin"] else 1, user_id))
        get_db().commit()
    return redirect(url_for("admin_users"))


@app.get("/admin/orders")
@admin_required
def admin_orders():
    rows = query_db(
        """SELECT orders.*, users.email AS user_email FROM orders
           JOIN users ON users.id = orders.user_id ORDER BY placed_at DESC""",
        fetchall=True,
    )
    return render_template("admin_orders.html", orders=rows, active="orders")


@app.post("/admin/orders/<order_id>/delete")
@admin_required
def admin_delete_order(order_id):
    query_db("DELETE FROM orders WHERE id = %s", (order_id,))
    get_db().commit()
    return redirect(url_for("admin_orders"))


@app.get("/admin/addresses")
@admin_required
def admin_addresses():
    rows = query_db(
        """SELECT addresses.*, users.email AS user_email FROM addresses
           JOIN users ON users.id = addresses.user_id ORDER BY addresses.id DESC""",
        fetchall=True,
    )
    return render_template("admin_addresses.html", addresses=rows, active="addresses")


@app.post("/admin/addresses/<int:address_id>/delete")
@admin_required
def admin_delete_address(address_id):
    query_db("DELETE FROM addresses WHERE id = %s", (address_id,))
    get_db().commit()
    return redirect(url_for("admin_addresses"))


if __name__ == "__main__":
    app.run(
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=int(os.environ.get("APP_PORT", "5005")),
        debug=False,
    )
