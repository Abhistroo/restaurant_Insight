import streamlit as st
import sqlite3
import pandas as pd
import pytesseract
from PIL import Image
import pdfplumber
import re
import qrcode
from io import BytesIO
import subprocess
import os
import matplotlib.pyplot as plt

# ======================================================
# 🔧 CONFIG
# ======================================================

PUBLIC_BASE_URL = "https://9c8629a9ccf1.ngrok-free.app"

if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

st.set_page_config(page_title="Restaurant Insights", layout="centered")

# ======================================================
# 💾 DATABASE
# ======================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "restaurant.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

# ======================================================
# 🗄️ TABLES
# ======================================================

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

# ======================================================
# 📸 OCR
# ======================================================

def extract_text(file):
    if file.type == "application/pdf":
        text = ""
        with pdfplumber.open(file) as pdf:
            for p in pdf.pages:
                if p.extract_text():
                    text += p.extract_text() + "\n"
        return text
    return pytesseract.image_to_string(Image.open(file))

# ======================================================
# 📋 MENU EXTRACTION (LOCKED)
# ======================================================

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

# ======================================================
# 🔀 ROUTING
# ======================================================

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

    ordered = st.selectbox("What did you order?", menu_items)
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
        if st.button("Create Account") and email and password:
            try:
                cur.execute("INSERT INTO users VALUES (NULL, ?, ?)", (email, password))
                conn.commit()
                st.success("Account created. Please login.")
            except:
                st.error("User already exists")

    st.stop()

uid = st.session_state.user_id
profile = pd.read_sql("SELECT * FROM restaurant_profile WHERE user_id=?", conn, params=(uid,))
menu_df = pd.read_sql("SELECT * FROM menu WHERE user_id=?", conn, params=(uid,))
p = profile.iloc[0] if not profile.empty else None

# ======================================================
# 🟦 ONBOARDING
# ======================================================

if p is None or menu_df.empty:
    st.title("🚀 Setup Your Restaurant")

    name = st.text_input("Restaurant Name")
    city = st.text_input("City")
    ambience = st.multiselect("Ambience", ["Cozy", "Modern", "Rooftop", "Family", "Street-side"])
    target = st.multiselect("Target Customers", ["Students", "Families", "Office Workers", "Tourists"])
    budget = st.radio("Budget Positioning", ["Budget", "Mid", "Premium"])

    file = st.file_uploader("Upload Menu", type=["png","jpg","jpeg","pdf"])

    if file:
        raw = extract_text(file)
        parsed = pd.DataFrame(parse_menu_lines_strict(raw))
        st.dataframe(parsed)

    if st.button("Complete Setup") and file and name:
        # ✅ FIXED INSERT
        cur.execute("""
            INSERT INTO restaurant_profile
            (user_id, name, city, ambience, target, budget)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (uid, name, city, ",".join(ambience), ",".join(target), budget))

        for _, r in parsed.iterrows():
            cur.execute("INSERT INTO menu VALUES (NULL, ?, ?, ?)", (uid, r["item"], r["price"]))

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
    st.dataframe(menu_df[["item", "price"]])

    if st.button("View Business Insights"):
        st.query_params["page"] = "insights"
        st.rerun()

# ======================================================
# 📊 INSIGHTS
# ======================================================

if page == "insights":
    st.title("🧠 Business Insights")

    fb = pd.read_sql(
        "SELECT overall_rating, taste_rating, value_rating, service_rating FROM feedback WHERE user_id=?",
        conn, params=(uid,)
    )

    st.subheader("📊 Customer Ratings (Average out of 5)")

    if not fb.empty:
        avg = fb.mean()
        categories = ["Overall", "Taste", "Value for Money", "Service"]
        values = [avg["overall_rating"], avg["taste_rating"], avg["value_rating"], avg["service_rating"]]

        fig, ax = plt.subplots(figsize=(6,4))
        bars = ax.bar(categories, values, color="#4F8BF9")

        ax.set_ylim(0, 5)
        ax.set_yticks([0,1,2,3,4,5])
        ax.set_ylabel("Rating")
        ax.set_title("Fixed Scale Customer Ratings (0–5)")

        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, h + 0.08, f"{h:.1f}",
                    ha="center", va="bottom", fontsize=10)

        st.pyplot(fig, clear_figure=True)
    else:
        st.info("No feedback yet.")

    st.subheader("🧠 AI Consultant Insights")

    if st.button("Refresh Insights"):
        prompt = f"""
You are a senior restaurant business consultant.

RULES:
- ONLY bullet points
- NO paragraphs
- Each bullet = one clear action

Restaurant:
City: {p['city']}
Ambience: {p['ambience']}
Target Customers: {p['target']}
Budget: {p['budget']}

Ratings:
Overall {fb['overall_rating'].mean():.1f}
Taste {fb['taste_rating'].mean():.1f}
Value {fb['value_rating'].mean():.1f}
Service {fb['service_rating'].mean():.1f}

Give insights under:
1. Strengths
2. Weaknesses
3. Pricing Strategy
4. Menu Improvements
5. Service Improvements
6. Quick Wins (7 days)
"""

        res = subprocess.run(
            ["ollama", "run", "mistral"],
            input=prompt,
            text=True,
            capture_output=True
        )

        cur.execute("DELETE FROM insights WHERE user_id=?", (uid,))
        cur.execute("INSERT INTO insights VALUES (?, ?)", (uid, res.stdout))
        conn.commit()

    saved = pd.read_sql("SELECT content FROM insights WHERE user_id=?", conn, params=(uid,))
    if not saved.empty:
        st.markdown(saved.iloc[0]["content"])

    st.divider()
    st.subheader("📲 Collect Customer Feedback")

    url = f"{PUBLIC_BASE_URL}/?mode=feedback&uid={uid}"
    qr = qrcode.make(url)
    buf = BytesIO()
    qr.save(buf)
    st.image(buf, width=200)
    st.code(url)
