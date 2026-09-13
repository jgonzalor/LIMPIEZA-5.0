# modules/auth.py
import streamlit as st
import streamlit_authenticator as stauth


# Estructura esperada en st.secrets:
# [auth]
# cookie_name = "gomapper_suite"
# key = "cambia-esta-clave-segura"
# expiry_days = 30
# [credentials]
# usernames = {
# "jgonzalo": {"email": "tucorreo@dominio.com", "name": "JG", "password": "<HASH_BCRYPT>"}
# }


def get_authenticator():
creds = st.secrets.get("credentials")
auth_cfg = st.secrets.get("auth", {})


if not creds or "usernames" not in creds:
raise RuntimeError("Faltan credentials en secrets.")


cookie_name = auth_cfg.get("cookie_name", "gomapper_suite")
key = auth_cfg.get("key", "cambia-esta-clave-segura")
expiry_days = int(auth_cfg.get("expiry_days", 30))


authenticator = stauth.Authenticate(
credentials=creds,
cookie_name=cookie_name,
key=key,
cookie_expiry_days=expiry_days,
)
return authenticator
