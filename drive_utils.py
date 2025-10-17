# drive_utils.py (VERSIÓN MODIFICADA Y CORREGIDA)

import io
import re
import time
import streamlit as st
import httplib2
import docx
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
# --- ELIMINADA LA IMPORTACIÓN CIRCULAR ---
# from utils import OPCION_ANALISIS_GENERAL <--- ¡ESTA LÍNEA SE HA QUITADO!

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
                return {} 
        except Exception as e:
            st.error(f"Error inesperado al listar proyectos: {e}")
            return {}

def get_files_in_project(service, project_folder_id):
    """Obtiene los archivos dentro de una carpeta de proyecto."""
    query = f"'{project_folder_id}' in parents and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name, mimeType)').execute()
    return response.get('files', [])


    guiones_main_folder_id = find_or_create_folder(service, "Guiones de Subapartados", parent_id=parent_folder_id)
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
    # Esta función ahora es más simple
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def get_or_create_lot_folder_id(service, project_folder_id, lot_name):
    """
    Obtiene el ID de la carpeta para un lote/bloque específico.
    Si no existe, la crea. Esta función ahora requiere un 'lot_name'.
    """
    if not lot_name:
        st.error("Error crítico: Se intentó crear una carpeta de lote sin un nombre.")
        return None

    # Usamos la función de limpieza para obtener un nombre de carpeta consistente
    lot_folder_name = clean_folder_name(lot_name)
    if not lot_folder_name: # Si el nombre queda vacío tras la limpieza
        st.error(f"Error: El nombre del lote '{lot_name}' no es válido para una carpeta.")
        return None

    # Busca o crea esta carpeta directamente dentro de la carpeta del proyecto
    lot_folder_id = find_or_create_folder(service, lot_folder_name, parent_id=project_folder_id)
    return lot_folder_id

def get_text_from_docx(file_bytes):
    """Extrae el texto de un objeto de bytes de un archivo .docx."""
    try:
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
        all_project_folders = list_project_folders(service, project_folder_id)
        
        for lot_name in context_lot_names:
            clean_name = clean_folder_name(lot_name)
            if clean_name in all_project_folders:
                lot_folder_id = all_project_folders[clean_name]
                
                # Busca la carpeta 'Guiones de Subapartados' DENTRO de la carpeta del lote
                guiones_folder_id = find_file_by_name(service, "Guiones de Subapartados", lot_folder_id)
                
                if guiones_folder_id:
                    final_context_str += f"\n--- Contenido del '{lot_name}' ---\n"
                    subapartado_folders = list_project_folders(service, guiones_folder_id)
                    
                    for sub_name, sub_id in subapartado_folders.items():
                        guion_files = get_files_in_project(service, sub_id)
                        docx_file = next((f for f in guion_files if f['name'].endswith('.docx')), None)
                        if docx_file:
                            file_bytes = download_file_from_drive(service, docx_file['id'])
                            texto = get_text_from_docx(file_bytes)
                            final_context_str += f"\n**Subapartado: {sub_name}**\n{texto}\n"
    
    final_context_str += "\n--- FIN DEL CONTEXTO DE LOTES RELACIONADOS ---\n"
    return final_context_str

# En drive_utils.py, añade esta función al final del archivo

def sync_guiones_folders_with_index(service, active_lot_folder_id, index_structure):
    """
    Lee la estructura de un índice y crea las carpetas correspondientes para los guiones
    en Google Drive si no existen.
    """
    try:
        if not index_structure or 'estructura_memoria' not in index_structure:
            print("Advertencia: La estructura del índice está vacía o es inválida. No se crearán carpetas.")
            return

        # 1. Asegurarse de que la carpeta principal "Guiones de Subapartados" existe
        guiones_main_folder_id = find_or_create_folder(service, "Guiones de Subapartados", parent_id=active_lot_folder_id)

        estructura = index_structure.get('estructura_memoria', [])
        
        # 2. Determinar si el índice tiene subapartados o solo apartados principales
        hay_subapartados = any(seccion.get('subapartados') for seccion in estructura)

        if hay_subapartados:
            # Si hay subapartados, crear una carpeta para cada uno
            for seccion in estructura:
                for subapartado_titulo in seccion.get('subapartados', []):
                    if subapartado_titulo:
                        folder_name = clean_folder_name(subapartado_titulo)
                        find_or_create_folder(service, folder_name, parent_id=guiones_main_folder_id)
        else:
            # Si no hay subapartados, crear una carpeta para cada apartado principal
            for seccion in estructura:
                apartado_titulo = seccion.get('apartado')
                if apartado_titulo:
                    folder_name = clean_folder_name(apartado_titulo)
                    find_or_create_folder(service, folder_name, parent_id=guiones_main_folder_id)
        
        print("Sincronización de carpetas completada con éxito.")

    except Exception as e:
        print(f"Error durante la sincronización de carpetas con el índice: {e}")
        # En una app de Streamlit, podrías usar st.warning o st.error aquí.
