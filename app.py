import os
import secrets
from pathlib import Path

import razorpay
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

from database import get_connection, init_db

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

print("Razorpay key loaded:", (RAZORPAY_KEY_ID or "NOT FOUND")[:9])

app = Flask(__name__)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    try:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        print("Razorpay client initialized successfully!")
    except Exception as e:
        print("Razorpay init error:", e)


app.secret_key = "qr-canteen-development-secret-key"


@app.route("/")
def home():
    return redirect(url_for("table_menu", table_code="T1"))


@app.route("/table/<table_code>")
def table_menu(table_code):
    conn = get_connection()

    table = conn.execute(
        """
        SELECT *
        FROM canteen_tables
        WHERE table_code = ?
        AND is_active = 1
        """,
        (table_code,)
    ).fetchone()

    if table is None:
        conn.close()
        return "Table not found", 404

    items = conn.execute(
        """
        SELECT
            menu_items.*,
            categories.name AS category_name
        FROM menu_items
        JOIN categories
            ON menu_items.category_id = categories.id
        WHERE menu_items.is_available = 1
        ORDER BY categories.name, menu_items.name
        """
    ).fetchall()

    categories = conn.execute(
        """
        SELECT *
        FROM categories
        ORDER BY name
        """
    ).fetchall()

    conn.close()

    return render_template(
        "menu.html",
        table=table,
        items=items,
        categories=categories
    )


@app.route("/order", methods=["POST"])
def place_order():
    table_code = request.form.get("table_code", "T1")
    conn = get_connection()
    table = conn.execute(
        "SELECT * FROM canteen_tables WHERE table_code = ? AND is_active = 1",
        (table_code,)
    ).fetchone()

    if table is None:
        conn.close()
        return "Invalid table", 400

    order_items_to_add = []
    total_amount = 0.0

    for key, value in request.form.items():
        if key.startswith("qty_"):
            try:
                qty = int(value)
                if qty > 0:
                    item_id = int(key.replace("qty_", ""))
                    item = conn.execute("SELECT id, name, price FROM menu_items WHERE id = ?", (item_id,)).fetchone()
                    if item:
                        subtotal = round(item["price"] * qty, 2)
                        total_amount += subtotal
                        order_items_to_add.append((item["id"], item["name"], qty, item["price"], subtotal))
            except (ValueError, TypeError):
                continue

    if not order_items_to_add or total_amount <= 0:
        conn.close()
        return redirect(url_for("table_menu", table_code=table_code))

    total_amount = round(total_amount, 2)
    token = secrets.token_hex(3).upper()

    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (token, table_id, total_amount, status) VALUES (?, ?, ?, ?)",
        (token, table["id"], total_amount, "PENDING_PAYMENT")
    )
    order_id = cursor.lastrowid

    for itm_id, itm_name, qty, unit_p, sub_tot in order_items_to_add:
        cursor.execute(
            """
            INSERT INTO order_items (order_id, menu_item_id, item_name, quantity, unit_price, subtotal)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (order_id, itm_id, itm_name, qty, unit_p, sub_tot)
        )

    cursor.execute(
        "INSERT INTO payments (order_id, payment_method, payment_status, amount) VALUES (?, ?, ?, ?)",
        (order_id, "CASH", "PENDING", total_amount)
    )

    cursor.execute(
        "INSERT INTO order_status_history (order_id, status) VALUES (?, ?)",
        (order_id, "PENDING_PAYMENT")
    )

    conn.commit()
    conn.close()

    return redirect(url_for("order_status", token=token))


@app.route("/order/<token>")
def order_status(token):
    conn = get_connection()
    order = conn.execute(
        """
        SELECT
            orders.*,
            canteen_tables.table_name,
            canteen_tables.table_code
        FROM orders
        JOIN canteen_tables
            ON orders.table_id = canteen_tables.id
        WHERE orders.token = ?
        """,
        (token,)
    ).fetchone()

    if order is None:
        conn.close()
        return "Order not found", 404

    order_items = conn.execute(
        """
        SELECT *
        FROM order_items
        WHERE order_id = ?
        """,
        (order["id"],)
    ).fetchall()

    payment = conn.execute(
        "SELECT * FROM payments WHERE order_id = ?",
        (order["id"],)
    ).fetchone()

    conn.close()

    rz_key = os.getenv("RAZORPAY_KEY_ID", "")
    rz_order_id = ""

    # Generate real Razorpay order if pending and client available
    if order["status"] == "PENDING_PAYMENT" and razorpay_client and order["total_amount"] > 0:
        try:
            rzp_response = razorpay_client.order.create({
                "amount": int(round(order["total_amount"] * 100)),
                "currency": "INR",
                "receipt": f"rec_{order['id']}",
                "payment_capture": 1
            })
            rz_order_id = rzp_response.get("id", "")
        except Exception as e:
            print("Razorpay order creation error:", e)

    return render_template(
        "order_status.html",
        order=order,
        order_items=order_items,
        payment=payment,
        razorpay_key_id=rz_key,
        razorpay_order_id=rz_order_id
    )


@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    data = request.get_json() or {}
    order_id = data.get("order_id")
    payment_id = data.get("razorpay_payment_id", "MANUAL_PAID")

    conn = get_connection()
    if order_id:
        conn.execute(
            "UPDATE orders SET status = 'CONFIRMED' WHERE id = ?",
            (order_id,)
        )
        conn.execute(
            "UPDATE payments SET payment_status = 'PAID', razorpay_payment_id = ? WHERE order_id = ?",
            (payment_id, order_id)
        )
        conn.execute(
            "INSERT INTO order_status_history (order_id, status) VALUES (?, 'CONFIRMED')",
            (order_id,)
        )
        conn.commit()

    conn.close()
    return jsonify({"status": "success", "message": "Payment recorded successfully"})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_connection()

        admin = conn.execute(
            """
            SELECT *
            FROM admins
            WHERE username = ?
            AND password = ?
            """,
            (
                username,
                password
            )
        ).fetchone()

        conn.close()

        if admin:
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]

            return redirect(
                url_for("admin_dashboard")
            )

        flash("Invalid username or password.")

    return render_template("admin_login.html")


@app.route("/admin/dashboard")
def admin_dashboard():

    if "admin_id" not in session:
        return redirect(
            url_for("admin_login")
        )

    conn = get_connection()

    orders = conn.execute(
        """
        SELECT
            orders.*,
            canteen_tables.table_name
        FROM orders
        JOIN canteen_tables
            ON orders.table_id = canteen_tables.id
        ORDER BY orders.created_at DESC
        """
    ).fetchall()

    total_orders = conn.execute(
        "SELECT COUNT(*) AS count FROM orders"
    ).fetchone()["count"]

    total_revenue = conn.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS total
        FROM orders
        """
    ).fetchone()["total"]

    conn.close()

    return render_template(
        "admin_dashboard.html",
        orders=orders,
        total_orders=total_orders,
        total_revenue=total_revenue
    )


@app.route("/admin/logout")
def admin_logout():

    session.clear()

    return redirect(
        url_for("admin_login")
    )


@app.route("/health")
def health():

    return {
        "status": "ok",
        "application": "QR Based Online Canteen System",
        "phase": "Phase 1"
    }




@app.route("/api/canteen-ai", methods=["POST"])
def canteen_ai_assistant():
    try:
        data = request.get_json(silent=True) or {}
        q = (data.get("query") or "").strip().lower()
        if not q:
            return jsonify({"reply": "Namaste! Main BBSBEC Canteen AI hoon. Aap menu, prices ya nutrition ke baare me pooch sakte hain."})

        if any(w in q for w in ["protein", "gym", "fitness", "healthy", "diet"]):
            return jsonify({"reply": "Fitness aur protein ke liye Paneer Roll (14g), Chilli Paneer (16.5g) aur Chole Bhature best options hain!"})

        if "samosa" in q:
            return jsonify({"reply": "Samosa freshly prepared hai, price sirf Rs 15 hai aur isme lagbhag 260 calories hoti hain!"})

        if "burger" in q:
            return jsonify({"reply": "Veg Cheese Burger Rs 50 ka hai, crisp patty aur melted cheese ke sath!"})

        if "coffee" in q:
            return jsonify({"reply": "Cold Coffee Rs 35 aur Cold Coffee with Ice Cream Rs 50 me counter par available hai!"})

        if any(w in q for w in ["tea", "chai"]):
            return jsonify({"reply": "Garma-garam Masala Tea sirf Rs 15 me available hai!"})

        if any(w in q for w in ["sweet", "meetha", "ice cream"]):
            return jsonify({"reply": "Ice creams me Chocolate Cornetto, Matka Kulfi aur Gulab Jamun available hain."})

        if any(w in q for w in ["print", "xerox", "file", "assignment"]):
            return jsonify({"reply": "Assignment B&W printing Rs 2 per page, Color print Rs 10 per page aur project folders available hain."})

        # Database lookup
        try:
            conn = get_connection()
            items = conn.execute("SELECT name, price, stock FROM menu_items WHERE is_available = 1").fetchall()
            conn.close()
            for itm in items:
                name_l = itm["name"].lower()
                if name_l in q or q in name_l:
                    st = "Available hai" if itm["stock"] > 0 else "Abhi stock khatam hai"
                    return jsonify({"reply": f"{itm['name']} ka price Rs {itm['price']} hai aur ye {st}."})
        except Exception:
            pass

        return jsonify({"reply": "Aap Samosa, Burger, Cold Coffee, Protein snacks ya Printing services ke baare me pooch sakte hain!"})
    except Exception as e:
        return jsonify({"reply": "Kripya dobara poochein, main canteen menu check kar raha hoon."})


if __name__ == "__main__":
    init_db()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
    