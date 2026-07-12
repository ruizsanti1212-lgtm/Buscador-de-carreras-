import streamlit as st
import easyocr
import pandas as pd
from PIL import Image
import os
import json
import httpx

# Configuración de página móvil
st.set_page_config(page_title="Historial Carreras", layout="centered")
st.title("🏁 Buscador de Carreras Multicategoría")

# --- CONEXIÓN SEGURA A SUPABASE ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# Carga optimizada del lector OCR
@st.cache_resource
def cargar_ocr():
    return easyocr.Reader(['es', 'en'], gpu=False)

reader = cargar_ocr()

# Inicializar las dos bases de datos locales separadas en el servidor
if "historial_galgos" not in st.session_state:
    st.session_state.historial_galgos = []
if "historial_caballos" not in st.session_state:
    st.session_state.historial_caballos = []

# Función para reducir el tamaño de la imagen y ahorrar memoria RAM
def optimizar_imagen(imagen_uploader, ruta_destino):
    img = Image.open(imagen_uploader)
    if img.width > 1200:
        proporcion = 1200 / float(img.width)
        alto = int((float(img.height) * float(proporcion)))
        img = img.resize((1200, alto), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(ruta_destino, "JPEG", quality=85)

# --- MENÚ MÓVIL EN LA BARRA LATERAL ---
st.sidebar.header("⚙️ Configuración")
tipo_animal = st.sidebar.radio("Selecciona el tipo de carrera:", ["🐕 Galgos", "🐎 Caballos"])
opcion = st.sidebar.radio("Acción:", ["🔍 Buscar Carrera", "📥 Cargar Historial"])

# Asignar la base de datos correcta según la selección
if tipo_animal == "🐕 Galgos":
    historial_actual = st.session_state.historial_galgos
    nombre_bucket = "imagenes-carreras" # Mantenemos tu bucket por defecto
else:
    historial_actual = st.session_state.historial_caballos
    nombre_bucket = "imagenes-carreras"

# --- SECCIÓN: CARGA ---
if opcion == "📥 Cargar Historial":
    st.header(f"📥 Guardar en Historial de {tipo_animal}")
    archivos_historial = st.file_uploader("Selecciona fotos de carreras:", accept_multiple_files=True, type=["jpg", "png", "jpeg"])
    
    if st.button("Procesar y Guardar Permanentemente", use_container_width=True):
        if archivos_historial:
            progreso = st.progress(0)
            for i, archivo in enumerate(archivos_historial):
                ruta_temp = f"temp_{archivo.name}"
                
                # Optimizar antes de procesar
                optimizar_imagen(archivo, ruta_temp)
                
                # Leer texto de la imagen (OCR)
                textos_detectados = reader.readtext(ruta_temp, detail=0)
                palabras_clave = [t.lower().strip() for t in textos_detectados]
                
                # Subir la imagen optimizada a Supabase Storage vía API HTTP directa
                with open(ruta_temp, "rb") as f:
                    datos_binarios = f.read()
                
                nombre_limpio = archivo.name.replace(" ", "_")
                # Se agrega un prefijo al nombre en la nube para identificar el animal en el mismo storage
                prefijo = "galgos_" if tipo_animal == "🐕 Galgos" else "caballos_"
                url_upload_api = f"{SUPABASE_URL}/storage/v1/object/{nombre_bucket}/{prefijo}{nombre_limpio}"
                headers_api = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "apikey": SUPABASE_KEY,
                    "Content-Type": "image/jpeg"
                }
                
                with httpx.Client() as cliente:
                    cliente.post(url_upload_api, headers=headers_api, content=datos_binarios)
                
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{nombre_bucket}/{prefijo}{nombre_limpio}"
                
                # Guardar el registro en la memoria estable correspondiente
                historial_actual.append({
                    "nombre_archivo": nombre_limpio,
                    "url_imagen": url_publica,
                    "palabras_clave": palabras_clave
                })
                
                if os.path.exists(ruta_temp):
                    os.remove(ruta_temp)
                progreso.progress((i + 1) / len(archivos_historial))
                
            st.success(f"¡{len(archivos_historial)} carreras de {tipo_animal} respaldadas exitosamente!")
        else:
            st.warning("Selecciona archivos primero.")

# --- SECCIÓN: BUSCADOR ---
if opcion == "🔍 Buscar Carrera":
    st.header(f"🔍 Buscar en Historial de {tipo_animal}")
    
    origen_foto = st.radio("Origen de la imagen:", ["Galería del Celular", "Cámara del Celular"])
    archivo_busqueda = st.file_uploader("Sube la imagen", type=["jpg", "png", "jpeg"]) if origen_foto == "Galería del Celular" else st.camera_input("Toma la foto")

    if archivo_busqueda:
        with st.spinner(f"Buscando en tu historial de {tipo_animal}..."):
            ruta_buscar = "temp_buscar.jpg"
            optimizar_imagen(archivo_busqueda, ruta_buscar)
                
            textos_busqueda = reader.readtext(ruta_buscar, detail=0)
            palabras_busqueda = set([t.lower().strip() for t in textos_busqueda])
            
            if os.path.exists(ruta_buscar):
                os.remove(ruta_buscar)
            
            if not historial_actual:
                st.error(f"Tu historial de {tipo_animal} está vacío. Carga imágenes primero en esta categoría.")
            else:
                resultados_similitud = []
                for carrera in historial_actual:
                    palabras_carrera = set(carrera["palabras_clave"])
                    coincidencias = palabras_busqueda.intersection(palabras_carrera)
                    porcentaje = (len(coincidencias) / len(palabras_busqueda)) * 100 if palabras_busqueda else 0
                    
                    resultados_similitud.append({
                        "nombre": carrera["nombre_archivo"],
                        "url": carrera["url_imagen"],
                        "similitud": porcentaje
                    })
                
                resultados_similitud = sorted(resultados_similitud, key=lambda x: x["similitud"], reverse=True)
                mejor = resultados_similitud[0]
                
                if mejor["similitud"] > 80:
                    st.success(f"🎯 ¡Carrera encontrada! Similitud: {mejor['similitud']:.1f}%")
                    st.image(mejor["url"], caption=f"Historial {tipo_animal}: {mejor['nombre']}", use_container_width=True)
                else:
                    st.warning("No hay coincidencia exacta. Carreras más parecidas encontradas:")
                    for res in resultados_similitud[:3]:
                        with st.expander(f"📋 {res['nombre']} ({res['similitud']:.1f}%)"):
                            st.image(res["url"], use_container_width=True)
