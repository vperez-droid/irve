import streamlit as st
import re
import os
import io
import json
import docx
import imgkit
from pypdf import PdfReader
import pandas as pd
import time
import google.api_core.exceptions
from PIL import Image

# <-- ¡CORRECCIÓN APLICADA AQUÍ! AÑADIMOS LA IMPORTACIÓN DE 'clean_folder_name'
from drive_utils import find_or_create_folder, get_or_create_lot_folder_id, clean_folder_name

# =============================================================================
#           FUNCIONES DE PROCESAMIENTO DE TEXTO Y JSON
# =============================================================================

CARACTERES_POR_PAGINA_MIN = 3500
CARACTERES_POR_PAGINA_MAX = 3800


CONTEXTO_LOTE_TEMPLATE = """

**INSTRUCCIÓN CRÍTICA DE ANÁLIS:** Tu análisis debe centrarse única y exclusivamente en la información relacionada con el **'{lote_seleccionado}'**. Ignora por completo cualquier dato, requisito o criterio de valoración que pertenezca a otros lotes.

"""
OPCION_ANALISIS_GENERAL = "Análisis general (no centrarse en un lote)"

def get_lot_index_info(service, project_folder_id, selected_lot):
    """
    Calcula el ID de la carpeta y el nombre de archivo específico para el índice.
    Si selected_lot es OPCION_ANALISIS_GENERAL, 'SIN_LOTES', o None, usa la carpeta de la aplicación
    del proyecto raíz y el nombre de archivo 'ultimo_indice.json'.
    Si es un lote, usa la carpeta de la aplicación DENTRO del lote y un nombre único.
    """
    is_general_analysis = (selected_lot == OPCION_ANALISIS_GENERAL or selected_lot is None)

    if is_general_analysis:
        # 1. Caso SIN LOTES (Comportamiento por defecto)
        app_folder_id = find_or_create_folder(service, "Documentos aplicación", parent_id=project_folder_id)
        index_filename = "ultimo_indice.json"
        target_folder_id = app_folder_id
    else:
        # 2. Caso CON LOTES (Comportamiento por lote)
        lot_folder_id = get_or_create_lot_folder_id(service, project_folder_id, lot_name=selected_lot)
        
        target_folder_id = find_or_create_folder(service, "Documentos aplicación", parent_id=lot_folder_id)
        
        match = re.search(r'Lote\s*(\d+|\w+)', selected_lot, re.IGNORECASE)
        # Esta es la línea que antes fallaba. Ahora 'clean_folder_name' es reconocida.
        lot_suffix = match.group(1).replace(' ', '_') if match else clean_folder_name(selected_lot).split('_')[0]
        
        index_filename = f"ultimo_indice_lote{lot_suffix}.json"

    return target_folder_id, index_filename

def get_lot_context():
    """Genera el texto de contexto para la IA si hay un lote seleccionado."""
    lote_seleccionado = st.session_state.get('selected_lot')
    if lote_seleccionado and lote_seleccionado != OPCION_ANALISIS_GENERAL:
        return CONTEXTO_LOTE_TEMPLATE.format(lote_seleccionado=lote_seleccionado)
    return ""
    
def enviar_mensaje_con_reintentos(chat, prompt_a_enviar, reintentos=5, delay=60):
    """
    Envía un mensaje a un chat de Gemini, con una lógica de reintentos para errores comunes.
    """
    for i in range(reintentos):
        try:
            response = chat.send_message(prompt_a_enviar)
            return response
        except google.api_core.exceptions.ResourceExhausted as e:
            st.warning(f"⚠️ Límite de la API alcanzado. Reintentando en {delay} segundos... ({i+1}/{reintentos})")
            time.sleep(delay)
        except Exception as e:
            st.error(f"Ocurrió un error inesperado al contactar la API: {e}")
            return None 
    
    st.error("No se pudo obtener una respuesta de la API después de varios intentos.")
    return None
    
def convertir_excel_a_texto_csv(archivo_excel_bytes, nombre_archivo):
    """
    Lee los bytes de un archivo Excel (.xlsx) y convierte todas sus hojas a una
    única cadena de texto en formato CSV.
    """
    try:
        xls = pd.ExcelFile(archivo_excel_bytes)
        texto_final_csv = ""

        if len(xls.sheet_names) > 1:
            texto_final_csv += f"--- Inicio del contenido del archivo Excel '{nombre_archivo}' (múltiples hojas) ---\n\n"
            for nombre_hoja in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=nombre_hoja)
                texto_final_csv += f"--- Contenido de la Hoja: '{nombre_hoja}' ---\n"
                texto_final_csv += df.to_csv(index=False)
                texto_final_csv += "\n\n"
            texto_final_csv += f"--- Fin del contenido del archivo Excel '{nombre_archivo}' ---\n"
        else:
            df = pd.read_excel(xls)
            texto_final_csv += f"--- Inicio del contenido del archivo Excel '{nombre_archivo}' ---\n"
            texto_final_csv += df.to_csv(index=False)
            texto_final_csv += f"\n--- Fin del contenido del archivo Excel '{nombre_archivo}' ---\n"
            
        return texto_final_csv

    except Exception as e:
        st.error(f"No se pudo procesar el archivo Excel '{nombre_archivo}': {e}")
        return ""
        
def limpiar_respuesta_json(texto_sucio):
    """
    Limpia de forma muy agresiva la respuesta de texto de la IA para extraer un objeto JSON válido.
    """
    if not isinstance(texto_sucio, str):
        return ""

    try:
        match = re.search(r'```(json)?\s*(\{.*?\})\s*```', texto_sucio, re.DOTALL)
        if match:
            return match.group(2)
        else:
            start_index = texto_sucio.find('{')
            end_index = texto_sucio.rfind('}')
            if start_index != -1 and end_index != -1 and end_index > start_index:
                return texto_sucio[start_index:end_index + 1]
            else:
                return ""
    except Exception:
        return ""

def limpiar_respuesta_final(texto_ia):
    """
    Limpia de forma agresiva la respuesta de la IA para la redacción final.
    """
    if not isinstance(texto_ia, str):
        return ""
    texto_limpio = re.sub(r'Este código crea.*?visualizar el diagrama\.', '', texto_ia, flags=re.DOTALL | re.IGNORECASE)
    texto_limpio = re.sub(r'El código HTML proporcionado genera.*?aún más:', '', texto_limpio, flags=re.DOTALL | re.IGNORECASE)
    texto_limpio = re.sub(r'```(json|html|mermaid|text)?\s*.*?```', '', texto_limpio, flags=re.DOTALL)
    frases_a_eliminar = [
        r'^\s*Aquí tienes el contenido.*?:',
        r'^\s*Claro, aquí está la redacción para.*?:',
        r'^\s*A continuación se presenta el contenido detallado:',
        r'^\s*##\s*.*?$'
    ]
    for patron in frases_a_eliminar:
        texto_limpio = re.sub(patron, '', texto_limpio, flags=re.IGNORECASE | re.MULTILINE)

    return texto_limpio.strip()

def corregir_numeracion_markdown(texto_markdown):
    """
    Recorre un texto en Markdown y corrige las listas numeradas para que sean consecutivas.
    """
    lineas_corregidas = []
    contador_lista = 0
    en_lista_numerada = False
    for linea in texto_markdown.split('\n'):
        match = re.match(r'^\s*\d+\.\s+', linea)
        if match:
            if not en_lista_numerada:
                en_lista_numerada = True
                contador_lista = 1
            else:
                contador_lista += 1
            texto_del_item = linea[match.end():]
            lineas_corregidas.append(f"{contador_lista}. {texto_del_item}")
        else:
            en_lista_numerada = False
            lineas_corregidas.append(linea)
    return '\n'.join(lineas_corregidas)


# =============================================================================
#           FUNCIONES DE MANIPULACIÓN DE DOCUMENTOS (WORD, HTML)
# =============================================================================

def natural_sort_key(s):
    """
    Crea una clave para el ordenamiento 'natural' de cadenas.
    """
    if not isinstance(s, str):
        return [s]
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def agregar_markdown_a_word(documento, texto_markdown):
    """
    Convierte una cadena de texto en formato Markdown a un documento de Word.
    """
    patron_encabezado = re.compile(r'^(#+)\s+(.*)')
    patron_lista_numerada = re.compile(r'^\s*\d+\.\s+')
    patron_lista_viñeta = re.compile(r'^\s*[\*\-]\s+')
    
    def procesar_linea_con_negritas(parrafo, texto):
        partes = re.split(r'(\*\*.*?\*\*)', texto)
        for parte in partes:
            if parte.startswith('**') and parte.endswith('**'):
                parrafo.add_run(parte[2:-2]).bold = True
            elif parte:
                parrafo.add_run(parte)

    for linea in texto_markdown.split('\n'):
        linea_limpia = linea.strip()
        if not linea_limpia: continue
        
        match_encabezado = patron_encabezado.match(linea_limpia)
        if match_encabezado:
            nivel = min(len(match_encabezado.group(1)), 4)
            documento.add_heading(match_encabezado.group(2).strip(), level=nivel)
            continue

        if patron_lista_numerada.match(linea_limpia):
            p = documento.add_paragraph(style='List Number')
            procesar_linea_con_negritas(p, patron_lista_numerada.sub('', linea_limpia))
        elif patron_lista_viñeta.match(linea_limpia):
            p = documento.add_paragraph(style='List Bullet')
            procesar_linea_con_negritas(p, patron_lista_viñeta.sub('', linea_limpia))
        else:
            p = documento.add_paragraph()
            procesar_linea_con_negritas(p, linea_limpia)

def generar_indice_word(documento, estructura_memoria):
    """
    Añade un índice (Tabla de Contenidos) al principio de un documento de Word.
    """
    documento.add_heading("Índice", level=1)
    if not estructura_memoria:
        documento.add_paragraph("No se encontró una estructura para generar el índice.")
        return
    for seccion in estructura_memoria:
        apartado_titulo = seccion.get("apartado", "Apartado sin título")
        subapartados = seccion.get("subapartados", [])
        p = documento.add_paragraph()
        p.add_run(apartado_titulo).bold = True
        if subapartados:
            for sub in subapartados:
                documento.add_paragraph(f"    {sub}")
    st.toast("Índice generado en el documento.")

# =============================================================================
#           FUNCIONES DE INTERFAZ DE USUARIO (UI)
# =============================================================================

def mostrar_indice_desplegable(estructura, matices=None):
    """
    Muestra una estructura de índice en Streamlit con apartados desplegables.
    """
    if not estructura:
        st.warning("La estructura de la memoria está vacía.")
        return

    if not matices:
        matices = []
    matices_dict = {item.get('subapartado'): item.get('indicaciones', 'No se encontraron indicaciones.') for item in matices}

    for seccion in estructura:
        apartado_principal = seccion.get('apartado', 'Sin Título')
        with st.expander(f"**{apartado_principal}**"):
            subapartados = seccion.get('subapartados', [])
            if not subapartados:
                st.write("No hay subapartados.")
            else:
                for subapartado in subapartados:
                    st.markdown(f" L &nbsp; **{subapartado}**")
                    indicaciones = matices_dict.get(subapartado)
                    if indicaciones:
                        with st.container(border=True):
                            st.info(indicaciones)
                    st.write("")

# =============================================================================
#           FUNCIONES DE CONVERSIÓN HTML A IMAGEN
# =============================================================================

def wrap_html_fragment(html_fragment):
    """
    Envuelve un fragmento de HTML en una estructura completa con estilos CSS.
    """
    if html_fragment.strip().startswith('<!DOCTYPE html>'):
        return html_fragment
    css_styles = """
        @import url('https://fonts.googleapis.com/css2?family=Urbanist:wght@400;600;700&display=swap');
        body { font-family: 'Urbanist', sans-serif; background-color: #f0f2f5; display: flex; justify-content: center; align-items: center; padding: 20px; width: 800px; box-sizing: border-box; }
        .card { background-color: white; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); padding: 25px; width: 100%; max-width: 750px; border-top: 5px solid #0046C6; }
        h2 { color: #0046C6; text-align: center; margin-top: 0; font-size: 24px; font-weight: 700; }
        ul { list-style-type: none; padding: 0; }
        li { display: flex; align-items: center; margin-bottom: 15px; font-size: 16px; color: #333; }
        li::before { content: '✔'; color: #32CFAA; font-size: 20px; font-weight: bold; margin-right: 15px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 15px; }
        th, td { padding: 12px 15px; border: 1px solid #ddd; text-align: left; }
        th { background-color: #f5f5f5; font-weight: 600; color: #333; }
        tr:nth-child(even) { background-color: #f9f9f9; }
    """
    return f"""
    <!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Visual Element</title><style>{css_styles}</style></head>
    <body>{html_fragment}</body></html>
    """

def html_a_imagen(html_string, output_filename="temp_image.png"):
    """
    Convierte una cadena de HTML en una imagen PNG usando wkhtmltoimage.
    """
    try:
        path_wkhtmltoimage = os.popen('which wkhtmltoimage').read().strip()
        if not path_wkhtmltoimage:
            st.error("❌ 'wkhtmltoimage' no encontrado. Asegúrate de que 'wkhtmltopdf' está en packages.txt.")
            return None
        config = imgkit.config(wkhtmltoimage=path_wkhtmltoimage)
        options = {'format': 'png', 'encoding': "UTF-8", 'width': '800', 'quiet': ''}
        imgkit.from_string(html_string, output_filename, config=config, options=options)
        return output_filename if os.path.exists(output_filename) else None
    except Exception as e:
        st.error(f"Error al convertir HTML a imagen: {e}")
        return None

# -----------------------------------------------------------------------------
#         NUEVA ARQUITECTURA DE ANÁLISIS MULTIMODAL CON CACHÉ
# -----------------------------------------------------------------------------

def _analizar_docx_core(file_bytes_io, nombre_archivo):
    """
    (FUNCIÓN INTERNA - SIN UI) - VERSIÓN CON MANEJO DE ERRORES DETALLADO
    """
    try:
        doc = docx.Document(file_bytes_io)
        prompt_parts = [
            (
                "Eres un analista experto de documentos de licitación. A continuación, te proporciono el contenido completo de un documento, "
                "desglosado en texto e imágenes en el orden en que aparecen. Tu tarea es analizar todo el contenido de forma integral y "
                "generar un único resumen de texto enriquecido que capture toda la información clave. Describe explícitamente el contenido de las imágenes "
                "(diagramas, esquemas, fotos) y explica cómo se relacionan con el texto circundante. El resultado debe ser un texto coherente "
                "que pueda ser utilizado por otro modelo de IA para entender completamente el documento original sin necesidad de verlo.\n\n"
                "--- INICIO DEL CONTENIDO DEL DOCUMENTO ---\n"
            )
        ]
        texto_completo = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        prompt_parts.append(texto_completo)
        prompt_parts.append("\n--- FIN DEL TEXTO / INICIO DE LAS IMÁGENES ---")

        image_count = 0
        skipped_images = 0
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    image_part = rel.target_part
                    image_bytes = image_part.blob
                    img = Image.open(io.BytesIO(image_bytes))
                    img.thumbnail((1024, 1024))
                    prompt_parts.append(img)
                    image_count += 1
                except Exception as e:
                    skipped_images += 1
                    print(f"ADVERTENCIA: Se omitió una imagen no soportada en '{nombre_archivo}'. Error: {e}")
        
        print(f"Análisis CORE: Se procesaron {image_count} imágenes y se omitieron {skipped_images} en '{nombre_archivo}'.")

        if not texto_completo and image_count == 0:
            return ""

        model = st.session_state.gemini_model
        response = model.generate_content(prompt_parts)

        if not response.candidates:
            block_reason = "No especificado"
            if hasattr(response, 'prompt_feedback') and hasattr(response.prompt_feedback, 'block_reason'):
                block_reason = response.prompt_feedback.block_reason.name
            return f"Error: La solicitud fue bloqueada por los filtros de seguridad de la API. Razón: {block_reason}"

        return f"--- ANÁLISIS MULTIMODAL DE '{nombre_archivo}' ---\n{response.text}"

    except Exception as e:
        print(f"ERROR en el análisis CORE para '{nombre_archivo}': {e}")
        return f"Error al procesar el archivo DOCX: {str(e)}"

@st.cache_data(show_spinner=False)
def get_cached_multimodal_analysis(_file_content_bytes, nombre_archivo):
    """
    (FUNCIÓN CACHEABLE)
    Esta función envuelve la lógica de análisis principal. Streamlit almacenará en caché
    el resultado. Si se llama de nuevo con los mismos bytes de archivo, devolverá
    el resultado guardado instantáneamente sin volver a ejecutar el análisis.
    El guion bajo en '_file_content_bytes' es una convención para indicar que es el
    argumento principal para el hashing de la caché.
    """
    print(f"CACHE MISS: Ejecutando análisis por primera vez para '{nombre_archivo}'.")
    file_bytes_io = io.BytesIO(_file_content_bytes)
    return _analizar_docx_core(file_bytes_io, nombre_archivo)


def analizar_docx_multimodal_con_gemini(file_bytes_io, nombre_archivo):
    """
    (FUNCIÓN PRINCIPAL - CON UI)
    Esta es la función que llamarás desde tu aplicación. Se encarga de mostrar
    mensajes al usuario y de llamar a la función cacheable para obtener el análisis.
    """
    with st.spinner(f"Analizando '{nombre_archivo}' (texto e imágenes)..."):
        st.write(f"Procesando archivo: {nombre_archivo}")
        
        # Pasamos los bytes crudos a la función cacheada
        file_content_bytes = file_bytes_io.getvalue()
        analysis_result = get_cached_multimodal_analysis(file_content_bytes, nombre_archivo)
        
        if "Error" in analysis_result:
            st.error(f"No se pudo analizar '{nombre_archivo}'.")
            return None
        
        st.success(f"Análisis de '{nombre_archivo}' obtenido (de caché o nuevo).")
        return analysis_result
