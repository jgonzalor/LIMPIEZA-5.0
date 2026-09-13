"""Legacy adapter. Active suite authentication lives in guardian.py."""
def get_authenticator():
    import streamlit as st
    try:
        import streamlit_authenticator as stauth
    except ImportError as error:
        raise RuntimeError("Adaptador opcional: requiere streamlit-authenticator. La suite usa guardian.py.") from error
    creds = st.secrets.get("credentials")
    cfg = st.secrets.get("auth", {})
    if not creds or "usernames" not in creds:
        raise RuntimeError("Faltan credentials en secrets.")
    return stauth.Authenticate(credentials=creds, cookie_name=cfg.get("cookie_name", "gomapper_suite"),
                              key=cfg["key"], cookie_expiry_days=int(cfg.get("expiry_days",30)))
