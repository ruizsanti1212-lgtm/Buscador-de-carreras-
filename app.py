import streamlit as st
import easyocr
from PIL import Image
import os
import uuid
import gc
import threading  # LIBRERÍA CLAVE: Para ejecutar la subida en segundo plano
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

# Inicializar llaves de control en segundo plano
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = str(uuid.uuid4())
if "tareas_activas" not in st.session_state:
    st.session_state["tareas_activas"] = []

# --- MENÚ EN LA BARRA LATERAL ---
st.sidebar.header("⚙️ Configuración")
tipo_animal = st.sidebar.radio("Selecciona el tipo de carrera:", ["🐕 Galgos", "🐎 Caballos"])
opcion = st.sidebar.radio("Acción:", ["🔍 Buscar Carrera", "📋 Ver Historial Completo", "📥 Cargar Historial"])

categoria_actual = "galgos" if tipo_animal == "🐕 Galgos" else "caballos"

# --- FUNCIONES DE BASE DE DATOS ---
def guardar_en_base_datos(categoria, nombre_archivo, url_imagen, palabras_clave):
    try:
        datos = {
            "categoria": categoria,
            "nombre_archivo": nombre_archivo,
            "url_imagen": url_imagen,
            "palabras_clave": palabras_clave
        }
        supabase.table("historial_carreras").insert(datos).execute()
        return True
    except:
        return False

def cargar_historial_desde_base_datos(categoria):
    try:
        respuesta = supabase.table("historial_carreras").select("*").eq("categoria", categoria).execute()
        return respuesta.data
    except Exception as e:
        return []

historial_actual = cargar_historial_desde_base_datos(categoria_actual)

def optimizar_imagen_rapido(imagen_bytes, ruta_destino):
    """Procesa la imagen directamente desde la memoria RAM."""
    img = Image.open(imagen_bytes)
    if img.width > 600: 
        proporcion = 600 / float(img.width)
        alto = int((float(img.height) * float(proporcion)))
        img = img.resize((600, alto), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(ruta_destino, "JPEG", quality=60, optimize=True)

def limpiar_y_extraer_datos_pantalla(textos_ocr):
    datos_utiles = []
    palabras_basura = {
        "ganador", "segundo", "tercero", "gemela", "trio", "rev", "reversible", 
        "juego", "resultados", "finalizado", "carrera", "de", "caballos", "galgos",
        "colores", "calidos"
    }
    for t in textos_ocr:
        texto = t.strip().lower()
        if len(texto) < 2 or texto in palabras_basura or texto.endswith("s."):
            continue
        if any(char.isdigit() for char in texto):
            texto = texto.replace('o', '0').replace('i', '1')
        datos_utiles.append(texto)
    return list(set(datos_utiles))

def calcular_similitud_texto(str1, str2):
    return SequenceMatcher(None, str1, str2).ratio()

# --- FUNCIÓN TRABAJADORA EN SEGUNDO PLANO (BACKGROUND THREAD) ---
def tarea_subida_segundo_plano(lista_archivos, categoria, url_sb, key_sb, bucket):
    """Ejecuta de forma invisible el OCR, compresión y subida a Supabase sin tocar la pantalla."""
    client_local = create_client(url_sb, key_sb)
    reader_local = easyocr.Reader(['es', 'en'], gpu=False)
    
    for archivo in lista_archivos:
        id_unico = uuid.uuid4().hex[:8]
        nombre_limpio = f"{id_unico}_{archivo['name'].replace(' ', '_')}"
        ruta_temp = f"temp_{nombre_limpio}"
        
        try:
            # Optimizar desde el volcado de bytes guardado
            optimizar_imagen_rapido(archivo["bytes"], ruta_temp)
            
            # Ejecutar el OCR pesado de forma oculta
            textos = reader_local.readtext(ruta_temp, detail=0)
            datos_limpios = limpiar_y_extraer_datos_pantalla(textos)
            
            ruta_almacenamiento = f"{categoria}_{nombre_limpio}"
            
            with open(ruta_temp, "rb") as f:
                client_local.storage.from_(bucket).upload(
                    path=ruta_almacenamiento,
                    file=f,
                    file_options={"content-type": "image/jpeg", "x-upsert": "true"}
                )
            
            url_publica = f"{url_sb}/storage/v1/object/public/{bucket}/{ruta_almacenamiento}"
            
            # Insertar en base de datos
            datos_db = {
                "categoria": categoria,
                "nombre_archivo": nombre_limpio,
                "url_imagen": url_publica,
                "palabras_clave": datos_limpios
            }
            client_local.table("historial_carreras").insert(datos_db).execute()
            
        except:
            pass
        finally:
            if os.path.exists(ruta_temp):
                os.remove(ruta_temp)
                
    gc.collect()

# --- SECCIÓN: CARGA MASIVA EN SEGUNDO PLANO ---
if opcion == "📥 Cargar Historial":
    st.header(f"📥 Guardar Resultados Finales de {tipo_animal}")
    
    # Notificación persistente si hay tareas corriendo de fondo
    if st.session_state["tareas_activas"]:
        # Filtrar hilos que ya terminaron su labor
        st.session_state["tareas_activas"] = [t for t in st.session_state["tareas_activas"] if t.is_alive()]
        if st.session_state["tareas_activas"]:
            st.warning("⚙️ **Hay subidas procesándose de fondo.** Puedes seguir usando la app con normalidad.")
            
    archivos_historial = st.file_uploader(
        "Selecciona fotos de resultados finales:", 
        accept_multiple_files=True, 
        type=["jpg", "png", "jpeg"],
        key=st.session_state["uploader_key"]
    )
    
    if archivos_historial:
        st.info(f"📂 ¡{len(archivos_historial)} imágenes listas para enviar al segundo plano!")

    if st.button("Enviar y Procesar en Segundo Plano", use_container_width=True):
        if archivos_historial:
            # Clonar los archivos en memoria para que no desaparezcan al limpiar el cargador
            archivos_clonados = []
            for a in archivos_historial:
                archivos_clonados.append({
                    "name": a.name,
                    "bytes": a  # Streamlit maneja los archivos subidos como BytesIO nativos
                })
            
            # Crear y arrancar el hilo secundario invisible
            hilo = threading.Thread(
                target=tarea_subida_segundo_plano,
                args=(archivos_clonados, categoria_actual, SUPABASE_URL, SUPABASE_KEY, nombre_bucket)
            )
            hilo.start()
            
            # Guardar registro del hilo para monitorear su estado
            st.session_state["tareas_activas"].append(hilo)
            
            # AUTO-LIMPIEZA INMEDIATA: Desaparecen los archivos del cuadro gris instantáneamente
            st.session_state["uploader_key"] = str(uuid.uuid4())
            
            st.success("✅ **¡Imágenes enviadas al segundo plano con éxito!** El cuadro se ha vaciado y ya puedes cambiar de menú o realizar búsquedas mientras el servidor procesa tus fotos.")
            time.sleep(1.5)
            st.rerun()
        else:
            st.warning("⚠️ Selecciona primero los archivos de tu galería.")

# --- SECCIÓN: VER HISTORIAL ---
elif opcion == "📋 Ver Historial Completo":
    st.header(f"📋 Historial de Resultados Finales")
    if st.session_state["tareas_activas"]:
        st.caption("🔄 *Nota: Algunas imágenes podrían estar indexándose en este momento de fondo.*")
        
    if not historial_actual:
        st.info(f"Aún no hay carreras registradas.")
    else:
        st.write(f"Total: **{len(historial_actual)}** registros.")
        for elemento in historial_actual:
            with st.expander(f"🖼️ *{elemento['nombre_archivo']}*"):
                st.image(elemento['url_imagen'], use_container_width=True)

# --- SECCIÓN: BUSCADOR POR COMBINACIÓN DE 6 CORREDORES ---
elif opcion == "🔍 Buscar Carrera":
    st.header(f"🔍 Verificar Combinación de 6 Corredores")
    
    origen_foto = st.radio("Origen de la imagen:", ["Galería del Celular", "Cámara del Celular"])
    archivo_busqueda = st.file_uploader("Sube la foto de la tabla de inicio", type=["jpg", "png", "jpeg"]) if origen_foto == "Galería del Celular" else st.camera_input("Toma la foto")
    
    if archivo_busqueda:
        with st.spinner(f"Analizando los 6 corredores y sus cuotas..."):
            reader = cargar_ocr()
            ruta_buscar = "temp_buscar.jpg"
            optimizar_imagen_rapido(archivo_busqueda, ruta_buscar)
            textos_busqueda = reader.readtext(ruta_buscar, detail=0)
            palabras_busqueda = limpiar_y_extraer_datos_pantalla(textos_busqueda)
            if os.path.exists(ruta_buscar):
                os.remove(ruta_buscar)
                
        if not historial_actual:
            st.error("El historial está vacío. Por favor, carga los resultados finales primero.")
        elif not palabras_busqueda:
            st.warning("⚠️ No se detectaron datos legibles.")
        else:
            carrera_repetida = None
            max_corredores_coincidentes = 0
            
            for carrera in historial_actual:
                palabras_carrera = carrera["palabras_clave"]
                coincidencias_estrictas = 0
                
                for p_carrera in palabras_carrera:
