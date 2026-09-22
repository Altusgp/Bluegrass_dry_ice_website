"""Bluegrass Dry Ice - Flask site.

Run locally:
    pip install -r requirements.txt
    python app.py
    -> http://127.0.0.1:5000
"""

import base64
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from email.message import EmailMessage
from functools import wraps
import json
import os
import secrets
import smtplib
import sqlite3
import time
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
import pymysql
from pymysql.cursors import DictCursor
import requests
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

MS_TENANT_ID = os.environ.get("MS_TENANT_ID")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET")
GRAPH_SENDER = os.environ.get("GRAPH_SENDER", SMTP_FROM)
GRAPH_SCOPE = os.environ.get("GRAPH_SCOPE", "https://graph.microsoft.com/.default")
GRAPH_API_BASE = os.environ.get("GRAPH_API_BASE", "https://graph.microsoft.com/v1.0")

ADMIN_ORDER_EMAIL = os.environ.get("ADMIN_ORDER_EMAIL", "info@dryiceky.com")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
stripe.api_key = STRIPE_SECRET_KEY

QB_CLIENT_ID = os.environ.get("QB_CLIENT_ID")
QB_CLIENT_SECRET = os.environ.get("QB_CLIENT_SECRET")
QB_ENVIRONMENT = os.environ.get("QB_ENVIRONMENT", "sandbox").lower()
QB_REDIRECT_URI = os.environ.get("QB_REDIRECT_URI")
QB_AUTH_BASE = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_PAYMENTS_API_BASE = (
    "https://sandbox.api.intuit.com" if QB_ENVIRONMENT == "sandbox" else "https://api.intuit.com"
)

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

ORDER_STATUSES = {
    "pending": {"label": "Pending", "message": "Your order has been received and is waiting to be processed."},
    "processing": {"label": "Processing", "message": "Your order is being processed."},
    "ready_for_pickup": {"label": "Ready for Pickup", "message": "Your order is ready for pickup!"},
    "picked_up": {"label": "Picked Up", "message": "Your order has been picked up. Thanks for choosing us!"},
    "cancelled": {"label": "Cancelled", "message": "Your order has been cancelled."},
}

# Pounds of dry ice consumed per day, per use case, before the container multiplier.
USE_RATES = {"ship": 8, "cooler": 6, "fog": 10, "freezer": 10}

PICKUP_IMAGE_CID = "pickup-instructions"
_pickup_image_cache = None


def get_pickup_image_bytes():
    global _pickup_image_cache
    if _pickup_image_cache is None:
        try:
            path = os.path.join(app.static_folder, "images", "DIKYPickup_Location_Image.png")
            with open(path, "rb") as f:
                _pickup_image_cache = f.read()
        except OSError:
            _pickup_image_cache = b""
    return _pickup_image_cache or None


_graph_token_cache = {"token": None, "expires_at": 0}


def _get_graph_token():
    now = time.time()
    if _graph_token_cache["token"] and now < _graph_token_cache["expires_at"] - 60:
        return _graph_token_cache["token"]
    resp = requests.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "scope": GRAPH_SCOPE,
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _graph_token_cache["token"] = data["access_token"]
    _graph_token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _graph_token_cache["token"]


def _send_via_graph(to_addr, subject, body, html=None, inline_images=None):
    token = _get_graph_token()
    message_body = {"contentType": "HTML", "content": html} if html else {"contentType": "Text", "content": body}
    message = {
        "subject": subject,
        "body": message_body,
        "toRecipients": [{"emailAddress": {"address": to_addr}}],
    }
    if inline_images:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": f"{cid}.png",
                "contentType": "image/png",
                "contentBytes": base64.b64encode(img_bytes).decode("ascii"),
                "isInline": True,
                "contentId": cid,
            }
            for cid, img_bytes in inline_images.items()
        ]
    resp = requests.post(
        f"{GRAPH_API_BASE}/users/{GRAPH_SENDER}/sendMail",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": message, "saveToSentItems": "false"},
        timeout=10,
    )
    resp.raise_for_status()


def send_email(to_addr, subject, body, html=None, inline_images=None):
    if EMAIL_BACKEND == "console":
        print(f"\n----- EMAIL (console backend) -----\nTo: {to_addr}\nSubject: {subject}\n\n{body}"
              f"{'  [+ HTML version]' if html else ''}"
              f"{'  [+ ' + str(len(inline_images)) + ' inline image(s)]' if inline_images else ''}"
              f"\n------------------------------------\n", flush=True)
        return
    if EMAIL_BACKEND == "graph":
        _send_via_graph(to_addr, subject, body, html=html, inline_images=inline_images)
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
        if inline_images:
            html_part = msg.get_payload()[-1]
            for cid, img_bytes in inline_images.items():
                html_part.add_related(img_bytes, "image", "png", cid=f"<{cid}>")
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


def get_admin_emails():
    rows = query_db("SELECT email FROM users WHERE is_admin = 1", fetchall=True)
    emails = {row["email"] for row in rows}
    if ADMIN_ORDER_EMAIL:
        emails.add(ADMIN_ORDER_EMAIL)
    return emails


def send_order_emails(order, customer_name, customer_email, customer_phone):
    order_history_url = url_for("order_history", _external=True)
    admin_orders_url = url_for("admin_orders", _external=True)

    items_lines = "\n".join(f"  {i['qty']} x {i['name']} - ${i['line_total']}" for i in order["items"])
    customer_text = (
        f"Thanks, {customer_name}!\n\nOrder {order['id']} is reserved.\n\n{items_lines}\n"
        f"  Container: {order['container']}\n  Subtotal: ${order['subtotal']:.2f}\n  Kentucky sales tax (6%): ${order['tax_amount']:.2f}\n  Total: ${order['total']:.2f}\n\n"
        f"Payment: {'Pay online' if order['payment'] == 'online' else 'Pay at pickup'} ({order['payment_status']})\n"
        + (f"Preferred pickup date: {order['pickup_date']}\n" if order["pickup_date"] else "")
        + f"\nPickup: {BUSINESS['street']}, {BUSINESS['city']}\nView your order: {order_history_url}"
    )
    pickup_image = get_pickup_image_bytes()
    try:
        send_email(
            customer_email,
            f"Your {BUSINESS['name']} order {order['id']}",
            customer_text,
            html=render_template(
                "email/order_customer.html", order=order, biz=BUSINESS,
                customer_name=customer_name, order_history_url=order_history_url,
                pickup_image_cid=PICKUP_IMAGE_CID if pickup_image else None,
            ),
            inline_images={PICKUP_IMAGE_CID: pickup_image} if pickup_image else None,
        )
    except Exception:
        pass

    admin_text = (
        f"New order {order['id']} from {customer_name} ({customer_email}, {customer_phone}).\n\n{items_lines}\n"
        f"  Container: {order['container']}\n  Subtotal: ${order['subtotal']:.2f}\n  Kentucky sales tax (6%): ${order['tax_amount']:.2f}\n  Total: ${order['total']:.2f}\n\n"
        f"Payment: {'Pay online' if order['payment'] == 'online' else 'Pay at pickup'} ({order['payment_status']})\n"
        + (f"Preferred pickup date: {order['pickup_date']}\n" if order["pickup_date"] else "")
        + (f"Notes: {order['notes']}\n" if order["notes"] else "")
        + f"\nAdmin panel: {admin_orders_url}"
    )
    admin_html = render_template(
        "email/order_admin.html", order=order, biz=BUSINESS,
        customer_name=customer_name, customer_email=customer_email, customer_phone=customer_phone,
        admin_orders_url=admin_orders_url,
    )
    for admin_email in get_admin_emails():
        try:
            send_email(admin_email, f"New order {order['id']} - {BUSINESS['name']}", admin_text, html=admin_html)
        except Exception:
            pass


def send_order_status_email(order, customer_name, customer_email):
    base_status = ORDER_STATUSES.get(order["order_status"])
    if not base_status:
        return
    status = dict(base_status)

    if order["order_status"] == "cancelled":
        reason = (order.get("cancel_reason") or "").strip()
        message = "We're sorry, your order has been cancelled."
        if reason:
            message += f" Reason: {reason}"
        if order.get("payment_status") == "paid":
            message += " Since this order was already paid, a refund will be processed."
        message += f" If you have any questions, please contact us at {BUSINESS['phone']} or {BUSINESS['email']}."
        status["message"] = message

    order_history_url = url_for("order_history", _external=True)
    text = (
        f"Hi {customer_name},\n\nOrder {order['id']} status: {status['label']}\n\n{status['message']}\n\n"
        f"View your order: {order_history_url}"
    )
    pickup_image = get_pickup_image_bytes() if order["order_status"] == "ready_for_pickup" else None
    try:
        send_email(
            customer_email,
            f"Order {order['id']} update: {status['label']} - {BUSINESS['name']}",
            text,
            html=render_template(
                "email/order_status.html", order=order, biz=BUSINESS, status=status,
                customer_name=customer_name, order_history_url=order_history_url,
                pickup_image_cid=PICKUP_IMAGE_CID if pickup_image else None,
            ),
            inline_images={PICKUP_IMAGE_CID: pickup_image} if pickup_image else None,
        )
    except Exception:
        pass


def _save_qb_tokens(data, realm_id=None):
    now = datetime.now()
    access_expires = (now + timedelta(seconds=data["expires_in"])).isoformat()
    refresh_expires = (now + timedelta(seconds=data["x_refresh_token_expires_in"])).isoformat()
    existing = query_db("SELECT id, realm_id FROM qb_tokens WHERE id = 1", fetchone=True)
    final_realm_id = realm_id or (existing["realm_id"] if existing else None)
    if existing:
        query_db(
            "UPDATE qb_tokens SET access_token=%s, refresh_token=%s, realm_id=%s, "
            "access_expires_at=%s, refresh_expires_at=%s WHERE id=1",
            (data["access_token"], data["refresh_token"], final_realm_id, access_expires, refresh_expires),
        )
    else:
        query_db(
            "INSERT INTO qb_tokens (id, access_token, refresh_token, realm_id, access_expires_at, refresh_expires_at) "
            "VALUES (1, %s, %s, %s, %s, %s)",
            (data["access_token"], data["refresh_token"], final_realm_id, access_expires, refresh_expires),
        )
    get_db().commit()


def get_qb_access_token():
    """Return (access_token, realm_id) for QuickBooks Payments, refreshing if needed. (None, None) if not connected."""
    row = query_db("SELECT * FROM qb_tokens WHERE id = 1", fetchone=True)
    if not row:
        return None, None
    if datetime.now() < datetime.fromisoformat(row["access_expires_at"]) - timedelta(minutes=2):
        return row["access_token"], row["realm_id"]

    resp = requests.post(
        QB_TOKEN_URL,
        auth=(QB_CLIENT_ID, QB_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        data={"grant_type": "refresh_token", "refresh_token": row["refresh_token"]},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _save_qb_tokens(data, realm_id=row["realm_id"])
    return data["access_token"], row["realm_id"]


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
                order_status VARCHAR(30) NOT NULL DEFAULT 'pending',
                cancel_reason VARCHAR(500) NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        if not column_exists(cursor, "orders", "pickup_date"):
            cursor.execute("ALTER TABLE orders ADD COLUMN pickup_date VARCHAR(20) NOT NULL DEFAULT ''")
        if not column_exists(cursor, "orders", "notes"):
            cursor.execute("ALTER TABLE orders ADD COLUMN notes VARCHAR(500) NOT NULL DEFAULT ''")
        if not column_exists(cursor, "orders", "order_status"):
            cursor.execute("ALTER TABLE orders ADD COLUMN order_status VARCHAR(30) NOT NULL DEFAULT 'pending'")
        if not column_exists(cursor, "orders", "cancel_reason"):
            cursor.execute("ALTER TABLE orders ADD COLUMN cancel_reason VARCHAR(500) NOT NULL DEFAULT ''")
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qb_tokens (
                id INT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                realm_id VARCHAR(50) NOT NULL,
                access_expires_at VARCHAR(30) NOT NULL,
                refresh_expires_at VARCHAR(30) NOT NULL
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
                order_status TEXT NOT NULL DEFAULT 'pending',
                cancel_reason TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS qb_tokens (
                id INTEGER PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                realm_id TEXT NOT NULL,
                access_expires_at TEXT NOT NULL,
                refresh_expires_at TEXT NOT NULL
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
        if not column_exists(cursor, "orders", "order_status"):
            cursor.execute("ALTER TABLE orders ADD COLUMN order_status TEXT NOT NULL DEFAULT 'pending'")
        if not column_exists(cursor, "orders", "cancel_reason"):
            cursor.execute("ALTER TABLE orders ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''")
    for field in ("subtotal", "tax_amount"):
        if not column_exists(cursor, "orders", field):
            field_type = "DECIMAL(10, 2)" if DB_BACKEND == "mysql" else "REAL"
            cursor.execute(f"ALTER TABLE orders ADD COLUMN {field} {field_type} NOT NULL DEFAULT 0")
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
        return redirect(session.pop("order_return", None) or url_for("account"))

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
    destination = request.form.get("next") or request.args.get("next") or ""
    if not destination.startswith("/") or destination.startswith("//") or "\\" in destination:
        destination = ""
    if destination == "/#order":
        session["order_return"] = destination
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = query_db("SELECT * FROM users WHERE email = %s", (email,), fetchone=True)
        if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            return render_template("auth.html", mode="login", next=destination, error="Email or password is incorrect.")
        session.clear()
        session["user_id"] = user["id"]
        return redirect(destination or url_for("account"))
    return render_template("auth.html", mode="login", next=destination)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = query_db("SELECT id FROM users WHERE email = %s", (email,), fetchone=True)
        if user:
            code = f"{secrets.randbelow(1_000_000):06d}"
            session["password_reset"] = {
                "user_id": user["id"],
                "email": email,
                "code": code,
                "expires_at": (datetime.now() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat(),
                "attempts": 0,
            }
            try:
                send_email(
                    email,
                    f"Your {BUSINESS['name']} password reset code",
                    f"Your password reset code is {code}.\n\nIt expires in {OTP_TTL_MINUTES} minutes. "
                    "If you didn't request this, you can ignore this email.",
                )
            except Exception:
                session.pop("password_reset", None)
        return redirect(url_for("reset_password", email=email))
    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    pending = session.get("password_reset")
    email = pending["email"] if pending else request.args.get("email", "")

    if request.method == "POST":
        if not pending:
            return render_template("reset_password.html", email=email, error="That code has expired. Please request a new one.")

        code = request.form.get("code", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if datetime.now() > datetime.fromisoformat(pending["expires_at"]):
            session.pop("password_reset", None)
            return render_template("forgot_password.html", error="That code expired. Please request a new one.")

        if code != pending["code"]:
            pending["attempts"] += 1
            if pending["attempts"] >= OTP_MAX_ATTEMPTS:
                session.pop("password_reset", None)
                return render_template("forgot_password.html", error="Too many incorrect attempts. Please start over.")
            session["password_reset"] = pending
            return render_template("reset_password.html", email=email, error="Incorrect code. Please try again.")

        if new_password != confirm_password:
            return render_template("reset_password.html", email=email, error="New password and confirmation don't match.")
        if len(new_password) < 8:
            return render_template("reset_password.html", email=email, error="Password must be at least 8 characters.")

        query_db(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new_password), pending["user_id"]),
        )
        get_db().commit()
        session.pop("password_reset", None)
        return render_template("auth.html", mode="login", notice="Your password was reset. Please sign in.")

    return render_template("reset_password.html", email=email)


@app.post("/forgot-password/resend")
def resend_reset_code():
    pending = session.get("password_reset")
    if not pending:
        return redirect(url_for("forgot_password"))

    code = f"{secrets.randbelow(1_000_000):06d}"
    pending["code"] = code
    pending["expires_at"] = (datetime.now() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
    pending["attempts"] = 0
    session["password_reset"] = pending

    try:
        send_email(
            pending["email"],
            f"Your {BUSINESS['name']} password reset code",
            f"Your password reset code is {code}.\n\nIt expires in {OTP_TTL_MINUTES} minutes. "
            "If you didn't request this, you can ignore this email.",
        )
    except Exception:
        return render_template("reset_password.html", email=pending["email"], error="Couldn't resend the code. Please try again in a moment.")

    return render_template("reset_password.html", email=pending["email"], notice="A new code was sent.")


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
    return render_template("orders.html", orders=orders, statuses=ORDER_STATUSES, active="orders")


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
    if data.get("payment", "pickup") != "pickup":
        return jsonify(ok=False, error="Online payment is unavailable. Please choose Pay at pickup."), 400
    payment = "pickup"
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

    subtotal = Decimal(str(bag_total)) + Decimal(str(container["price"]))
    tax_amount = (subtotal * Decimal("0.06")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    order_id = "BDI-" + uuid4().hex[:6].upper()
    order = {
        "id": order_id,
        "placed_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "total_lbs": total_lbs,
        "container": container["label"],
        "payment": payment,
        "payment_status": "unpaid",
        "subtotal": float(subtotal),
        "tax_amount": float(tax_amount),
        "total": float(subtotal + tax_amount),
        "pickup_date": pickup_date,
        "notes": notes,
    }
    query_db(
        """INSERT INTO orders
           (id, user_id, placed_at, items_json, total_lbs, container,
            payment_method, payment_status, total, pickup_date, notes, subtotal, tax_amount)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (order_id, session["user_id"], order["placed_at"], json.dumps(items),
         total_lbs, order["container"], payment, order["payment_status"], order["total"],
         pickup_date, notes, order["subtotal"], order["tax_amount"]),
    )
    if data.get("save_billing") and all(billing[key] for key in ("line1", "city", "state", "zip")):
        query_db(
            """INSERT INTO addresses (user_id, label, line1, line2, city, state, zip)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (session["user_id"], "Billing", billing["line1"], billing["line2"],
             billing["city"], billing["state"], billing["zip"]),
        )
    get_db().commit()

    send_order_emails(
        order,
        data.get("name") or "",
        data.get("email") or "",
        data.get("phone") or "",
    )

    checkout_url = None

    return jsonify(
        ok=True,
        order=order,
        checkout_url=checkout_url,
        message=f"Order {order_id} reserved. Total ${order['total']:.2f}.",
    )


@app.get("/order/<order_id>/confirm")
@login_required
def order_confirmation(order_id):
    order = query_db(
        "SELECT * FROM orders WHERE id = %s AND user_id = %s", (order_id, session["user_id"]), fetchone=True
    )
    if not order:
        abort(404)

    session_id = request.args.get("session_id")
    if session_id and order["payment_status"] != "paid" and STRIPE_SECRET_KEY:
        try:
            checkout_session = stripe.checkout.Session.retrieve(session_id)
            if (checkout_session.payment_status == "paid"
                    and checkout_session.metadata.get("order_id") == order_id):
                query_db("UPDATE orders SET payment_status = %s WHERE id = %s", ("paid", order_id))
                get_db().commit()
                order = query_db("SELECT * FROM orders WHERE id = %s", (order_id,), fetchone=True)
        except Exception:
            pass

    return render_template("order_confirmation.html", order=order)


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
            "subtotal": row["subtotal"],
            "tax_amount": row["tax_amount"],
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


@app.get("/admin/quickbooks")
@admin_required
def admin_quickbooks():
    token_row = query_db("SELECT realm_id, refresh_expires_at FROM qb_tokens WHERE id = 1", fetchone=True)
    return render_template(
        "admin_quickbooks.html", active="quickbooks", token=token_row,
        configured=bool(QB_CLIENT_ID and QB_CLIENT_SECRET and QB_REDIRECT_URI),
    )


@app.get("/admin/quickbooks/connect")
@admin_required
def qb_connect():
    from urllib.parse import urlencode
    state = secrets.token_urlsafe(16)
    session["qb_oauth_state"] = state
    params = {
        "client_id": QB_CLIENT_ID,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.payment",
        "redirect_uri": QB_REDIRECT_URI,
        "state": state,
    }
    return redirect(f"{QB_AUTH_BASE}?{urlencode(params)}")


@app.get("/admin/quickbooks/callback")
@admin_required
def qb_callback():
    if not request.args.get("state") or request.args.get("state") != session.pop("qb_oauth_state", None):
        abort(400)
    code = request.args.get("code")
    realm_id = request.args.get("realmId")
    if not code or not realm_id:
        return redirect(url_for("admin_quickbooks"))

    resp = requests.post(
        QB_TOKEN_URL,
        auth=(QB_CLIENT_ID, QB_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": QB_REDIRECT_URI},
        timeout=10,
    )
    resp.raise_for_status()
    _save_qb_tokens(resp.json(), realm_id=realm_id)
    return redirect(url_for("admin_quickbooks"))


@app.post("/admin/quickbooks/disconnect")
@admin_required
def qb_disconnect():
    query_db("DELETE FROM qb_tokens WHERE id = 1")
    get_db().commit()
    return redirect(url_for("admin_quickbooks"))


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
        """SELECT orders.*, users.email AS user_email, users.name AS user_name FROM orders
           JOIN users ON users.id = orders.user_id ORDER BY placed_at DESC""",
        fetchall=True,
    )
    return render_template("admin_orders.html", orders=rows, statuses=ORDER_STATUSES, active="orders")


@app.post("/admin/orders/<order_id>/delete")
@admin_required
def admin_delete_order(order_id):
    query_db("DELETE FROM orders WHERE id = %s", (order_id,))
    get_db().commit()
    return redirect(url_for("admin_orders"))


@app.post("/admin/orders/<order_id>/status")
@admin_required
def admin_update_order_status(order_id):
    new_status = request.form.get("order_status", "")
    reason = request.form.get("reason", "").strip()[:500]
    if new_status not in ORDER_STATUSES:
        abort(400)

    order_row = query_db(
        """SELECT orders.*, users.email AS user_email, users.name AS user_name FROM orders
           JOIN users ON users.id = orders.user_id WHERE orders.id = %s""",
        (order_id,), fetchone=True,
    )
    if not order_row:
        abort(404)

    if new_status == "cancelled":
        query_db(
            "UPDATE orders SET order_status = %s, cancel_reason = %s WHERE id = %s",
            (new_status, reason, order_id),
        )
    else:
        query_db("UPDATE orders SET order_status = %s WHERE id = %s", (new_status, order_id))
    get_db().commit()

    order = dict(order_row)
    order["order_status"] = new_status
    order["cancel_reason"] = reason if new_status == "cancelled" else order.get("cancel_reason", "")
    order["items"] = json.loads(order["items_json"])
    send_order_status_email(order, order["user_name"], order["user_email"])

    return redirect(url_for("admin_orders"))


@app.post("/admin/orders/<order_id>/payment-status")
@admin_required
def admin_update_payment_status(order_id):
    new_status = request.form.get("payment_status", "")
    if new_status not in ("unpaid", "paid"):
        abort(400)

    order_row = query_db("SELECT id FROM orders WHERE id = %s", (order_id,), fetchone=True)
    if not order_row:
        abort(404)

    query_db("UPDATE orders SET payment_status = %s WHERE id = %s", (new_status, order_id))
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
