"""Bluegrass Dry Ice - Flask site.

Run locally:
    pip install -r requirements.txt
    python app.py
    -> http://127.0.0.1:5000
"""

from datetime import datetime
from uuid import uuid4

from flask import Flask, jsonify, redirect, render_template, request, url_for
import stripe
from content import BAGS, BUSINESS, CONTAINERS, FAQS, GUIDES, SAFETY_RULES, USE_CASES, WONT_DO

app = Flask(__name__)

# Pounds of dry ice consumed per day, per use case, before the container multiplier.
USE_RATES = {"ship": 8, "cooler": 6, "fog": 10, "freezer": 10}

# In-memory store. Swap for a real database before launch.
ORDERS = {}


@app.route("/")
def home():
    return render_template(
        "index.html",
        bags=BAGS,
        containers=CONTAINERS,
        use_cases=USE_CASES,
        safety_rules=SAFETY_RULES,
        wont_do=WONT_DO,
        guides=GUIDES,
        faqs=FAQS,
        biz=BUSINESS,
        year=datetime.now().year,
    )


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

    order_id = "BDI-" + uuid4().hex[:6].upper()
    order = {
        "id": order_id,
        "placed_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "total_lbs": total_lbs,
        "container": container["label"],
        "payment": payment,
        "total": round(bag_total + container["price"], 2),
    }
    ORDERS[order_id] = order

    return jsonify(
        ok=True,
        order=order,
        message=f"Order {order_id} reserved. Total ${order['total']:.2f}.",
    )


@app.get("/api/orders")
def api_orders():
    """Simple read-back of orders taken this session (prototype only)."""
    return jsonify(count=len(ORDERS), orders=list(ORDERS.values()))


if __name__ == "__main__":
    # 0.0.0.0 serves on every interface, so the site is reachable both at
    # http://127.0.0.1:5005 on this machine and at http://<your-wifi-ip>:5005
    # from phones on the same network, even if the DHCP lease changes.
    app.run(host="0.0.0.0", port=5005, debug=False)
