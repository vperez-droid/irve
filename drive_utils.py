import io
import re
import time
import streamlit as st
import httplib2
import docx
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

ROOT_FOLDER_NAME = "ProyectosLicitaciones"

# --- OPTIMIZACIÓN APLICADA ---
# Se añade @st.cache_data a las funciones de lectura.
# El argumento 'service' se renombra a '_service' para que el decorador lo ignore.

@st.cache_data
def find_or_create_folder(_service, folder_name, parent_id=None, retries=3):
    """
    Busca una carpeta. Si no la encuentra, la crea.
    Cacheada porque la parte de 'buscar' es una operación de lectura.
    """
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    
    for attempt in range(retries):
        try:
            response = _service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            files = response.get('files', [])
            if files:
                return files[0]['id']
            else:
                # Si la carpeta no existe, la creamos y limpiamos el caché para
                # que la próxima llamada refleje el cambio.
                st.cache_data.clear()
                file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
                if parent_id:
                    file_metadata['parents'] = [parent_id]
                folder = _service.files().create(body=file_metadata, fields='id').execute()
                st.toast(f"Carpeta '{folder_name}' creada en tu Drive.")
                return folder.get('id')
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else: raise
        except Exception as e:
            st.error(f"Ocurrió un error inesperado con Google Drive: {e}")
            raise

def upload_file_to_drive(service, file_object, folder_id, retries=3):
    """
    Sube un objeto de archivo a una carpeta de Drive.
    Esta es una operación de escritura, por lo que NO se cachea.
    """
    # Al final de una subida exitosa, limpiamos el caché de las funciones
    # que listan archivos para que reflejen el nuevo fichero.
    st.cache_data.clear()
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
                time.sleep(2 ** attempt)
            else: raise
        except Exception as e:
            st.error(f"Error inesperado al subir archivo: {e}")
            raise

def delete_file_from_drive(service, file_id, retries=3):
    """
    Elimina un archivo o carpeta. Operación de escritura, NO se cachea.
    """
    # Limpiamos el caché para reflejar la eliminación.
    st.cache_data.clear()
    for attempt in range(retries):
        try:
            service.files().delete(fileId=file_id).execute()
            return True
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else: return False
        except HttpError as error:
            st.error(f"No se pudo eliminar el archivo: {error}")
            return False

@st.cache_data
def find_file_by_name(_service, file_name, folder_id, retries=3):
    """Busca un archivo por nombre dentro de una carpeta, con reintentos."""
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    for attempt in range(retries):
        try:
            response = _service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            files = response.get('files', [])
            return files[0]['id'] if files else None
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else: raise
        except Exception as e:
            st.error(f"Error inesperado al buscar archivo: {e}")
            raise


@st.cache_data
def download_file_from_drive_cached(_service, file_id, retries=3):
    """
    Descarga el contenido de un archivo de Drive.
    USA EL CACHÉ. Solo debe ser llamada desde el hilo principal de Streamlit.
    """
    for attempt in range(retries):
        try:
            request = _service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else: raise
        except Exception as e:
            st.error(f"Error inesperado al descargar (cached): {e}")
            raise


def download_file_from_drive_uncached(service, file_id, retries=3):
    """
    Descarga el contenido de un archivo de Drive.
    NO USA EL CACHÉ. Es segura para ser llamada desde múltiples hilos.
    """
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
                time.sleep(2 ** attempt)
            else: raise
        except Exception as e:
            print(f"ERROR en hilo de descarga (uncached) para file_id {file_id}: {e}")
            raise


@st.cache_data
def list_project_folders(_service, root_folder_id, retries=3):
    """Lista las subcarpetas (proyectos) dentro de la carpeta raíz, con reintentos."""
    query = f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    for attempt in range(retries):
        try:
            response = _service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            return {file['name']: file['id'] for file in response.get('files', [])}
        except (TimeoutError, httplib2.ServerNotFoundError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else: return {} 
        except Exception as e:
            st.error(f"Error inesperado al listar proyectos: {e}")
            return {}

@st.cache_data
def get_files_in_project(_service, project_folder_id):
    """Obtiene los archivos dentro de una carpeta de proyecto."""
    query = f"'{project_folder_id}' in parents and trashed = false"
    response = _service.files().list(q=query, spaces='drive', fields='files(id, name, mimeType)').execute()
    return response.get('files', [])
    
# El resto de las funciones en drive_utils.py no se modifican ya que
# o bien son wrappers de otras funciones o realizan operaciones de escritura
# que no deben ser cacheadas.
def clean_folder_name(name):
    """Limpia un string para que sea un nombre de carpeta válido en Drive."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def get_or_create_lot_folder_id(service, project_folder_id, lot_name):
    """
    Obtiene el ID de la carpeta para un lote/bloque específico.
    Si no existe, la crea.
    """
    if not lot_name:
        return None
    lot_folder_name = clean_folder_name(lot_name)
    if not lot_folder_name:
        return None
    # Llama a la función cacheada para buscar o crear la carpeta
    return find_or_create_folder(service, lot_folder_name, parent_id=project_folder_id)

@st.cache_data
def get_text_from_docx(_service, file_bytes):
    """Extrae el texto de un objeto de bytes de un archivo .docx."""
    try:
        doc = docx.Document(io.BytesIO(file_bytes.getvalue()))
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        st.warning(f"No se pudo leer un archivo .docx para el contexto: {e}")
        return ""

def get_context_from_lots(service, project_folder_id, context_lot_names):
    """
    Recopila todo el texto de los guiones generados para una lista de lotes.
    """
    if not context_lot_names:
        return ""

    final_context_str = "\n\n--- INICIO DEL CONTEXTO DE LOTES RELACIONADOS ---\n"
    
    # Usamos st.spinner aquí porque es una operación de cara al usuario
    with st.spinner(f"Cargando contexto desde {len(context_lot_names)} lote(s)..."):
        # Obtiene una lista de todas las subcarpetas del proyecto de una vez
        query = f"'{project_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        all_project_folders = {file['name']: file['id'] for file in response.get('files', [])}
        
        for lot_name in context_lot_names:
            clean_name = clean_folder_name(lot_name)
            lot_folder_id = all_project_folders.get(clean_name)
            
            if lot_folder_id:
                guiones_folder_id = find_file_by_name(service, "Guiones de Subapartados", lot_folder_id)
                
                if guiones_folder_id:
                    final_context_str += f"\n--- Contenido del Lote: '{lot_name}' ---\n"
                    # Obtenemos las carpetas de los subapartados
                    query_sub = f"'{guiones_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
                    response_sub = service.files().list(q=query_sub, spaces='drive', fields='files(id, name)').execute()
                    subapartado_folders = {file['name']: file['id'] for file in response_sub.get('files', [])}
                    
                    for sub_name, sub_id in subapartado_folders.items():
                        guion_files = get_files_in_project(service, sub_id)
                        docx_file = next((f for f in guion_files if f['name'].endswith('.docx')), None)
                        if docx_file:
                            # -------- ¡AQUÍ ESTÁ LA CORRECCIÓN! --------
                            # Se usa la función correcta que sí existe.
                            file_bytes = download_file_from_drive_uncached(service, docx_file['id'])
                            texto = get_text_from_docx(service, file_bytes)
                            final_context_str += f"\n**Subapartado: {sub_name}**\n{texto}\n"
    
    final_context_str += "\n--- FIN DEL CONTEXTO DE LOTES RELACIONADOS ---\n"
    return final_context_str

def sync_guiones_folders_with_index(service, active_lot_folder_id, index_structure):
    """
    Crea las carpetas para los guiones en Google Drive.
    """
    try:
        if not index_structure or 'estructura_memoria' not in index_structure:
            return

        guiones_main_folder_id = find_or_create_folder(service, "Guiones de Subapartados", parent_id=active_lot_folder_id)
        estructura = index_structure.get('estructura_memoria', [])
        hay_subapartados = any(seccion.get('subapartados') for seccion in estructura)

        if hay_subapartados:
            for seccion in estructura:
                for subapartado_titulo in seccion.get('subapartados', []):
                    if subapartado_titulo:
                        folder_name = clean_folder_name(subapartado_titulo)
                        find_or_create_folder(service, folder_name, parent_id=guiones_main_folder_id)
        else:
            for seccion in estructura:
                apartado_titulo = seccion.get('apartado')
                if apartado_titulo:
                    folder_name = clean_folder_name(apartado_titulo)
                    find_or_create_folder(service, folder_name, parent_id=guiones_main_folder_id)
    except Exception as e:
        st.error(f"Error durante la sincronización de carpetas: {e}")
