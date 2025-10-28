import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid',
]

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
    if 'credentials_info' in st.session_state:
        creds_info = st.session_state['credentials_info']
        creds = Credentials.from_authorized_user_info(creds_info, SCOPES)

        if not all(scope in creds.scopes for scope in SCOPES):
            del st.session_state['credentials_info']
            st.rerun()
        
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                st.session_state['credentials_info'] = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes
                }
            except Exception as e:
                del st.session_state['credentials_info']
                st.rerun()
        
        return creds

    try:
        code = st.query_params.get('code')
    except:
        code = None
        
    if code:
        try:
            flow = get_google_flow()
            flow.fetch_token(code=code)
            
            creds = flow.credentials
            st.session_state['credentials_info'] = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }

            st.query_params.clear()
            st.rerun()

        except Exception as e:
            st.error(f"Error al obtener el token: {e}")
            if 'credentials_info' in st.session_state:
                del st.session_state['credentials_info']
            st.button("Reintentar inicio de sesión")
            st.stop()
            
    return None

# OPTIMIZACIÓN APLICADA AQUÍ
@st.cache_resource
def build_drive_service(credentials):
    """
    Construye y devuelve el objeto de servicio de la API de Drive.
    Gracias a @st.cache_resource, este objeto se crea una vez y se reutiliza.
    """
    try:
        # El objeto 'credentials' se pasa como argumento para que el caché sepa
        # cuándo debe volver a ejecutar la función (si las credenciales cambian).
        return build('drive', 'v3', credentials=credentials)
    except HttpError as error:
        st.error(f"No se pudo crear el servicio de Drive: {error}")
        return None
