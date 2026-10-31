import streamlit as st
import sqlite3
import pandas as pd

st.set_page_config(page_title="DB Viewer (Temp)", layout="wide")
st.title("🗄️ Restaurant App – Database Viewer (TEMP)")

# Connect DB (read-only usage)
conn = sqlite3.connect("restaurant.db", check_same_thread=False)

# Utility to load table safely
def load_table(table_name):
    try:
        return pd.read_sql(f"SELECT * FROM {table_name}", conn)
    except Exception as e:
        st.error(f"Error loading {table_name}: {e}")
        return pd.DataFrame()

# Sidebar table selector
table = st.sidebar.selectbox(
    "Select Table",
    [
        "users",
        "restaurant_profile",
        "menu",
        "feedback",
        "feedback_items",
        "insights"
    ]
)

st.subheader(f"📋 Table: `{table}`")

df = load_table(table)

if df.empty:
    st.warning("No data found")
else:
    st.dataframe(df, use_container_width=True)

st.divider()

st.caption(
    "⚠️ This is a TEMP debug tool. "
    "Do not deploy or expose in production."
)
