# app.py (VERSIÓN COMPLETA Y MODIFICADA)
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

from auth import get_credentials, build_drive_service
# Asegúrate de que los nombres de las funciones importadas coincidan con los de tu ui_pages.py
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
# [MODIFICADO] Se añade la importación del nuevo prompt
from prompts import PROMPT_PLIEGOS, PROMPT_DETECTAR_LOTES

# Se importa la función para convertir Excel.
from utils import limpiar_respuesta_json, convertir_excel_a_texto_csv

from drive_utils import find_or_create_folder, get_files_in_project, download_file_from_drive

# =============================================================================
#           CONFIGURACIÓN GLOBAL Y GESTIÓN DE ESTADO
# =============================================================================

st.set_page_config(layout="wide")

# --- Inicialización de Estado ---
if 'page' not in st.session_state: st.session_state.page = 'landing'
if 'credentials' not in st.session_state: st.session_state.credentials = None
if 'drive_service' not in st.session_state: st.session_state.drive_service = None
if 'selected_project' not in st.session_state: st.session_state.selected_project = None

# [NUEVO] Estados para la gestión de lotes
if 'detected_lotes' not in st.session_state: st.session_state.detected_lotes = None
if 'selected_lot' not in st.session_state: st.session_state.selected_lot = None

# Estados específicos del proyecto
if 'requisitos_extraidos' not in st.session_state: st.session_state.requisitos_extraidos = None
if 'generated_structure' not in st.session_state: st.session_state.generated_structure = None
if 'uploaded_pliegos' not in st.session_state: st.session_state.uploaded_pliegos = None
if 'generated_doc_buffer' not in st.session_state: st.session_state.generated_doc_buffer = None
if 'generated_doc_filename' not in st.session_state: st.session_state.generated_doc_filename = ""
if 'refined_doc_buffer' not in st.session_state: st.session_state.refined_doc_buffer = None
if 'refined_doc_filename' not in st.session_state: st.session_state.refined_doc_filename = ""


# --- Funciones de Navegación (NUEVO FLUJO) ---
def go_to_landing(): st.session_state.page = 'landing'
def go_to_project_selection(): st.session_state.page = 'project_selection'
def go_to_phase1(): st.session_state.page = 'phase_1_viability'
def go_to_phase2(): st.session_state.page = 'phase_2_structure'
def go_to_phase2_results(): st.session_state.page = 'phase_2_results'
def go_to_phase3(): st.session_state.page = 'phase_3_guiones'
def go_to_phase4(): st.session_state.page = 'phase_4_prompts'
def go_to_phase5(): st.session_state.page = 'phase_5_redaccion'
def go_to_phase6(): st.session_state.page = 'phase_6_ensamblaje'

# --- Función de Limpieza ---
def back_to_project_selection_and_cleanup():
    """Limpia el estado de la sesión relacionado con un proyecto específico."""
    # [MODIFICADO] Se añaden los nuevos estados de lotes a la limpieza
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

# [NUEVO] Función de contexto de lote y constantes asociadas
CONTEXTO_LOTE_TEMPLATE = "\n\n**INSTRUCCIÓN CRÍTICA DE ANÁLISIS:** Tu análisis debe centrarse única y exclusivamente en la información relacionada con el **'{lote_seleccionado}'**. Ignora por completo cualquier dato, requisito o criterio de valoración que pertenezca a otros lotes.\n\n"
OPCION_ANALISIS_GENERAL = "Análisis general (no centrarse en un lote)"

def get_lot_context():
    """Genera el texto de contexto para la IA si hay un lote seleccionado."""
    lote_seleccionado = st.session_state.get('selected_lot')
    if lote_seleccionado and lote_seleccionado != OPCION_ANALISIS_GENERAL:
        return CONTEXTO_LOTE_TEMPLATE.format(lote_seleccionado=lote_seleccionado)
    return ""

def handle_full_regeneration(model):
    """
    Función que genera un índice desde cero analizando los archivos de 'Pliegos'.
    Esta versión está corregida para manejar XLSX, DOCX y PDF correctamente.
    """
    if not st.session_state.get('drive_service') or not st.session_state.get('selected_project'):
        st.error("Error de sesión. No se puede iniciar la regeneración."); return False

    with st.spinner("Descargando archivos de 'Pliegos' y re-analizando para generar índice..."):
        response = None
        try:
            service = st.session_state.drive_service
            project_folder_id = st.session_state.selected_project['id']
            pliegos_folder_id = find_or_create_folder(service, "Pliegos", parent_id=project_folder_id)
            document_files = get_files_in_project(service, pliegos_folder_id)

            if not document_files:
                st.warning("No se encontraron archivos en la carpeta 'Pliegos' para analizar."); return False

            idioma_seleccionado = st.session_state.get('project_language', 'Español')
            
            # [MODIFICADO] Se añade el contexto del lote al formatear el prompt
            contexto_lote = get_lot_context()
            prompt_con_idioma = PROMPT_PLIEGOS.format(idioma=idioma_seleccionado, contexto_lote=contexto_lote)
            
            contenido_ia = [prompt_con_idioma]

            for file in document_files:
                file_content_bytes = download_file_from_drive(service, file['id'])
                nombre_archivo = file['name']
                
                if nombre_archivo.lower().endswith('.xlsx'):
                    st.write(f"⚙️ Procesando Excel para el índice: {nombre_archivo}...")
                    texto_csv = convertir_excel_a_texto_csv(file_content_bytes, nombre_archivo)
                    if texto_csv:
                        contenido_ia.append(texto_csv)
                
                else:
                    contenido_ia.append({"mime_type": file['mimeType'], "data": file_content_bytes.getvalue()})

            try:
                response = model.generate_content(contenido_ia, generation_config={"response_mime_type": "application/json"})
            except Exception as api_error:
                st.error(f"Error Crítico durante la llamada a la API de Gemini.")
                st.info("Esto puede ocurrir por contenido en los documentos que activa un filtro de seguridad o por un formato inválido.")
                st.write("Detalles del error de la librería:")
                st.code(f"Tipo de error: {type(api_error)}\nMensaje: {api_error}")
                return False

            if not response or not response.candidates:
                st.error("La IA no generó una respuesta. Esto puede deberse a filtros de seguridad o un problema temporal.")
                if response and hasattr(response, 'prompt_feedback'):
                    st.code(f"Razón del bloqueo: {response.prompt_feedback}")
                else:
                    st.code(f"La respuesta de la API estuvo vacía o fue inválida.")
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
            if response:
                st.info("Respuesta recibida de la IA que causó el error:")
                st.code(response.text)
            return False
        except Exception as e:
            st.error(f"Ocurrió un error inesperado durante la regeneración completa: {e}")
            if response:
                st.info("Respuesta recibida de la IA:")
                st.code(response.text)
            return False

# =============================================================================
#                        LÓGICA PRINCIPAL (ROUTER)
# =============================================================================

credentials = get_credentials()

if not credentials:
    landing_page()
else:
    try:
        if 'drive_service' not in st.session_state or st.session_state.drive_service is None:
            st.session_state.drive_service = build_drive_service(credentials)
        
        if 'gemini_model' not in st.session_state:
            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
            st.session_state.gemini_model = genai.GenerativeModel('models/gemini-1.5-flash') # Modelo actualizado

        model = st.session_state.gemini_model

    except Exception as e:
        st.error(f"Error en la configuración de servicios. Detalle: {e}")
        del st.session_state['credentials']
        st.button("Reintentar conexión", on_click=go_to_landing)
        st.stop()
        
    if st.session_state.page == 'landing':
        go_to_project_selection()
        st.rerun()

    # --- [MODIFICADO] BARRA LATERAL CON INFORMACIÓN DEL LOTE ---
    # Se muestra en todas las páginas una vez que se ha cargado un proyecto.
    if st.session_state.get('selected_project') and st.session_state.page != 'project_selection':
        with st.sidebar:
            st.header(f"Proyecto Activo")
            st.info(st.session_state.selected_project['name'])
            
            # [NUEVO] Mostrar el lote activo si existe y no es la opción general
            if st.session_state.get('selected_lot') and st.session_state.selected_lot != OPCION_ANALISIS_GENERAL:
                st.success(f"Lote activo: {st.session_state.selected_lot}")

            st.markdown("---")
            
            # Inicializa el idioma si no existe, para evitar errores
            if 'project_language' not in st.session_state:
                st.session_state.project_language = 'Español'
            
            # Selector de idioma persistente que guarda su estado
            st.selectbox(
                "Idioma del Proyecto:",
                ('Español', 'Inglés', 'Catalán', 'Gallego', 'Francés', 'Euskera'),
                key='project_language'
            )
            st.markdown("---")
            
            if st.button("↩️ Volver a Selección de Proyecto", use_container_width=True):
                back_to_project_selection_and_cleanup()
                st.rerun()
    # --- [FIN DEL CÓDIGO MODIFICADO] ---

    # Router: Llama a la función de la página actual según el estado.
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
