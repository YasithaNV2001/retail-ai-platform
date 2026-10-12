import streamlit as st

st.title("Probe P-19")
st.write("Secret present:", "RAP_PROBE_SECRET" in st.secrets)
