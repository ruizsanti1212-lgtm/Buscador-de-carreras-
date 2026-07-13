import streamlit as st
import easyocr
from PIL import Image
import os
import uuid
import gc  # Liberador de memoria del sistema
import time
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

# Carga e inicialización optimizada del lector OCR
@st.cache_resource
def cargar_ocr():
    return easyocr.Reader(['es', 'en'], gpu=False)

reader = cargar_ocr()

# --- CONTROL DE ESTADO (SOLUCIÓN AL BLOQUEO DE SUBIDAS) ---
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = str(uuid.uuid4())

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
    except Exception as e:
        st.error(f"Error al insertar datos: {e}")
        return False

@st.cache_data(ttl=60)  # Almacena en caché el historial durante 1 minuto para optimizar rendimiento
def cargar_historial_desde_base_datos(categoria):
    try:
        respuesta = supabase.table("historial_carreras").select("*").eq("categoria", categoria).execute()
        return respuesta.data
    except Exception as e:
        return []

historial_actual = cargar_historial_desde_base_datos(categoria_actual)

# --- COMPRESIÓN ULTRA RÁPIDA DE IMÁGENES ---
def optimizar_imagen_rapido(imagen_uploader, ruta_destino):
    """Reduce drásticamente el tamaño para que el OCR procese en milisegundos."""
    img = Image.open(imagen_uploader)
    # Reducimos a 800px de ancho (suficiente para pantallas y mucho más rápido de procesar)
    if img.width > 800:
        proporcion = 800 / float(img.width)
        alto = int((float(img.height) * float(proporcion)))
        img = img.resize((800, alto), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    # Bajamos la calidad a 70% (el texto sigue siendo legible pero el archivo pesa la mitad)
    img.save(ruta_destino, "JPEG", quality=70, optimize=True)

# --- PROCESADOR FILTRADO DE TEXTO PANTALLA ---
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

# --- SECCIÓN: CARGA MASIVA CON AUTO-LIMPIEZA Y ESTADOS ---
if opcion == "📥 Cargar Historial":
    st.header(f"📥 Guardar Resultados Finales de {tipo_animal}")
    
    # El componente usa una clave dinámica que podemos resetear para blanquear el cuadro
    archivos_historial = st.file_uploader(
        "Selecciona fotos de resultados finales:", 
        accept_multiple_files=True, 
        type=["jpg", "png", "jpeg"],
        key=st.session_state["uploader_key"]
    )
    
    if st.button("Procesar y Guardar Todo", use_container_width=True):
        if archivos_historial:
            total_archivos = len(archivos_historial)
            exitos_guardados = 0
            
            # Contenedores visuales dinámicos
            zona_alerta = st.empty()
            zona_progreso = st.empty()
            zona_texto = st.empty()
            
            # Mensaje en AZUL para el proceso de análisis y subida
            zona_alerta.info(f"⏳ **Procesando e indexando {total_archivos} imágenes... Por favor, no cierres la app.**")
            
            for i, archivo in enumerate(archivos_historial):
                zona_texto.caption(f"📦 Analizando y subiendo: `{archivo.name}`")
                zona_progreso.progress((i + 1) / total_archivos)
                
                id_unico = uuid.uuid4().hex[:8]
                nombre_limpio = f"{id_unico}_{archivo.name.replace(' ', '_')}"
                ruta_temp = f"temp_{nombre_limpio}"
                
                optimizar_imagen_rapido(archivo, ruta_temp)
                
                textos_detectados = reader.readtext(ruta_temp, detail=0)
                palabras_clave = limpiar_y_extraer_datos_pantalla(textos_detectados)
                
                ruta_almacenamiento = f"{categoria_actual}_{nombre_limpio}"
                try:
                    with open(ruta_temp, "rb") as f:
                        supabase.storage.from_(nombre_bucket).upload(
                            path=ruta_almacenamiento,
                            file=f,
                            file_options={"content-type": "image/jpeg", "x-upsert": "true"}
                        )
                    
                    url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{nombre_bucket}/{ruta_almacenamiento}"
                    guardado_exitoso = guardar_en_base_datos(categoria_actual, nombre_limpio, url_publica, palabras_clave)
                    
                    if guardado_exitoso:
                        exitos_guardados += 1
                except Exception as e:
                    st.error(f"❌ Error al subir {archivo.name}: {e}")
                finally:
                    if os.path.exists(ruta_temp):
                        os.remove(ruta_temp)
            
            # Liberar memoria RAM residual inmediatamente
            gc.collect()
            
            # Limpiar elementos temporales de la pantalla
            zona_texto.empty()
            zona_progreso.empty()
            
            if exitos_guardados > 0:
                # Alerta final en VERDE
                zona_alerta.success(f"✅ ¡Se han subido y procesado exitosamente {exitos_guardados} de {total_archivos} carreras!")
                
                # AUTO-LIMPIEZA: Cambiar el ID del uploader elimina las fotos del cuadro gris al instante
                st.session_state["uploader_key"] = str(uuid.uuid4())
                
                st.cache_data.clear()  # Forzar actualización inmediata del historial
                time.sleep(2.5)        # Pausa para que el usuario aprecie el estado verde
                st.rerun()
            else:
                zona_alerta.error("❌ No se pudo procesar ninguna imagen correctamente.")
        else:
            st.warning("⚠️ Por favor, selecciona al menos un archivo antes de presionar el botón.")

# --- SECCIÓN: VER HISTORIAL ---
elif opcion == "📋 Ver Historial Completo":
    st.header(f"📋 Historial de Resultados Finales")
    if not historial_actual:
        st.info(f"Aún no hay carreras registradas.")
    else:
        st.write(f"Total: **{len(historial_actual)}** registros.")
        for elemento in historial_actual:
            with st.expander(f"🖼 *{elemento['nombre_archivo']}*"):
                st.image(elemento['url_imagen'], use_container_width=True)
                if elemento['palabras_clave']:
                    st.caption(f"Datos Guardados: {', '.join(elemento['palabras_clave'])}")

# --- SECCIÓN: BUSCADOR POR COMBINACIÓN DE 6 CORREDORES ---
elif opcion == "🔍 Buscar Carrera":
    st.header(f"🔍 Verificar Combinación de 6 Corredores")
    st.write("Sube la foto del inicio de la carrera para comprobar si se repiten los mismos 6 corredores con sus mismas cuotas.")
    
    origen_foto = st.radio("Origen de la imagen:", ["Galería del Celular", "Cámara del Celular"])
    archivo_busqueda = st.file_uploader("Sube la foto de la tabla de inicio", type=["jpg", "png", "jpeg"]) if origen_foto == "Galería del Celular" else st.camera_input("Toma la foto")
    
    if archivo_busqueda:
        with st.spinner(f"Analizando los 6 corredores y sus cuotas..."):
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
            
            # Recorremos el historial buscando coincidencias del bloque de corredores
            for carrera in historial_actual:
                palabras_carrera = carrera["palabras_clave"]
