# app.py (VERSIÓN OPTIMIZADA)
# -----------------------------------------------------------------------------
# Este es el punto de entrada principal de la aplicación Streamlit.
# Actúa como el "director de orquesta": gestiona la autenticación, el estado
# de la sesión, la navegación y llama a la función de la página correcta
# desde el módulo ui_pages.
# -----------------------------------------------------------------------------

import streamlit as st
import google.generativeai as genai
import json
import time

# =============================================================================
#           BLOQUE DE IMPORTACIONES DE OTROS MÓDulos
# =============================================================================

# La llamada a build_drive_service ahora usará la versión cacheada de auth.py
from auth import get_credentials, build_drive_service
from ui_pages import (
    landing_page, 
    project_selection_page,
    phase_1_viability_page,
    phase_2_structure_page,
    phase_2_results_page,
    phase_3_page,
    phase_4_page,
    phase_5_page,
    phase_6_page
)
from prompts import PROMPT_PLIEGOS

# Las funciones de utils no cambian
from utils import (
    limpiar_respuesta_json, 
    convertir_excel_a_texto_csv, 
    get_lot_context, 
    OPCION_ANALISIS_GENERAL
)

# Todas estas llamadas ahora usarán las versiones cacheadas de drive_utils.py,
# haciendo la app mucho más rápida en operaciones repetitivas.
from drive_utils import find_or_create_folder, get_files_in_project, download_file_from_drive

# =============================================================================
#           CONFIGURACIÓN GLOBAL Y GESTIÓN DE ESTADO
# =============================================================================

st.set_page_config(layout="wide")

# --- Inicialización de Estado (sin cambios) ---
if 'page' not in st.session_state: st.session_state.page = 'landing'
if 'credentials' not in st.session_state: st.session_state.credentials = None
if 'drive_service' not in st.session_state: st.session_state.drive_service = None
if 'selected_project' not in st.session_state: st.session_state.selected_project = None
if 'detected_lotes' not in st.session_state: st.session_state.detected_lotes = None
if 'selected_lot' not in st.session_state: st.session_state.selected_lot = None
if 'requisitos_extraidos' not in st.session_state: st.session_state.requisitos_extraidos = None
if 'generated_structure' not in st.session_state: st.session_state.generated_structure = None
if 'uploaded_pliegos' not in st.session_state: st.session_state.uploaded_pliegos = None
if 'generated_doc_buffer' not in st.session_state: st.session_state.generated_doc_buffer = None
if 'generated_doc_filename' not in st.session_state: st.session_state.generated_doc_filename = ""
if 'refined_doc_buffer' not in st.session_state: st.session_state.refined_doc_buffer = None
if 'refined_doc_filename' not in st.session_state: st.session_state.refined_doc_filename = ""


# --- Funciones de Navegación (sin cambios) ---
def go_to_landing(): st.session_state.page = 'landing'
def go_to_project_selection(): st.session_state.page = 'project_selection'
def go_to_phase1(): st.session_state.page = 'phase_1_viability'
def go_to_phase2(): st.session_state.page = 'phase_2_structure'
def go_to_phase2_results(): st.session_state.page = 'phase_2_results'
def go_to_phase3(): st.session_state.page = 'phase_3_guiones'
def go_to_phase4(): st.session_state.page = 'phase_4_prompts'
def go_to_phase5(): st.session_state.page = 'phase_5_redaccion'
def go_to_phase6(): st.session_state.page = 'phase_6_ensamblaje'

# --- Función de Limpieza (sin cambios) ---
def back_to_project_selection_and_cleanup():
    """Limpia el estado de la sesión relacionado con un proyecto específico."""
    keys_to_clear = [
        'requisitos_extraidos', 'generated_structure', 'uploaded_pliegos', 
        'selected_project', 'generated_doc_buffer', 'refined_doc_buffer', 
        'generated_doc_filename', 'refined_doc_filename', 'project_language',
        'detected_lotes', 'selected_lot' 
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    go_to_project_selection()

# =============================================================================
#           LÓGICA CENTRAL DE LA APLICACIÓN (NO-UI)
# =============================================================================

def handle_full_regeneration(model):
    """
    Función que genera un índice desde cero analizando los archivos de 'Pliegos'.
    NOTA DE OPTIMIZACIÓN: Esta función ahora es mucho más rápida en ejecuciones
    repetidas porque las funciones subyacentes (get_files_in_project, 
    download_file_from_drive) están cacheadas.
    """
    if not st.session_state.get('drive_service') or not st.session_state.get('selected_project'):
        st.error("Error de sesión. No se puede iniciar la regeneración."); return False

    with st.spinner("Descargando y analizando archivos para generar índice..."):
        response = None
        try:
            service = st.session_state.drive_service
            project_folder_id = st.session_state.selected_project['id']
            
            # Estas llamadas ahora usan el caché de Streamlit
            pliegos_folder_id = find_or_create_folder(service, "Pliegos", parent_id=project_folder_id)
            document_files = get_files_in_project(service, pliegos_folder_id)

            if not document_files:
                st.warning("No se encontraron archivos en la carpeta 'Pliegos' para analizar."); return False

            idioma_seleccionado = st.session_state.get('project_language', 'Español')
            contexto_lote = get_lot_context()
            prompt_con_idioma = PROMPT_PLIEGOS.format(idioma=idioma_seleccionado, contexto_lote=contexto_lote)
            
            contenido_ia = [prompt_con_idioma]

            for file in document_files:
                # Esta descarga será casi instantánea después de la primera vez
                file_content_bytes = download_file_from_drive(service, file['id'])
                nombre_archivo = file['name']
                
                if nombre_archivo.lower().endswith('.xlsx'):
                    texto_csv = convertir_excel_a_texto_csv(file_content_bytes, nombre_archivo)
                    if texto_csv:
                        contenido_ia.append(texto_csv)
                else:
                    contenido_ia.append({"mime_type": file['mimeType'], "data": file_content_bytes.getvalue()})

            # La llamada a la API sigue siendo el paso que consume más tiempo, como es de esperar.
            response = model.generate_content(contenido_ia, generation_config={"response_mime_type": "application/json"})
            
            # El resto de la lógica de manejo de errores no cambia
            if not response or not response.candidates:
                st.error("La IA no generó una respuesta. Esto puede deberse a filtros de seguridad o un problema temporal.")
                if response and hasattr(response, 'prompt_feedback'): st.code(f"Razón del bloqueo: {response.prompt_feedback}")
                else: st.code("La respuesta de la API estuvo vacía o fue inválida.")
                return False

            json_limpio_str = limpiar_respuesta_json(response.text)
            if json_limpio_str:
                st.session_state.generated_structure = json.loads(json_limpio_str)
                st.session_state.uploaded_pliegos = document_files
                st.toast("✅ ¡Índice regenerado desde cero con éxito!")
                return True
            else:
                st.error("La IA devolvió una respuesta vacía o no válida (después de la limpieza)."); return False
                
        except json.JSONDecodeError as e:
            st.error(f"Error de formato: La IA devolvió una respuesta que no es un JSON válido. Error: {e}")
            if response: st.code(response.text)
            return False
        except Exception as e:
            st.error(f"Ocurrió un error inesperado durante la regeneración completa: {e}")
            if response: st.code(response.text)
            return False

# =============================================================================
#                        LÓGICA PRINCIPAL (ROUTER)
# =============================================================================

credentials = get_credentials()

if not credentials:
    landing_page()
else:
    try:
        # OPTIMIZACIÓN: build_drive_service ahora está cacheada (@st.cache_resource).
        # El objeto de servicio se crea una sola vez por sesión, ahorrando tiempo.
        if 'drive_service' not in st.session_state or st.session_state.drive_service is None:
            st.session_state.drive_service = build_drive_service(credentials)
        
        if 'gemini_model' not in st.session_state:
            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
            
            # OPTIMIZACIÓN: Se añade una 'system_instruction' para reducir tokens.
            # Esto establece el rol del modelo una vez, evitando repetirlo en cada prompt.
            st.session_state.gemini_model = genai.GenerativeModel(
                'models/gemini-2.5-flash',
                system_instruction="Eres un asistente experto en la preparación de memorias técnicas para licitaciones. Tu objetivo es generar documentos estratégicos, precisos y profesionales en el idioma solicitado, siguiendo estrictamente las instrucciones y formatos requeridos."
            )

        model = st.session_state.gemini_model

    except Exception as e:
        st.error(f"Error en la configuración de servicios. Detalle: {e}")
        del st.session_state['credentials']
        st.button("Reintentar conexión", on_click=go_to_landing)
        st.stop()
        
    if st.session_state.page == 'landing':
        go_to_project_selection()
        st.rerun()

    # Barra lateral (sin cambios)
    if st.session_state.get('selected_project') and st.session_state.page != 'project_selection':
        with st.sidebar:
            st.header("Proyecto Activo")
            st.info(st.session_state.selected_project['name'])
            
            if st.session_state.get('selected_lot') and st.session_state.selected_lot != OPCION_ANALISIS_GENERAL:
                st.success(f"Lote activo: {st.session_state.selected_lot}")

            st.markdown("---")
            
            if 'project_language' not in st.session_state:
                st.session_state.project_language = 'Español'
            
            st.selectbox(
                "Idioma del Proyecto:",
                ('Español', 'Inglés', 'Catalán', 'Gallego', 'Francés', 'Euskera'),
                key='project_language'
            )
            st.markdown("---")
            
            if st.button("↩️ Volver a Selección de Proyecto", use_container_width=True):
                back_to_project_selection_and_cleanup()
                st.rerun()

    # Router (sin cambios en la lógica de enrutamiento)
    page = st.session_state.page
    
    if page == 'project_selection':
        project_selection_page(go_to_landing, go_to_phase1)
    elif page == 'phase_1_viability':
        phase_1_viability_page(model, go_to_project_selection, go_to_phase2)
    elif page == 'phase_2_structure':
        phase_2_structure_page(model, go_to_phase1, go_to_phase2_results, handle_full_regeneration, back_to_project_selection_and_cleanup)
    elif page == 'phase_2_results':
        phase_2_results_page(model, go_to_phase2, go_to_phase3, handle_full_regeneration)
    elif page == 'phase_3_guiones':
        phase_3_page(model, go_to_phase2_results, go_to_phase4)
    elif page == 'phase_4_prompts':
        phase_4_page(model, go_to_phase3, go_to_phase5)
    elif page == 'phase_5_redaccion':
        phase_5_page(model, go_to_phase4, go_to_phase6)
    elif page == 'phase_6_ensamblaje':
        phase_6_page(model, go_to_phase5, back_to_project_selection_and_cleanup)
    else:
        st.error(f"Página '{page}' no reconocida. Volviendo a la selección de proyecto.")
        go_to_project_selection()
        st.rerun()
