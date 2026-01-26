import streamlit as st
import sqlite3
import pandas as pd
import pytesseract
from PIL import Image
import pdfplumber
import re
import qrcode
from io import BytesIO
import socket
import subprocess
import os
import streamlit.components.v1 as components

# ---------------- CONFIG ----------------
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
st.set_page_config(page_title="Restaurant Insights", layout="centered")

# ---------------- DB (ABSOLUTE PATH) ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "restaurant.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

# ---------------- TABLES ----------------
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,
    password TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS restaurant_profile (
    user_id INTEGER UNIQUE,
    name TEXT,
    city TEXT,
    ambience TEXT,
    target TEXT,
    budget TEXT,
    latitude REAL,
    longitude REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS menu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item TEXT,
    price REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    overall_rating INTEGER,
    taste_rating INTEGER,
    value_rating INTEGER,
    service_rating INTEGER,
    ordered TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS insights (
    user_id INTEGER,
    content TEXT
)
""")

conn.commit()

# ---------------- UTIL ----------------
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_browser_location():
    return components.html(
        """
        <script>
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                document.body.innerHTML =
                    pos.coords.latitude + "," + pos.coords.longitude;
            }
        );
        </script>
        """,
        height=0,
    )

# ---------------- OCR ----------------
def extract_text(file):
    if file.type == "application/pdf":
        text = ""
        with pdfplumber.open(file) as pdf:
            for p in pdf.pages:
                if p.extract_text():
                    text += p.extract_text() + "\n"
        return text
    return pytesseract.image_to_string(Image.open(file))

# ---------------- MENU EXTRACTION (DO NOT TOUCH) ----------------
def extract_clean_item_name(name_part):
    words = [w for w in name_part.split() if w.isalpha()]
    return " ".join(words).title()

def limit_to_two_words(name):
    return " ".join(name.split()[:2])

def parse_menu_lines_strict(text):
    items = []
    for line in text.split("\n"):
        line = line.replace("₹", "$")
        m = re.search(r"\$(\d{2,3})", line)
        if not m:
            continue
        price = float(m.group(1))
        name_part = line.split(".", 1)[0]
        name = limit_to_two_words(extract_clean_item_name(name_part))
        if name.lower() not in ["restaurant", "menu", "vs"]:
            items.append({"item": name, "price": price})
    return items

# ---------------- ROUTING ----------------
query = st.query_params
page = query.get("page", "dashboard")
mode = query.get("mode")
uid_param = query.get("uid")

# ======================================================
# 📲 CUSTOMER FEEDBACK (PHONE)
# ======================================================
if mode == "feedback" and uid_param:
    uid = int(uid_param)

    st.title("⭐ Quick Feedback")

    menu_items = pd.read_sql(
        "SELECT item FROM menu WHERE user_id=?",
        conn, params=(uid,)
    )["item"].tolist()

    ordered = st.selectbox(
        "What did you order?",
        options=menu_items,
        index=None,
        placeholder="Select item from menu"
    )

    overall = st.slider("Overall Experience", 1, 5)
    taste = st.slider("Taste", 1, 5)
    value = st.slider("Value for Money", 1, 5)
    service = st.slider("Service", 1, 5)

    if st.button("Submit"):
        cur.execute("""
            INSERT INTO feedback
            (user_id, overall_rating, taste_rating, value_rating, service_rating, ordered)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (uid, overall, taste, value, service, ordered))
        conn.commit()
        st.success("Thanks for your feedback ❤️")

    st.stop()

# ======================================================
# 🔐 AUTH
# ======================================================
if "user_id" not in st.session_state:
    st.session_state.user_id = None

if st.session_state.user_id is None:
    st.title("🔐 Restaurant Insights")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            cur.execute(
                "SELECT id FROM users WHERE email=? AND password=?",
                (email, password)
            )
            u = cur.fetchone()
            if u:
                st.session_state.user_id = u[0]
                st.rerun()

    with tab2:
        email = st.text_input("Email", key="s")
        password = st.text_input("Password", type="password", key="p")
        if st.button("Create Account"):
            if email and password:
                try:
                    cur.execute(
                        "INSERT INTO users VALUES (NULL, ?, ?)",
                        (email, password)
                    )
                    conn.commit()
                    st.success("Account created. Please login.")
                except:
                    st.error("User already exists")

    st.stop()

uid = st.session_state.user_id

profile = pd.read_sql(
    "SELECT * FROM restaurant_profile WHERE user_id=?",
    conn, params=(uid,)
)
menu_df = pd.read_sql(
    "SELECT * FROM menu WHERE user_id=?",
    conn, params=(uid,)
)

# ✅ SAFE PROFILE ACCESS
p = profile.iloc[0] if not profile.empty else None

# ======================================================
# 🟦 ONBOARDING
# ======================================================
if p is None or menu_df.empty:
    st.title("🚀 Setup Your Restaurant")

    name = st.text_input("Restaurant Name")
    city = st.text_input("City")

    ambience = st.multiselect(
        "Ambience / Vibe",
        ["Cozy", "Open & Airy", "Rooftop / View",
         "Modern", "Street-side", "Family Friendly"]
    )

    target = st.multiselect(
        "Target Customers",
        ["Students", "Families", "Office Workers", "Tourists"]
    )

    budget = st.radio("Budget Positioning", ["Budget", "Mid", "Premium"])

    if "location" not in st.session_state:
        st.session_state.location = None

    if st.button("📍 Get Live Location"):
        loc = get_browser_location()
        if loc:
            try:
                lat, lon = map(float, loc.split(","))
                st.session_state.location = (lat, lon)
            except:
                pass

    if st.session_state.location:
        st.success(f"Location captured: {st.session_state.location}")

    file = st.file_uploader("Upload Menu", type=["png","jpg","jpeg","pdf"])

    if "parsed_menu" not in st.session_state:
        st.session_state.parsed_menu = None

    if file:
        raw = extract_text(file)
        st.session_state.parsed_menu = pd.DataFrame(
            parse_menu_lines_strict(raw)
        )
        st.dataframe(st.session_state.parsed_menu)

    if st.button("Complete Setup"):
        if not name or st.session_state.parsed_menu is None:
            st.error("Please fill all required fields")
        else:
            cur.execute("""
                INSERT INTO restaurant_profile
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid,
                name,
                city,
                ",".join(ambience),
                ",".join(target),
                budget,
                st.session_state.location[0] if st.session_state.location else None,
                st.session_state.location[1] if st.session_state.location else None,
            ))

            for _, r in st.session_state.parsed_menu.iterrows():
                cur.execute(
                    "INSERT INTO menu VALUES (NULL, ?, ?, ?)",
                    (uid, r["item"], r["price"])
                )

            conn.commit()
            st.rerun()

    st.stop()

# ======================================================
# 🏠 DASHBOARD
# ======================================================
if page == "dashboard":
    st.title("🏠 Restaurant Dashboard")

    st.write(f"**Name:** {p['name']}")
    st.write(f"**City:** {p['city']}")
    st.write(f"**Ambience:** {p['ambience']}")
    st.write(f"**Target Customers:** {p['target']}")
    st.write(f"**Budget:** {p['budget']}")

    st.subheader("📋 Menu")
    st.dataframe(menu_df[["item", "price"]], use_container_width=True)

    if st.button("View Business Insights"):
        st.query_params["page"] = "insights"
        st.rerun()

# ======================================================
# 📊 INSIGHTS
# ======================================================
if page == "insights":
    st.title("🧠 Business Insights")

    fb = pd.read_sql(
        "SELECT overall_rating, taste_rating, value_rating, service_rating \
         FROM feedback WHERE user_id=?",
        conn, params=(uid,)
    )

    # 🔹 GRAPH
    st.subheader("📊 Customer Ratings Overview")
    if not fb.empty:
        avg = fb.mean().rename({
            "overall_rating": "Overall",
            "taste_rating": "Taste",
            "value_rating": "Value for Money",
            "service_rating": "Service"
        })
        chart_df = avg.reset_index()
        chart_df.columns = ["Category", "Average Rating"]
        st.bar_chart(chart_df.set_index("Category"), height=300)
    else:
        st.info("No feedback yet to show graph.")

    st.divider()

    feedback_text = ""
    for _, r in fb.iterrows():
        feedback_text += f"""
Overall: {r['overall_rating']}
Taste: {r['taste_rating']}
Value: {r['value_rating']}
Service: {r['service_rating']}
---
"""

    prompt = f"""
You are a restaurant business consultant.

Ambience: {p['ambience']}
Target Customers: {p['target']}
Budget: {p['budget']}
Location: {p['latitude']}, {p['longitude']}

Menu:
{menu_df[['item','price']].to_string(index=False)}

Customer Feedback:
{feedback_text}

Give clear, actionable business insights.
"""

    if st.button("Refresh Insights"):
        res = subprocess.run(
            ["ollama", "run", "mistral"],
            input=prompt,
            text=True,
            capture_output=True
        )
        st.markdown(res.stdout)

    st.divider()

    st.subheader("📲 Collect Customer Feedback")
    url = f"http://{get_local_ip()}:8501/?mode=feedback&uid={uid}"
    qr = qrcode.make(url)
    buf = BytesIO()
    qr.save(buf)
    st.image(buf, width=200)
    st.code(url)
