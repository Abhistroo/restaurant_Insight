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
import shutil
import matplotlib.pyplot as plt

# ======================================================
# 🔧 CONFIG
# ======================================================

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://gradually-records-builder-annex.trycloudflare.com")

if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

st.set_page_config(page_title="Restaurant Insights", layout="centered")

# ======================================================
# 💾 DATABASE
# ======================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "restaurant.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
conn.execute("PRAGMA journal_mode=WAL;")
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
    ambience_rating INTEGER,
    ordered TEXT
)
""")

try:
    cols = [c[1] for c in cur.execute("PRAGMA table_info(feedback)").fetchall()]
    if "ambience_rating" not in cols:
        cur.execute("ALTER TABLE feedback ADD COLUMN ambience_rating INTEGER DEFAULT 4")
except Exception:
    pass

cur.execute("""
CREATE TABLE IF NOT EXISTS feedback_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER,
    user_id INTEGER,
    item TEXT,
    taste_rating INTEGER,
    value_rating INTEGER
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
    st.title("⭐ Customer Feedback")

    submitted_key = f"feedback_submitted_{uid}"
    already_submitted = (query.get("submitted") == "true") or st.session_state.get(submitted_key, False)

    if already_submitted:
        st.success("🎉 Thank you! Your feedback has been submitted ❤️")
        st.button("Response Already Submitted", disabled=True)
        st.stop()

    menu_items = pd.read_sql(
        "SELECT item FROM menu WHERE user_id=?",
        conn, params=(uid,)
    )["item"].tolist()

    st.subheader("🍽️ Dishes Ordered")
    selected_dishes = st.multiselect(
        "Select all dishes you ordered:",
        options=menu_items,
        default=None,
        placeholder="Choose one or more dishes..."
    )

    custom_dish = st.text_input("Don't see your dish? Enter dish name (optional):").strip()
    all_selected = list(selected_dishes)
    if custom_dish and custom_dish not in all_selected:
        all_selected.append(custom_dish)

    dish_ratings = {}
    if all_selected:
        st.markdown("---")
        st.subheader("🍲 Rate Your Dishes (Taste & Pricing)")
        for dish in all_selected:
            with st.container():
                st.markdown(f"**{dish}**")
                col1, col2 = st.columns(2)
                with col1:
                    t = st.slider(f"Taste - {dish}", 1, 5, 4, key=f"taste_{dish}")
                with col2:
                    v = st.slider(f"Pricing & Value - {dish}", 1, 5, 4, key=f"price_{dish}")
                dish_ratings[dish] = {"taste": t, "value": v}
    else:
        st.info("👆 Please select at least one dish above to rate its taste and pricing.")

    st.markdown("---")
    st.subheader("🏪 Restaurant Experience")
    st.caption("Ambience, service, and overall experience are evaluated for the restaurant as a whole.")
    ambience = st.slider("Ambience", 1, 5, 4, key="ambience_rating")
    service = st.slider("Service", 1, 5, 4, key="service_rating")
    overall = st.slider("Overall Experience", 1, 5, 4, key="overall_rating")

    st.markdown("---")
    if st.button("Submit Feedback", type="primary", disabled=already_submitted):
        if not all_selected:
            st.error("Please select or enter at least one dish you ordered.")
        else:
            avg_taste = sum(r["taste"] for r in dish_ratings.values()) / len(dish_ratings)
            avg_value = sum(r["value"] for r in dish_ratings.values()) / len(dish_ratings)
            ordered_str = ", ".join(all_selected)

            cur.execute("""
                INSERT INTO feedback
                (user_id, overall_rating, taste_rating, value_rating, service_rating, ambience_rating, ordered)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (uid, overall, round(avg_taste), round(avg_value), service, ambience, ordered_str))
            feedback_id = cur.lastrowid

            for dish, r in dish_ratings.items():
                cur.execute("""
                    INSERT INTO feedback_items
                    (feedback_id, user_id, item, taste_rating, value_rating)
                    VALUES (?, ?, ?, ?, ?)
                """, (feedback_id, uid, dish, r["taste"], r["value"]))

            conn.commit()
            st.session_state[submitted_key] = True
            st.query_params["submitted"] = "true"
            st.rerun()

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
            if not email or not password:
                st.warning("Please enter both email and password.")
            else:
                cur.execute(
                    "SELECT id FROM users WHERE email=? AND password=?",
                    (email.strip(), password)
                )
                u = cur.fetchone()
                if u:
                    st.session_state.user_id = u[0]
                    st.rerun()
                else:
                    st.error("Invalid email or password. Please try again.")

    with tab2:
        email = st.text_input("Email", key="s")
        password = st.text_input("Password", type="password", key="p")
        if st.button("Create Account"):
            if not email or not password:
                st.warning("Please enter both email and password.")
            else:
                try:
                    cur.execute("INSERT INTO users VALUES (NULL, ?, ?)", (email.strip(), password))
                    conn.commit()
                    st.success("Account created successfully! Please switch to the Login tab.")
                except Exception:
                    st.error("User with this email already exists.")

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
    col_back, col_title = st.columns([1, 4])
    with col_back:
        if st.button("⬅️ Dashboard"):
            st.query_params["page"] = "dashboard"
            st.rerun()

    st.title("🧠 Business Insights")

    fb = pd.read_sql(
        "SELECT overall_rating, taste_rating, value_rating, service_rating, ambience_rating FROM feedback WHERE user_id=?",
        conn, params=(uid,)
    )

    st.subheader("📊 Customer Ratings (Average out of 5)")

    if not fb.empty:
        avg = fb.mean()
        ambience_val = avg["ambience_rating"] if "ambience_rating" in avg and pd.notna(avg["ambience_rating"]) else 4.0
        categories = ["Overall", "Taste", "Pricing / Value", "Service", "Ambience"]
        values = [avg["overall_rating"], avg["taste_rating"], avg["value_rating"], avg["service_rating"], ambience_val]

        fig, ax = plt.subplots(figsize=(7,4))
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

    # Dish-level feedback breakdown
    fb_items = pd.read_sql(
        """
        SELECT item as 'Dish',
               ROUND(AVG(taste_rating), 1) as 'Avg Taste (1-5)',
               ROUND(AVG(value_rating), 1) as 'Avg Pricing/Value (1-5)',
               COUNT(*) as 'Total Ratings'
        FROM feedback_items
        WHERE user_id=?
        GROUP BY item
        ORDER BY 'Total Ratings' DESC
        """,
        conn, params=(uid,)
    )
    if not fb_items.empty:
        st.subheader("🍲 Dish-Level Feedback (Taste & Pricing)")
        st.dataframe(fb_items, use_container_width=True)

    st.subheader("🧠 AI Consultant Insights")

    def generate_ai_insights(p_data, fb_data, items_data):
        overall = fb_data["overall_rating"].mean() if not fb_data.empty else 3.5
        taste = fb_data["taste_rating"].mean() if not fb_data.empty else 3.5
        value = fb_data["value_rating"].mean() if not fb_data.empty else 3.5
        service = fb_data["service_rating"].mean() if not fb_data.empty else 3.5
        ambience = fb_data["ambience_rating"].mean() if not fb_data.empty and "ambience_rating" in fb_data and pd.notna(fb_data["ambience_rating"].mean()) else 4.0
        total_reviews = len(fb_data)

        dish_summary_lines = []
        low_taste_dishes = []
        low_value_dishes = []
        top_dishes = []

        if not items_data.empty:
            for _, row in items_data.iterrows():
                d_name = row["Dish"]
                d_taste = float(row["Avg Taste (1-5)"])
                d_val = float(row["Avg Pricing/Value (1-5)"])
                dish_summary_lines.append(f"- {d_name}: Taste {d_taste:.1f}/5, Value {d_val:.1f}/5")
                if d_taste < 3.5:
                    low_taste_dishes.append(d_name)
                elif d_taste >= 4.0:
                    top_dishes.append(d_name)
                if d_val < 3.5:
                    low_value_dishes.append(d_name)

        dishes_text = "\n".join(dish_summary_lines) if dish_summary_lines else "No specific dish ratings yet."

        prompt = f"""You are a senior restaurant business consultant.

RULES:
- ONLY bullet points
- NO paragraphs
- Each bullet = one clear action

Restaurant:
Name: {p_data['name']}
City: {p_data['city']}
Ambience: {p_data['ambience']}
Target Customers: {p_data['target']}
Budget: {p_data['budget']}
Total Customer Reviews: {total_reviews}

Customer Ratings (Average out of 5):
Overall: {overall:.1f}
Taste: {taste:.1f}
Pricing / Value: {value:.1f}
Service: {service:.1f}
Ambience: {ambience:.1f}

Dish-Level Feedback:
{dishes_text}

Give insights under:
1. Strengths
2. Weaknesses
3. Pricing Strategy
4. Menu Improvements
5. Service Improvements
6. Quick Wins (7 days)
"""

        # 1. Try local Ollama if installed
        if shutil.which("ollama"):
            try:
                res = subprocess.run(
                    ["ollama", "run", "mistral"],
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=30
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass

        # 2. Comprehensive data-driven AI Consultant engine
        strengths = []
        if overall >= 4.0:
            strengths.append(f"Strong overall guest satisfaction with an average rating of {overall:.1f}/5 across {total_reviews} reviews.")
        if taste >= 4.0:
            strengths.append(f"High culinary satisfaction with an average taste rating of {taste:.1f}/5.")
        if top_dishes:
            strengths.append(f"Customer favorite dish(es) performing exceptionally: {', '.join(top_dishes)}.")
        if ambience >= 3.8:
            strengths.append(f"Ambiance '{p_data['ambience']}' is well-liked ({ambience:.1f}/5), appealing to target audience ({p_data['target']}).")
        if service >= 4.0:
            strengths.append(f"Front-of-house hospitality is a strong asset with an average service score of {service:.1f}/5.")
        if not strengths:
            strengths.append(f"Well-positioned concept in {p_data['city']} catering to {p_data['target']}.")

        weaknesses = []
        if overall < 3.5:
            weaknesses.append(f"Overall satisfaction is low ({overall:.1f}/5); comprehensive improvements needed across dining operations.")
        if taste < 3.5 or low_taste_dishes:
            d_note = f" (particularly on {', '.join(low_taste_dishes)})" if low_taste_dishes else ""
            weaknesses.append(f"Food taste ratings are below expectations at {taste:.1f}/5{d_note}.")
        if value < 3.5 or low_value_dishes:
            d_note = f" for {', '.join(low_value_dishes)}" if low_value_dishes else ""
            weaknesses.append(f"Perceived value for money is unfavorable at {value:.1f}/5{d_note}.")
        if service < 3.5:
            weaknesses.append(f"Service rating of {service:.1f}/5 signals slow turnaround or inadequate table check-ins.")
        if not weaknesses:
            weaknesses.append("Table turnaround time during peak dining hours can be further optimized.")

        pricing = []
        if low_value_dishes:
            pricing.append(f"Re-evaluate portion sizes or introduce bundled combo pricing for {', '.join(low_value_dishes)} to boost perceived value.")
        elif value < 3.8:
            pricing.append(f"Introduce lunchtime combo offers and value platters tailored to {p_data['target']}.")
        else:
            pricing.append("Current pricing structure is well received; test premium add-ons to increase average check size.")
        pricing.append(f"Maintain close competitor price benchmarking in {p_data['city']} for {p_data['budget']}-tier dining.")

        menu_impr = []
        if low_taste_dishes:
            menu_impr.append(f"Standardize recipes, fresh ingredients, and prep guidelines for underperforming items: {', '.join(low_taste_dishes)}.")
        if top_dishes:
            menu_impr.append(f"Promote top performers ({', '.join(top_dishes)}) as Chef Specials on menus and social channels.")
        menu_impr.append(f"Audit low-order items to streamline kitchen prep and reduce ingredient waste.")

        service_impr = []
        if service < 4.0:
            service_impr.append("Institute a strict 5-minute initial greeting and beverage delivery benchmark for all tables.")
            service_impr.append("Conduct weekly customer service training focusing on order accuracy and proactive guest care.")
        else:
            service_impr.append("Maintain high hospitality benchmarks and reward top-reviewed service staff.")

        quick_wins = []
        if low_taste_dishes or low_value_dishes:
            troubled = list(set(low_taste_dishes + low_value_dishes))
            quick_wins.append(f"Conduct an immediate taste and portion audit for {', '.join(troubled)} within 48 hours.")
        quick_wins.append("Place feedback QR cards at table centers to capture continuous real-time customer feedback.")
        quick_wins.append(f"Launch a targeted weekday promotional deal designed for {p_data['target']}.")

        return f"""### 1. Strengths
""" + "\n".join(f"- {s}" for s in strengths) + f"""

### 2. Weaknesses
""" + "\n".join(f"- {w}" for w in weaknesses) + f"""

### 3. Pricing Strategy
""" + "\n".join(f"- {pr}" for pr in pricing) + f"""

### 4. Menu Improvements
""" + "\n".join(f"- {m}" for m in menu_impr) + f"""

### 5. Service Improvements
""" + "\n".join(f"- {sv}" for sv in service_impr) + f"""

### 6. Quick Wins (7 days)
""" + "\n".join(f"- {q}" for q in quick_wins)

    if st.button("Refresh Insights"):
        with st.spinner("Analyzing customer feedback and generating insights..."):
            new_insights = generate_ai_insights(p, fb, fb_items)
            cur.execute("DELETE FROM insights WHERE user_id=?", (uid,))
            cur.execute("INSERT INTO insights (user_id, content) VALUES (?, ?)", (uid, new_insights))
            conn.commit()
            st.success("✨ Insights updated based on latest customer reviews!")

    saved = pd.read_sql("SELECT content FROM insights WHERE user_id=?", conn, params=(uid,))
    if not saved.empty and saved.iloc[0]["content"]:
        st.markdown(saved.iloc[0]["content"])

    st.divider()
    st.subheader("📲 Collect Customer Feedback")

    base_url = st.text_input("Feedback Base URL (Public Tunnel or Local Wi-Fi)", value=PUBLIC_BASE_URL).rstrip("/")
    url = f"{base_url}/?mode=feedback&uid={uid}"
    qr = qrcode.make(url)
    buf = BytesIO()
    qr.save(buf)
    st.image(buf, width=200)
    st.code(url)
    st.caption("Scan with your phone to open the feedback form.")
