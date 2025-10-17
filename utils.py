# utils.py (VERSIÓN COMPLETA Y CORREGIDA)

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

# <-- ¡CORRECCIÓN AQUÍ! AÑADIMOS LA IMPORTACIÓN DE LAS FUNCIONES DE DRIVE
from drive_utils import find_or_create_folder, get_or_create_lot_folder_id

# =============================================================================
#           FUNCIONES DE PROCESAMIENTO DE TEXTO Y JSON
# =============================================================================

CARACTERES_POR_PAGINA_MIN = 3500
CARACTERES_POR_PAGINA_MAX = 3800


CONTEXTO_LOTE_TEMPLATE = """

**INSTRUCCIÓN CRÍTICA DE ANÁLIS:** Tu análisis debe centrarse única y exclusivamente en la información relacionada con el **'{lote_seleccionado}'**. Ignora por completo cualquier dato, requisito o criterio de valoración que pertenezca a otros lotes.

"""
OPCION_ANALISIS_GENERAL = "Análisis general (no centrarse en un lote)"

# En tu archivo utils.py, reemplaza la función get_lot_index_info completa por esta:

def get_lot_index_info(service, project_folder_id, selected_lot):
    """
    Calcula el ID de la carpeta y el nombre de archivo específico para el índice.
    Si selected_lot es OPCION_ANALISIS_GENERAL, 'SIN_LOTES', o None, usa la carpeta de la aplicación
    del proyecto raíz y el nombre de archivo 'ultimo_indice.json'.
    Si es un lote, usa la carpeta de la aplicación DENTRO del lote y un nombre único.
    """
    
    # =============================================================================
    #           [INICIO DE LA CORRECCIÓN]
    # =============================================================================
    # Se añade "or selected_lot is None" a la condición. Esto maneja el caso de error
    # y lo trata de forma segura como un análisis general, evitando que la app se detenga.
    is_general_analysis = (selected_lot == OPCION_ANALISIS_GENERAL or selected_lot is None)
    # =============================================================================
    #           [FIN DE LA CORRECCIÓN]
    # =============================================================================

    if is_general_analysis:
        # 1. Caso SIN LOTES (Comportamiento por defecto)
        # La carpeta de documentos de la app está a nivel de proyecto
        app_folder_id = find_or_create_folder(service, "Documentos aplicación", parent_id=project_folder_id)
        index_filename = "ultimo_indice.json"
        target_folder_id = app_folder_id
    else:
        # 2. Caso CON LOTES (Comportamiento por lote)
        # La carpeta del lote está a nivel de proyecto
        lot_folder_id = get_or_create_lot_folder_id(service, project_folder_id, lot_name=selected_lot)
        
        # La carpeta de documentos de la app está DENTRO de la carpeta del lote
        target_folder_id = find_or_create_folder(service, "Documentos aplicación", parent_id=lot_folder_id)
        
        # Generar el nombre de archivo
        match = re.search(r'Lote\s*(\d+|\w+)', selected_lot, re.IGNORECASE)
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
            return response # Si tiene éxito, devuelve la respuesta y sale de la función
        except google.api_core.exceptions.ResourceExhausted as e:
            st.warning(f"⚠️ Límite de la API alcanzado. Reintentando en {delay} segundos... ({i+1}/{reintentos})")
            time.sleep(delay)
        except Exception as e:
            st.error(f"Ocurrió un error inesperado al contactar la API: {e}")
            # Para otros errores, podría ser mejor no reintentar, así que salimos.
            return None 
    
    # Si el bucle termina sin éxito después de todos los reintentos
    st.error("No se pudo obtener una respuesta de la API después de varios intentos.")
    return None
    
def convertir_excel_a_texto_csv(archivo_excel_bytes, nombre_archivo):
    """
    Lee los bytes de un archivo Excel (.xlsx) y convierte todas sus hojas a una
    única cadena de texto en formato CSV.

    Args:
        archivo_excel_bytes (io.BytesIO): El contenido del archivo Excel en bytes.
        nombre_archivo (str): El nombre original del archivo para dar contexto.

    Returns:
        str: Una cadena de texto con el contenido de todas las hojas en formato CSV.
    """
    try:
        # Usamos pandas.ExcelFile para poder inspeccionar las hojas del archivo
        xls = pd.ExcelFile(archivo_excel_bytes)
        texto_final_csv = ""

        # Si hay más de una hoja, iteramos sobre cada una
        if len(xls.sheet_names) > 1:
            texto_final_csv += f"--- Inicio del contenido del archivo Excel '{nombre_archivo}' (múltiples hojas) ---\n\n"
            for nombre_hoja in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=nombre_hoja)
                # Añadimos un encabezado para que la IA sepa de qué hoja vienen los datos
                texto_final_csv += f"--- Contenido de la Hoja: '{nombre_hoja}' ---\n"
                # Convertimos el DataFrame a un string CSV, sin el índice de pandas
                texto_final_csv += df.to_csv(index=False)
                texto_final_csv += "\n\n"
            texto_final_csv += f"--- Fin del contenido del archivo Excel '{nombre_archivo}' ---\n"
        # Si solo hay una hoja, la procesamos directamente
        else:
            df = pd.read_excel(xls)
            texto_final_csv += f"--- Inicio del contenido del archivo Excel '{nombre_archivo}' ---\n"
            texto_final_csv += df.to_csv(index=False)
            texto_final_csv += f"\n--- Fin del contenido del archivo Excel '{nombre_archivo}' ---\n"
            
        return texto_final_csv

    except Exception as e:
        # Si algo falla, devolvemos un mensaje de error claro
        st.error(f"No se pudo procesar el archivo Excel '{nombre_archivo}': {e}")
        return ""
        
def limpiar_respuesta_json(texto_sucio):
    """
    Limpia de forma muy agresiva la respuesta de texto de la IA para extraer un objeto JSON válido.
    Primero, busca un bloque de código JSON (```json ... ```). Si no lo encuentra,
    busca el primer '{' y el último '}' en la cadena.
    """
    if not isinstance(texto_sucio, str):
        return ""

    try:
        # [NUEVO] Búsqueda mejorada que prioriza los bloques de código Markdown
        # Esto es mucho más fiable para las respuestas de la API de Gemini
        match = re.search(r'```(json)?\s*(\{.*?\})\s*```', texto_sucio, re.DOTALL)
        if match:
            # Si encuentra un bloque ```json {...}```, extrae el contenido del grupo 2, que es el JSON
            return match.group(2)
        else:
            # [LÓGICA ANTERIOR COMO RESPALDO] Si no hay bloque de código, usamos el método original
            start_index = texto_sucio.find('{')
            end_index = texto_sucio.rfind('}')
            if start_index != -1 and end_index != -1 and end_index > start_index:
                return texto_sucio[start_index:end_index + 1]
            else:
                return "" # No se encontró nada que parezca un JSON
    except Exception:
        # En caso de cualquier otro error, devuelve una cadena vacía
        return ""

def limpiar_respuesta_final(texto_ia):
    """
    Limpia de forma agresiva la respuesta de la IA para la redacción final,
    eliminando meta-texto, explicaciones, y bloques de código.
    """
    if not isinstance(texto_ia, str):
        return ""
    # Eliminar frases sobre la creación de diagramas o código
    texto_limpio = re.sub(r'Este código crea.*?visualizar el diagrama\.', '', texto_ia, flags=re.DOTALL | re.IGNORECASE)
    texto_limpio = re.sub(r'El código HTML proporcionado genera.*?aún más:', '', texto_limpio, flags=re.DOTALL | re.IGNORECASE)
    # Eliminar bloques de código JSON o de otro tipo
    texto_limpio = re.sub(r'```(json|html|mermaid|text)?\s*.*?```', '', texto_limpio, flags=re.DOTALL)
    # Eliminar frases introductorias comunes
    frases_a_eliminar = [
        r'^\s*Aquí tienes el contenido.*?:',
        r'^\s*Claro, aquí está la redacción para.*?:',
        r'^\s*A continuación se presenta el contenido detallado:',
        r'^\s*##\s*.*?$' # Elimina cualquier título Markdown que la IA pueda repetir
    ]
    for patron in frases_a_eliminar:
        texto_limpio = re.sub(patron, '', texto_limpio, flags=re.IGNORECASE | re.MULTILINE)

    return texto_limpio.strip()

def corregir_numeracion_markdown(texto_markdown):
    """
    Recorre un texto en Markdown y corrige las listas numeradas para que
    sean consecutivas (1., 2., 3., etc.), independientemente de los números originales.
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
    Ej: 'item 10' viene después de 'item 2'.
    """
    if not isinstance(s, str):
        return [s]
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def agregar_markdown_a_word(documento, texto_markdown):
    """
    Convierte una cadena de texto en formato Markdown a un documento de Word,
    manejando encabezados (#), listas (*, -), listas numeradas (1.) y negritas (**).
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
    Añade un índice (Tabla de Contenidos) al principio de un documento de Word
    basado en la estructura de la memoria técnica.
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
    Muestra una estructura de índice en Streamlit con apartados desplegables
    y las indicaciones detalladas para cada subapartado.
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
                    st.write("") # Un pequeño espacio para separar

# =============================================================================
#           FUNCIONES DE CONVERSIÓN HTML A IMAGEN
# =============================================================================

def wrap_html_fragment(html_fragment):
    """
    Envuelve un fragmento de HTML en una estructura completa con estilos CSS
    para una correcta renderización a imagen.
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
        # Busca wkhtmltoimage en el PATH del sistema (funciona en Streamlit Cloud)
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
