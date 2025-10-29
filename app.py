from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import json
from pathlib import Path
import numpy as np
import pyodbc

app = Flask(__name__)
CORS(app)

# ===============================
# Konfigurácia DB (Azure SQL)
# ===============================
DB_SERVER = os.getenv("DB_SERVER", "swiss2025.database.windows.net")
DB_NAME = os.getenv("DB_NAME", "swiss2025")
DB_USER = os.getenv("DB_USER", "adminjozo")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Asdasdasd007")
ODBC_DRIVER = os.getenv("ODBC_DRIVER", "{ODBC Driver 18 for SQL Server}")

DATA_PATH = Path(__file__).parent / "students.json"

def get_connection():
    conn_str = (
        f"DRIVER={ODBC_DRIVER};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)

ALLOWED_ORDER = {"Id", "Name", "Gender", "City", "Weight", "Bench"}

def parse_filters():
    args = request.args
    city = args.get("city")
    gender = args.get("gender")
    name = args.get("name")

    def _to_float(key):
        val = args.get(key)
        if val is None or val == "":
            return None
        return float(val)

    min_weight = _to_float("min_weight") if args.get("min_weight") else None
    max_weight = _to_float("max_weight") if args.get("max_weight") else None

    limit = max(1, min(int(args.get("limit", 100)), 500))
    offset = max(0, int(args.get("offset", 0)))

    order_by = args.get("order_by", "Id")
    if order_by not in ALLOWED_ORDER:
        order_by = "Id"
    order_dir = "DESC" if args.get("order_dir", "asc").lower() == "desc" else "ASC"

    return {
        "city": city, "gender": gender, "name": name,
        "min_weight": min_weight, "max_weight": max_weight,
        "limit": limit, "offset": offset,
        "order_by": order_by, "order_dir": order_dir
    }

# -------- UI ----------
@app.route("/")
def index():
    # Render peknej stránky s tabuľkou a filtrami
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    return ("", 204)

# -------- Health ----------
@app.route("/health")
def health():
    try:
        with get_connection() as _:
            return jsonify({"status": "ok", "db_connected": True})
    except Exception as e:
        return jsonify({"status": "error", "db_connected": False, "message": str(e)}), 500

# -------- DB ----------
@app.route("/students", methods=["GET"])
def get_students_from_db():
    try:
        f = parse_filters()
    except Exception as ve:
        return jsonify({"error": str(ve)}), 400

    where, params = [], []
    if f["city"]:
        where.append("City = ?"); params.append(f["city"])
    if f["gender"]:
        where.append("Gender = ?"); params.append(f["gender"])
    if f["name"]:
        where.append("Name LIKE ?"); params.append(f"%{f['name']}%")
    if f["min_weight"] is not None:
        where.append("Weight >= ?"); params.append(f["min_weight"])
    if f["max_weight"] is not None:
        where.append("Weight <= ?"); params.append(f["max_weight"])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order_sql = f"ORDER BY {f['order_by']} {f['order_dir']}"
    paging_sql = "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            sql = f"""
                SELECT Id, Name, Gender, City, Weight, Bench
                FROM Students
                {where_sql}
                {order_sql}
                {paging_sql}
            """
            exec_params = params + [f["offset"], f["limit"]]
            cur.execute(sql, exec_params)
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
            data = [dict(zip(cols, row)) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------- JSON ----------
@app.route("/students/json", methods=["GET"])
def get_students_from_json():
    try:
        f = parse_filters()
    except Exception as ve:
        return jsonify({"error": str(ve)}), 400

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return jsonify({"error": "students.json not found"}), 404

    def ok(s):
        if f["city"] and s.get("City") != f["city"]:
            return False
        if f["gender"] and s.get("Gender") != f["gender"]:
            return False
        if f["name"] and f["name"].lower() not in (s.get("Name") or "").lower():
            return False
        w = s.get("Weight")
        if f["min_weight"] is not None and (w is None or float(w) < f["min_weight"]):
            return False
        if f["max_weight"] is not None and (w is None or float(w) > f["max_weight"]):
            return False
        return True

    data = [s for s in raw if ok(s)]
    reverse = f["order_dir"] == "DESC"
    try:
        data.sort(key=lambda x: (x.get(f["order_by"]) is None, x.get(f["order_by"])), reverse=reverse)
    except Exception:
        pass
    start, end = f["offset"], f["offset"] + f["limit"]
    return jsonify(data[start:end])

# -------- Predict (ponechané z cvika) ----------
@app.route("/predict", methods=["POST"])
def predict():
    try:
        payload = request.get_json(force=True)
        scores = payload["scores"]
        if not isinstance(scores, list) or len(scores) < 2:
            return jsonify({"error": "Provide at least two numeric scores"}), 400
        x = np.arange(len(scores))
        y = np.array(scores, dtype=float)
        coeffs = np.polyfit(x, y, 1)
        return jsonify({"predicted_next_score": float(np.polyval(coeffs, len(scores)))})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
