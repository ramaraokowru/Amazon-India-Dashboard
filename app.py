"""Amazon India Dashboard Flask application.

Run locally with: python app.py
The dashboard is served by Flask and all private data APIs require a login session.
"""
import os
import re
import sqlite3
from functools import wraps
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
# Load local configuration from a .env file beside app.py (if present).
load_dotenv(BASE / ".env", override=False)

DATA_FILE = Path(os.environ.get("DATA_FILE", str(BASE / "data" / "Amazon_Sales_Data_India.xlsx")))
DB_FILE = Path(os.environ.get("DB_FILE", str(BASE / "users.db")))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

app = Flask(__name__, static_folder="static", static_url_path="")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-key-change-before-deploying"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REQUIRED_COLUMNS = {
    "Order_Date", "Category", "Product", "Quantity", "Total_Sales_INR", "Profit_INR",
    "Payment_Method", "Fulfillment", "Order_Status", "Ship_State"
}


def load_data() -> pd.DataFrame:
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"Sales workbook not found: {DATA_FILE}. Place Amazon_Sales_Data_India.xlsx in the data folder "
            "or set DATA_FILE to its location."
        )
    frame = pd.read_excel(DATA_FILE)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError("Sales workbook is missing required columns: " + ", ".join(sorted(missing)))
    frame["Order_Date"] = pd.to_datetime(frame["Order_Date"], errors="coerce")
    frame = frame.dropna(subset=["Order_Date"]).copy()
    for col in ["Quantity", "Total_Sales_INR", "Profit_INR"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0)
    for col in ["Category", "Product", "Payment_Method", "Fulfillment", "Order_Status", "Ship_State"]:
        frame[col] = frame[col].fillna("Unknown").astype(str)
    if "Order_ID" not in frame.columns:
        frame["Order_ID"] = [f"ORDER-{i+1}" for i in range(len(frame))]
    frame["Month"] = frame["Order_Date"].dt.strftime("%Y-%m")
    frame["Year"] = frame["Month"].str[:4]
    return frame


def build_payload(frame: pd.DataFrame) -> dict:
    def index_values(column):
        values = sorted(frame[column].dropna().unique().tolist())
        return values, {value: i for i, value in enumerate(values)}

    months, month_i = index_values("Month")
    categories, category_i = index_values("Category")
    products, product_i = index_values("Product")
    payments, payment_i = index_values("Payment_Method")
    fulfillment, fulfillment_i = index_values("Fulfillment")
    statuses, status_i = index_values("Order_Status")
    states, state_i = index_values("Ship_State")
    product_category = frame.groupby("Product")["Category"].first().to_dict()
    rows = []
    for row in frame.itertuples(index=False):
        rows.append([
            month_i[row.Month], category_i[row.Category], product_i[row.Product], int(row.Quantity),
            round(float(row.Total_Sales_INR), 2), round(float(row.Profit_INR), 2),
            payment_i[row.Payment_Method], fulfillment_i[row.Fulfillment],
            status_i[row.Order_Status], state_i[row.Ship_State],
        ])
    return {
        "m": months, "c": categories, "p": products, "y": payments, "f": fulfillment,
        "s": statuses, "t": states, "r": rows,
        "pc": [category_i[product_category[p]] for p in products],
    }


DF = load_data()
PAYLOAD = build_payload(DF)


def db():
    if "db" not in g:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            pw_hash TEXT, picture TEXT, provider TEXT NOT NULL DEFAULT 'password')""")


init_db()


def name_from_email(email: str) -> str:
    base = re.sub(r"[._\d]+", " ", email.split("@")[0]).strip() or "User"
    return base.title()


def public(user) -> dict:
    return {"name": user["name"], "email": user["email"], "picture": user["picture"]}


def current_user():
    uid = session.get("uid")
    return db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify(error="Please sign in."), 401
        return fn(*args, **kwargs)
    return wrapper


def start_session(user):
    session.clear()
    session["uid"] = user["id"]
    session.permanent = True


def error(message, status=400):
    return jsonify(error=message), status


@app.get("/api/health")
def health():
    return jsonify(ok=True, service="amazon-india-dashboard")


@app.get("/api/config")
def config():
    return jsonify(googleClientId=GOOGLE_CLIENT_ID, googleEnabled=bool(GOOGLE_CLIENT_ID))


@app.get("/api/me")
def me():
    user = current_user()
    return jsonify(user=public(user) if user else None)


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not EMAIL_RE.match(email):
        return error("Please enter a valid email address.")
    if len(password) < 6:
        return error("Password must be at least 6 characters.")
    if db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        return error("An account with this email already exists. Please sign in.", 409)
    cursor = db().execute(
        "INSERT INTO users(email,name,pw_hash) VALUES(?,?,?)",
        (email, name_from_email(email), generate_password_hash(password)),
    )
    db().commit()
    user = db().execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
    start_session(user)
    return jsonify(ok=True, user=public(user)), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or not user["pw_hash"] or not check_password_hash(user["pw_hash"], password):
        return error("Wrong email or password. If you are new, create an account.", 401)
    start_session(user)
    return jsonify(ok=True, user=public(user))


@app.post("/api/auth/google")
def google_login():
    if not GOOGLE_CLIENT_ID:
        return error("Google sign-in is not configured on the server.", 501)
    credential = (request.get_json(silent=True) or {}).get("credential")
    if not credential:
        return error("Missing Google credential.")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
        info = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    except Exception:
        return error("Google sign-in could not be verified.", 401)
    if not info.get("email_verified"):
        return error("Your Google email is not verified.", 401)
    email = info["email"].lower()
    user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user:
        cursor = db().execute(
            "INSERT INTO users(email,name,picture,provider) VALUES(?,?,?,'google')",
            (email, info.get("name") or name_from_email(email), info.get("picture")),
        )
        db().commit()
        user = db().execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
    start_session(user)
    return jsonify(ok=True, user=public(user))


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


def filtered() -> pd.DataFrame:
    args = request.args
    frame = DF
    if args.get("year") and args["year"] != "all":
        frame = frame[frame.Year == args["year"]]
    for arg, column in (("category", "Category"), ("state", "Ship_State"),
                        ("payment", "Payment_Method"), ("fulfillment", "Fulfillment"),
                        ("status", "Order_Status")):
        if args.get(arg):
            frame = frame[frame[column] == args[arg]]
    query = args.get("q", "").strip().lower()
    if query:
        searchable = (frame.Product + " " + frame.Category + " " + frame.Ship_State + " " +
                      frame.Payment_Method + " " + frame.Fulfillment + " " + frame.Order_Status).str.lower()
        mask = pd.Series(True, index=frame.index)
        for word in query.split():
            mask &= searchable.str.contains(word, regex=False)
        frame = frame[mask]
    return frame


@app.get("/api/data")
@login_required
def data():
    return jsonify(PAYLOAD)


@app.get("/api/summary")
@login_required
def summary():
    frame = filtered()
    count, sales, profit = len(frame), float(frame.Total_Sales_INR.sum()), float(frame.Profit_INR.sum())
    statuses = frame.Order_Status.value_counts()
    status_count = lambda value: int(statuses.get(value, 0))
    lost_sales = frame[frame.Order_Status.isin(["Returned", "Cancelled"])].Total_Sales_INR.sum()
    return jsonify(
        total_sales=round(sales, 2), total_profit=round(profit, 2), total_orders=count,
        total_units=int(frame.Quantity.sum()), avg_order_value=round(sales / count, 2) if count else 0,
        profit_margin_pct=round(profit / sales * 100, 2) if sales else 0,
        delivered=status_count("Delivered"), shipped=status_count("Shipped"),
        returned=status_count("Returned"), cancelled=status_count("Cancelled"),
        return_rate_pct=round(status_count("Returned") / count * 100, 2) if count else 0,
        cancellation_rate_pct=round(status_count("Cancelled") / count * 100, 2) if count else 0,
        revenue_lost=round(float(lost_sales), 2),
    )


BREAKDOWNS = {"month": "Month", "year": "Year", "category": "Category", "state": "Ship_State",
              "payment": "Payment_Method", "fulfillment": "Fulfillment", "product": "Product"}


@app.get("/api/breakdown")
@login_required
def breakdown():
    dimension = request.args.get("by", "category")
    column = BREAKDOWNS.get(dimension)
    if not column:
        return error("by must be one of: " + ", ".join(BREAKDOWNS))
    grouped = (filtered().groupby(column)
               .agg(sales=("Total_Sales_INR", "sum"), profit=("Profit_INR", "sum"),
                    orders=("Order_ID", "count"), units=("Quantity", "sum")).reset_index())
    grouped = grouped.sort_values(column, ascending=True) if dimension in ("month", "year") else grouped.sort_values("sales", ascending=False)
    limit = request.args.get("limit", "")
    if limit.isdigit():
        grouped = grouped.head(min(int(limit), 1000))
    grouped = grouped.rename(columns={column: "label"}).round(2)
    return jsonify(by=dimension, rows=grouped.to_dict("records"))


@app.get("/")
def index():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5001)), debug=os.environ.get("FLASK_DEBUG") == "1")
