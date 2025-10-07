# auth.py (TU CÓDIGO, CORREGIDO Y OPTIMIZADO)

import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

# No necesitas st.set_page_config aquí, ya lo tienes en app.py
# st.set_page_config(layout="wide")

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid',
]

# Es mejor usar el diccionario de st.secrets directamente para más claridad
CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets["GOOGLE_CLIENT_ID"],
        "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
        "redirect_uris": [st.secrets["GOOGLE_REDIRECT_URI"]],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

def get_google_flow():
    """Crea y devuelve el objeto Flow de Google OAuth."""
    return Flow.from_client_config(
        client_config=CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=st.secrets["GOOGLE_REDIRECT_URI"]
    )

def get_credentials():
    """
    Gestiona el flujo de autenticación de forma robusta para Streamlit.
    """
    
    # --- PASO 1: VERIFICAR SI YA TENEMOS CREDENCIALES VÁLIDAS EN LA SESIÓN ---
    if 'credentials_info' in st.session_state:
        creds_info = st.session_state['credentials_info']
        
        # Reconstruir el objeto Credentials a partir de la info guardada
        creds = Credentials.from_authorized_user_info(creds_info, SCOPES)

        # Comprobar si los scopes han cambiado
        if not all(scope in creds.scopes for scope in SCOPES):
            # Si faltan scopes, las credenciales no son válidas. Las borramos y empezamos de nuevo.
            del st.session_state['credentials_info']
            st.rerun() # Forzamos recarga para que el usuario se loguee de nuevo
        
        # Comprobar si el token ha expirado y refrescarlo si es posible
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Actualizamos la información en el session_state
                st.session_state['credentials_info'] = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes
                }
            except Exception as e:
                # Si el refresh token falla (p.ej. ha sido revocado), borramos credenciales
                del st.session_state['credentials_info']
                st.rerun()
        
        # Si llegamos aquí, las credenciales son válidas
        return creds

    # --- PASO 2: SI NO HAY CREDENCIALES, VERIFICAR SI GOOGLE NOS HA DEVUELTO UN CÓDIGO ---
    # Usamos try-except porque st.query_params puede dar error al inicio
    try:
        code = st.query_params.get('code')
    except:
        code = None
        
    if code:
        try:
            flow = get_google_flow()
            flow.fetch_token(code=code)
            
            # ¡CAMBIO CLAVE! Guardamos la información como un diccionario simple, no como un objeto.
            # Esto es mucho más estable en Streamlit.
            creds = flow.credentials
            st.session_state['credentials_info'] = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }

            # Limpiamos la URL y forzamos una recarga.
            # En la siguiente ejecución, el PASO 1 encontrará las credenciales y las devolverá.
            st.query_params.clear()
            st.rerun()

        except Exception as e:
            # Si hay un error, lo mostramos y limpiamos el estado.
            st.error(f"Error al obtener el token: {e}")
            if 'credentials_info' in st.session_state:
                del st.session_state['credentials_info']
            st.button("Reintentar inicio de sesión")
            st.stop()
            
    # --- PASO 3: SI NO HAY NI CREDENCIALES NI CÓDIGO, EL USUARIO NO ESTÁ LOGUEADO ---
    return None
    
def build_drive_service(credentials):
    """Construye y devuelve el objeto de servicio de la API de Drive."""
    try:
        return build('drive', 'v3', credentials=credentials)
    except HttpError as error:
        st.error(f"No se pudo crear el servicio de Drive: {error}")
        return None
