import io
import re
import time
import streamlit as st
import httplib2
import docx  # <--- NUEVO: Añadido para leer archivos de Word
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from utils import OPCION_ANALISIS_GENERAL # <--- NUEVO: Para manejar el caso de análisis general

# Constante para el nombre de la carpeta raíz de la aplicación en Drive
ROOT_FOLDER_NAME = "ProyectosLicitaciones"


def find_or_create_folder(service, folder_name, parent_id=None, retries=3):
    """Busca una carpeta. Si no la encuentra, la crea. Incluye reintentos para errores de red."""
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    
    for attempt in range(retries):
        try:
            response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            files = response.get('files', [])
            if files:
                return files[0]['id']
            else:
                file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
                if parent_id:
                    file_metadata['parents'] = [parent_id]
                folder = service.files().create(body=file_metadata, fields='id').execute()
                st.toast(f"Carpeta '{folder_name}' creada en tu Drive.")
                return folder.get('id')
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                st.toast(f"⏳ Error de red con Drive ({type(e).__name__}). Reintentando... ({attempt + 2}/{retries})")
                time.sleep(2 ** attempt)
            else:
                st.error("❌ No se pudo conectar con Google Drive. Por favor, refresca la página.")
                raise
        except Exception as e:
            st.error(f"Ocurrió un error inesperado con Google Drive: {e}")
            raise

def upload_file_to_drive(service, file_object, folder_id, retries=3):
    """Sube un objeto de archivo a una carpeta de Drive, con reintentos."""
    for attempt in range(retries):
        try:
            file_metadata = {'name': file_object.name, 'parents': [folder_id]}
            file_object.seek(0) 
            media = MediaIoBaseUpload(file_object, mimetype=file_object.type, resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            st.toast(f"📄 Archivo '{file_object.name}' guardado en Drive.")
            return file.get('id')
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                st.toast(f"⏳ Error de red al subir archivo. Reintentando... ({attempt + 2}/{retries})")
                time.sleep(2 ** attempt)
            else:
                st.error(f"❌ No se pudo subir el archivo '{file_object.name}' tras varios intentos.")
                raise
        except Exception as e:
            st.error(f"Error inesperado al subir archivo: {e}")
            raise

def delete_file_from_drive(service, file_id, retries=3):
    """Elimina un archivo o carpeta de Drive por su ID, con reintentos."""
    for attempt in range(retries):
        try:
            service.files().delete(fileId=file_id).execute()
            return True
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                st.toast(f"⏳ Error de red al eliminar. Reintentando... ({attempt + 2}/{retries})")
                time.sleep(2 ** attempt)
            else:
                st.error(f"❌ No se pudo eliminar el archivo/carpeta tras varios intentos.")
                return False
        except HttpError as error:
            st.error(f"No se pudo eliminar el archivo: {error}")
            return False

def find_file_by_name(service, file_name, folder_id, retries=3):
    """Busca un archivo por nombre dentro de una carpeta, con reintentos."""
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    for attempt in range(retries):
        try:
            response = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            files = response.get('files', [])
            return files[0]['id'] if files else None
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                st.toast(f"⏳ Error de red buscando archivo. Reintentando... ({attempt + 2}/{retries})")
                time.sleep(2 ** attempt)
            else:
                st.error(f"❌ No se pudo buscar el archivo '{file_name}' tras varios intentos.")
                raise
        except Exception as e:
            st.error(f"Error inesperado al buscar archivo: {e}")
            raise
    
def download_file_from_drive(service, file_id, retries=3):
    """Descarga el contenido de un archivo de Drive, con reintentos."""
    for attempt in range(retries):
        try:
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                st.toast(f"⏳ Error de red al descargar. Reintentando... ({attempt + 2}/{retries})")
                time.sleep(2 ** attempt)
            else:
                st.error(f"❌ No se pudo descargar el archivo tras varios intentos.")
                raise
        except Exception as e:
            st.error(f"Error inesperado al descargar: {e}")
            raise

def list_project_folders(service, root_folder_id, retries=3):
    """Lista las subcarpetas (proyectos) dentro de la carpeta raíz, con reintentos."""
    query = f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    for attempt in range(retries):
        try:
            response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            return {file['name']: file['id'] for file in response.get('files', [])}
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                st.toast(f"⏳ Error de red listando proyectos. Reintentando... ({attempt + 2}/{retries})")
                time.sleep(2 ** attempt)
            else:
                st.error("❌ No se pudieron listar los proyectos de Drive tras varios intentos.")
                return {} # Devolvemos un diccionario vacío en caso de fallo final
        except Exception as e:
            st.error(f"Error inesperado al listar proyectos: {e}")
            return {}

def get_files_in_project(service, project_folder_id):
    """Obtiene los archivos dentro de una carpeta de proyecto."""
    query = f"'{project_folder_id}' in parents and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name, mimeType)').execute()
    return response.get('files', [])

def sync_guiones_folders_with_index(service, project_folder_id, new_index_structure):
    """
    Compara las carpetas de guiones existentes en Drive con el nuevo índice.
    Elimina las carpetas que ya no corresponden a ningún subapartado.
    """
    # NOTA: Esta función necesitará ser adaptada en el siguiente paso para que
    # apunte a la carpeta del lote activo, no directamente a 'project_folder_id'.
    # Por ahora, se mantiene como está para no romper la Fase 2 actual.
    
    st.toast("🔄 Sincronizando carpetas de guiones con el nuevo índice...")
    expected_folders = set()
    if 'estructura_memoria' in new_index_structure:
        for seccion in new_index_structure.get('estructura_memoria', []):
            for subapartado_titulo in seccion.get('subapartados', []):
                nombre_limpio = re.sub(r'[\\/*?:"<>|]', "", subapartado_titulo)
                expected_folders.add(nombre_limpio)
    
    if not expected_folders:
        st.warning("El nuevo índice no contiene subapartados. No se realizó ninguna limpieza.")
        return 0

    guiones_main_folder_id = find_or_create_folder(service, "Guiones de Subapartados", parent_id=project_folder_id)
    existing_folders_map = list_project_folders(service, guiones_main_folder_id)

    deleted_count = 0
    folders_to_delete = []
    for folder_name, folder_id in existing_folders_map.items():
        if folder_name not in expected_folders:
            folders_to_delete.append((folder_name, folder_id))

    if not folders_to_delete:
        st.toast("✅ Las carpetas de guiones ya estaban sincronizadas.")
        return 0
        
    with st.spinner(f"Eliminando {len(folders_to_delete)} carpetas de guiones obsoletas..."):
        for folder_name, folder_id in folders_to_delete:
            if delete_file_from_drive(service, folder_id):
                st.toast(f"🗑️ Carpeta obsoleta eliminada: '{folder_name}'")
                deleted_count += 1
            else:
                st.warning(f"No se pudo eliminar la carpeta obsoleta: '{folder_name}'")
    
    return deleted_count

# =============================================================================
#           NUEVAS FUNCIONES PARA GESTIÓN DE LOTES Y CONTEXTO
# =============================================================================

def clean_folder_name(name):
    """Limpia un string para que sea un nombre de carpeta válido en Drive."""
    if name == OPCION_ANALISIS_GENERAL:
        return "Analisis_General"
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def get_or_create_lot_folder_id(service, project_folder_id):
    """
    Obtiene el ID de la carpeta para el lote/bloque actualmente seleccionado en la sesión.
    Si no existe, la crea. Maneja el caso de "Análisis General".
    """
    selected_lot = st.session_state.get('selected_lot')
    if not selected_lot:
        st.error("Error crítico: No se ha seleccionado ningún lote en la sesión.")
        return None

    # Usamos la función de limpieza para obtener un nombre de carpeta consistente
    lot_folder_name = clean_folder_name(selected_lot)

    # Busca o crea esta carpeta directamente dentro de la carpeta del proyecto
    lot_folder_id = find_or_create_folder(service, lot_folder_name, parent_id=project_folder_id)
    return lot_folder_id

def get_text_from_docx(file_bytes):
    """Extrae el texto de un objeto de bytes de un archivo .docx."""
    try:
        # file_bytes es el objeto BytesIO devuelto por download_file_from_drive
        doc = docx.Document(io.BytesIO(file_bytes.getvalue()))
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        st.warning(f"No se pudo leer un archivo .docx para el contexto: {e}")
        return ""

def get_context_from_lots(service, project_folder_id, context_lot_names):
    """
    Recopila todo el texto de los guiones generados para una lista de lotes
    y lo formatea como un string de contexto para la IA.
    """
    if not context_lot_names:
        return ""

    final_context_str = "\n\n--- INICIO DEL CONTEXTO DE LOTES RELACIONADOS ---\n"
    
    with st.spinner(f"Cargando contexto desde {len(context_lot_names)} lote(s)..."):
        # Obtiene un mapa de todos los subdirectorios del proyecto (que ahora son los lotes)
        all_project_folders = list_project_folders(service, project_folder_id)
        
        for lot_name in context_lot_names:
            # Busca la carpeta del lote por su nombre limpio
            clean_name = clean_folder_name(lot_name)
            if clean_name in all_project_folders:
                lot_folder_id = all_project_folders[clean_name]
                # Busca la carpeta 'Guiones de Subapartados' DENTRO de la carpeta del lote
                guiones_folder_id = find_file_by_name(service, "Guiones de Subapartados", lot_folder_id)
                
                if guiones_folder_id:
                    final_context_str += f"\n--- Contenido del '{lot_name}' ---\n"
                    # Lista las carpetas de cada subapartado dentro de la carpeta de guiones
                    subapartado_folders = list_project_folders(service, guiones_folder_id)
                    
                    for sub_name, sub_id in subapartado_folders.items():
                        guion_files = get_files_in_project(service, sub_id)
                        # Busca el archivo .docx del guion
                        docx_file = next((f for f in guion_files if f['name'].endswith('.docx')), None)
                        if docx_file:
                            file_bytes = download_file_from_drive(service, docx_file['id'])
                            texto = get_text_from_docx(file_bytes)
                            final_context_str += f"\n**Subapartado: {sub_name}**\n{texto}\n"
    
    final_context_str += "\n--- FIN DEL CONTEXTO DE LOTES RELACIONADOS ---\n"
    return final_context_str
