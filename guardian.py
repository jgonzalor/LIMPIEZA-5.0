import streamlit as st

# =========================
#  CARGA DE CREDENCIALES
# =========================

def _load_credentials_from_secrets():
    """
    Lee credenciales desde st.secrets soportando varios esquemas:

    1) Esquema simple:
       SUITE_USER = "admin"
       SUITE_PASS = "1234"

    2) Esquema [auth]:
       [auth]
       owner_user = "jgonzalo"
       default_user = "demo"
       default_password = "demo123"
       [auth.users]
       gonzalo = "pass1"
       invitado = "pass2"
    """
    users = {}

    try:
        # Esquema simple (compat viejo)
        if "SUITE_USER" in st.secrets and "SUITE_PASS" in st.secrets:
            users[str(st.secrets["SUITE_USER"])] = str(st.secrets["SUITE_PASS"])

        # Esquema [auth]
        if "auth" in st.secrets:
            auth = st.secrets["auth"]

            # auth.users = tabla de usuarios adicionales
            if "users" in auth:
                # auth["users"] puede ser un mapeo tipo Config/Section → lo forzamos a dict
                users.update({str(k): str(v) for k, v in dict(auth["users"]).items()})

            # default_user / default_password opcionales
            du = auth.get("default_user")
            dp = auth.get("default_password")
            if du and dp:
                users.setdefault(str(du), str(dp))
    except Exception:
        # No tumbar la app si falta algo en secrets
        pass

    # Extra: si alguien definió [users] directamente en la raíz (compat muy viejo)
    try:
        if "users" in st.secrets:
            root_users = dict(st.secrets["users"])
            users.update({str(k): str(v) for k, v in root_users.items()})
    except Exception:
        pass

    return users


def _fallback_users():
    # Solo para desarrollo/local; en producción configure secrets.toml
    return {"admin": "1234"}


def _get_user_db():
    db = _load_credentials_from_secrets()
    return db if db else _fallback_users()


USERS = _get_user_db()


def _get_owner_user():
    """
    Determina quién es el 'owner' principal de la suite:

    1) auth.owner_user (si existe)
    2) SUITE_USER (si existe)
    3) Primer usuario del diccionario USERS
    """
    # 1) [auth].owner_user
    try:
        if "auth" in st.secrets and "owner_user" in st.secrets["auth"]:
            return str(st.secrets["auth"]["owner_user"])
    except Exception:
        pass

    # 2) SUITE_USER simple
    try:
        if "SUITE_USER" in st.secrets:
            return str(st.secrets["SUITE_USER"])
    except Exception:
        pass

    # 3) Primer usuario configurado
    try:
        return next(iter(USERS.keys()))
    except StopIteration:
        return "admin"


OWNER_USER = _get_owner_user()


# =========================
#  CHECK CREDENTIALS
# =========================

def check_credentials(username: str, password: str):
    """
    Devuelve el rol si las credenciales son válidas:
    - 'owner' -> usuario principal de la suite
    - 'user'  -> usuario normal / demo / cliente
    - None    -> credenciales inválidas
    """
    if not username or not password:
        return None

    username = str(username)
    password = str(password)

    real = USERS.get(username)
    if real is None:
        return None

    if str(real) != password:
        return None

    if username == OWNER_USER:
        return "owner"
    return "user"


# =========================
#  LOGIN GUARD (UI tipo app.py)
# =========================

def _ensure_session_keys():
    st.session_state.setdefault("logged_in", False)
    st.session_state.setdefault("suite_auth", False)  # compat con páginas viejas
    st.session_state.setdefault("user_role", None)
    st.session_state.setdefault("user_name", None)
    st.session_state.setdefault("username", "")       # el que usa app.py
    st.session_state.setdefault("remember", True)


def login_guard(page_name: str = "Suite Go Mapper"):
    """
    Bloquea la página hasta que el usuario inicie sesión.

    Uso:
        from guardian import login_guard
        login_guard("Limpieza de CDR")

    Comportamiento:
    - Si ya inició sesión en app.py (logged_in/suite_auth = True), deja pasar directo.
    - Si entra directo a esta página, muestra un login con la MISMA interfaz que app.py.
    """
    _ensure_session_keys()

    # Si ya está autenticado (desde portada o desde otro módulo), no pedimos login de nuevo
    if st.session_state.get("logged_in") or st.session_state.get("suite_auth"):
        return True

    # Interfaz igualita a app.py
    st.title("🗺️ Go Mapper Suite")
    st.subheader("Acceso")
    st.caption(f"Módulo actual: {page_name}")

    with st.form("login_guard_form"):
        c1, c2 = st.columns(2)
        with c1:
            u = st.text_input("Usuario")
        with c2:
            p = st.text_input("Contraseña", type="password")
        remember = st.checkbox("Recordarme en esta sesión", value=True)
        ok = st.form_submit_button("Entrar")

    if ok:
        role = check_credentials(u.strip(), p)
        if role is not None:
            st.session_state["logged_in"]  = True
            st.session_state["suite_auth"] = True  # para guards antiguos
            st.session_state["user_role"]  = role
            st.session_state["user_name"]  = u.strip()
            st.session_state["username"]   = u.strip()  # lo que usa app.py en el saludo
            st.session_state["remember"]   = bool(remember)

            st.success(f"Bienvenido, {u} 👋")
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")

    # Si todavía no pasa, cortamos ejecución del módulo
    st.stop()
