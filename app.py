import streamlit as st
import easyocr
from PIL import Image
import os
import uuid
import gc
import threading  
import time  
import io
import re
from difflib import SequenceMatcher
from supabase import create_client, Client

# Configuración de página móvil optimizada
st.set_page_config(page_title="Historial Carreras", layout="centered")
st.title("🏁 Buscador de Carreras Pro")

# --- CONEXIÓN SEGURA Y OFICIAL A SUPABASE ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
nombre_bucket = "imagenes-carreras"

@st.cache_resource
def inicializar_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    supabase: Client = inicializar_supabase()
except Exception as e:
    st.error(f"Error al inicializar las credenciales de Supabase: {e}")

# Inicialización optimizada del motor OCR
@st.cache_resource
def cargar_ocr():
    return easyocr.Reader(['es', 'en'], gpu=False)

reader_compartido = cargar_ocr()

# Inicializar llaves de control en segundo plano y progreso
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = str(uuid.uuid4())
if "tareas_activas" not in st.session_state:
    st.session_state["tareas_activas"] = []

# Variables globales planas que NO pertenecen a session_state para evitar bloqueos de hilos
if "total_lote" not in st.session_state:
    st.session_state["total_lote"] = 0
if "procesadas_lote" not in st.session_state:
    st.session_state["procesadas_lote"] = 0

# --- MENÚ EN LA BARRA LATERAL ---
st.sidebar.header("⚙️ Configuración")
tipo_animal = st.sidebar.radio("Selecciona el tipo de carrera:", ["🐕 Galgos", "🐎 Caballos"])
opcion = st.sidebar.radio("Acción:", ["🔍 Buscar Carrera", "📋 Ver Historial Completo", "📥 Cargar Historial"])

categoria_actual = "galgos" if tipo_animal == "🐕 Galgos" else "caballos"

# --- FUNCIONES DE BASE DE DATOS ---
def cargar_historial_desde_base_datos(categoria):
    try:
        respuesta = supabase.table("historial_carreras").select("*").eq("categoria", categoria).order("id", descending=True).execute()
        return respuesta.data
    except Exception as e:
        return []

historial_actual = cargar_historial_desde_base_datos(categoria_actual)

def optimizar_imagen_rapido(raw_bytes, ruta_destino):
    img = Image.open(io.BytesIO(raw_bytes))
    if img.width > 600: 
        proporcion = 600 / float(img.width)
        alto = int((float(img.height) * float(proporcion)))
        img = img.resize((600, alto), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(ruta_destino, "JPEG", quality=60, optimize=True)

def procesar_y_vincular_filas(resultados_ocr):
    filas_agrupadas = {}
    tolerancia_y = 12  
    
    for (bbox, texto, prob) in resultados_ocr:
        texto_limpio = texto.strip().lower()
        if len(texto_limpio) < 1:
            continue
            
        if any(c.isdigit() for c in texto_limpio) and ('.' in texto_limpio or ',' in texto_limpio):
            texto_limpio = texto_limpio.replace('o', '0').replace('i', '1').replace('s', '5').replace(',', '.')

        centro_y = (bbox + bbox) / 2
        
        fila_encontrada = False
        for y_existente in filas_agrupadas.keys():
            if abs(centro_y - y_existente) < tolerancia_y:
                filas_agrupadas[y_existente].append((bbox, texto_limpio))
                fila_encontrada = True
                break
        
        if not fila_encontrada:
            filas_agrupadas[centro_y] = [(bbox, texto_limpio)]
            
    huellas_corredores = []
    
    for y in sorted(filas_agrupadas.keys()):
        elementos_fila = sorted(filas_agrupadas[y], key=lambda x: x)
        textos_fila = [item for item in elementos_fila]
        
        cuota = None
        palabras_nombre = []
        
        for t in textos_fila:
            if t in ["1", "2", "3", "4", "5", "6"]:
                continue
            if bool(re.match(r'^\d+\.\d+$', t)) and cuota is None:
                cuota = t
                continue
            if len(t) > 2 and not any(c.isdigit() for c in t):
                if t in ["ganador", "segundo", "tercero", "juego", "resultados", "finalizado", "carrera", "caballos", "galgos", "ultimos", "valoracion", "gana", "segu", "terce", "estado", "pista"]:
                    continue
                palabras_nombre.append(t)
        
        if palabras_nombre:
            nombre_completo = " ".join(palabras_nombre)
            cuota_final = cuota if cuota else "0.0"
            huellas_corredores.append(f"{nombre_completo}_{cuota_final}")
            
    return list(set(huellas_corredores))

def calcular_similitud_texto(str1, str2):
    return SequenceMatcher(None, str1, str2).ratio()

# --- CONTENEDOR SEGURO DE ESTADO PARA EVITAR CONFLICTOS CON STREAMLIT ---
class RastreadorProgreso:
    def __init__(self):
        self.procesadas = 0

progreso_hilo = RastreadorProgreso()

# --- FUNCIÓN EN SEGUNDO PLANO (CORREGIDA SIN INTERFERENCIAS) ---
def tarea_subida_segundo_plano(lista_archivos, categoria, url_sb, key_sb, bucket, tracker):
    client_local = create_client(url_sb, key_sb)
    reader_local = easyocr.Reader(['es', 'en'], gpu=False)
    
    for idx, archivo in enumerate(lista_archivos):
        id_unico = uuid.uuid4().hex[:8]
        nombre_limpio = f"{id_unico}_{archivo['name'].replace(' ', '_')}"
        ruta_temp = f"temp_{nombre_limpio}"
        
        try:
            optimizar_imagen_rapido(archivo["data"], ruta_temp)
            resultados_raw = reader_local.readtext(ruta_temp, detail=1)
            datos_huella = procesar_y_vincular_filas(resultados_raw)
            
            ruta_almacenamiento = f"{categoria}_{nombre_limpio}"
            with open(ruta_temp, "rb") as f:
                client_local.storage.from_(bucket).upload(
                    path=ruta_almacenamiento,
                    file=f,
                    file_options={"content-type": "image/jpeg", "x-upsert": "true"}
                )
            
            url_publica = f"{url_sb}/storage/v1/object/public/{bucket}/{ruta_almacenamiento}"
            datos_db = {
                "categoria": categoria,
                "nombre_archivo": nombre_limpio,
                "url_imagen": url_publica,
                "palabras_clave": datos_huella
            }
            client_local.table("historial_carreras").insert(datos_db).execute()
        except Exception as e:
            pass
        finally:
            if os.path.exists(ruta_temp):
                os.remove(ruta_temp)
            # Actualizar el objeto tracker externo seguro
            tracker.procesadas = idx + 1
                
    gc.collect()

# --- SECCIÓN: CARGA MASIVA ---
if opcion == "📥 Cargar Historial":
    st.header(f"📥 Guardar Resultados Finales")
    
    if st.session_state["tareas_activas"]:
        # Filtrar hilos vivos
        st.session_state["tareas_activas"] = [t for t in st.session_state["tareas_activas"] if t.is_alive()]
        
        if st.session_state["tareas_activas"]:
            total = st.session_state["total_lote"]
            procesadas = progreso_hilo.procesadas
            
            # Sincronizar el progreso del hilo con el estado visual
            st.session_state["procesadas_lote"] =流量 = procesadas
            porcentaje = int((procesadas / total) * 100) if total > 0 else 0
            
            with st.container(border=True):
                st.warning(f"⚙️ **Procesando imágenes de fondo:** {procesadas} de {total} completadas.")
                st.progress(porcentaje / 100.0)
                st.caption(f"📈 **Progreso actual:** {porcentaje}% indexado en Supabase.")
                if st.button("🔄 Actualizar estado de subida"):
                    st.rerun()
        else:
            st.success("✅ **¡Todas las subidas han finalizado! Los datos ya están guardados en tu historial.**")
            time.sleep(1.0)
            st.rerun()
            
    archivos_historial = st.file_uploader("Selecciona fotos de resultados finales:", accept_multiple_files=True, type=["jpg", "png", "jpeg"], key=st.session_state["uploader_key"])
    
    if archivos_historial and st.button("Enviar y Procesar en Segundo Plano", use_container_width=True):
        archivos_clonados = [{"name": a.name, "data": a.read()} for a in archivos_historial]
        
        st.session_state["total_lote"] = len(archivos_clonados)
        progreso_hilo.procesadas = 0
        st.session_state["procesadas_lote"] = 0
        
        # Pasamos el rastreador de clase pura en lugar del diccionario mutante de Streamlit
        hilo = threading.Thread(
            target=tarea_subida_segundo_plano, 
            args=(archivos_clonados, categoria_actual, SUPABASE_URL, SUPABASE_KEY, nombre_bucket, progreso_hilo)
        )
        hilo.start()
        
        st.session_state["tareas_activas"].append(hilo)
        st.session_state["uploader_key"] = str(uuid.uuid4())
        st.success("✅ ¡Imágenes enviadas al segundo plano con éxito!")
        time.sleep(1.2)
        st.rerun()

# --- SECCIÓN: VER HISTORIAL ---
elif opcion == "📋 Ver Historial Completo":
    st.header(f"📋 Historial ({tipo_animal})")
    if not historial_actual:
        st.info(f"Aún no hay carreras registradas.")
    else:
        for item in historial_actual:
            with st.container(border=True):
                st.image(item["url_imagen"], use_container_width=True)
                st.caption(f"🔑 **Huellas de Corredores Guardadas:**")
                st.write(", ".join([t.replace('_', ' (Cuota: ') + ')' for t in item['palabras_clave']]).title())

# --- SECCIÓN: BUSCAR CARRERA ---
elif opcion == "🔍 Buscar Carrera":
    st.header(f"🔍 Diagnóstico de Similitud Avanzado ({tipo_animal})")
    
    metodo_busqueda = st.sidebar.radio(
        "Método de búsqueda:", 
        ["📸 Foto en Vivo (Parrilla completa)", "⌨️ Buscar un Corredor específico"]
    )
    
    huellas_actuales = []

