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

# --- CONEXIÓN SEGURA A SUPABASE (SÓLO PARA IMÁGENES) ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
nombre_bucket = "imagenes-carreras"

# Carga optimizada del lector OCR
@st.cache_resource
def cargar_ocr():
    return easyocr.Reader(['es', 'en'], gpu=False)

reader = cargar_ocr()

# --- MENÚ MÓVIL EN LA BARRA LATERAL ---
st.sidebar.header("⚙️ Configuración")
tipo_animal = st.sidebar.radio("Selecciona el tipo de carrera:", ["🐕 Galgos", "🐎 Caballos"])
opcion = st.sidebar.radio("Acción:", ["🔍 Buscar Carrera", "📋 Ver Historial Completo", "📥 Cargar Historial"])

# Convertir el tipo de animal a un texto simple para la base de datos interna
categoria_actual = "galgos" if tipo_animal == "🐕 Galgos" else "caballos"

# Inicializar almacenamiento local estable si no existen
if "db_local_galgos" not in st.session_state:
    st.session_state.db_local_galgos = []
if "db_local_caballos" not in st.session_state:
    st.session_state.db_local_caballos = []

# Asignar el historial correspondiente en la sesión actual
if categoria_actual == "galgos":
    historial_actual = st.session_state.db_local_galgos
else:
    historial_actual = st.session_state.db_local_caballos

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

# --- SECCIÓN: CARGA ---
if opcion == "📥 Cargar Historial":
    st.header(f"📥 Guardar en Historial de {tipo_animal}")
    archivos_historial = st.file_uploader("Selecciona fotos de carreras:", accept_multiple_files=True, type=["jpg", "png", "jpeg"])
    
    if st.button("Procesar y Guardar Permanentemente", use_container_width=True):
        if archivos_historial:
            progreso = st.progress(0)
            for i, archivo in enumerate(archivos_historial):
                ruta_temp = f"temp_{archivo.name}"
                optimizar_imagen(archivo, ruta_temp)
                
                # Leer texto de la imagen (OCR)
                textos_detectados = reader.readtext(ruta_temp, detail=0)
                palabras_clave = [t.lower().strip() for t in textos_detectados]
                
                # Subir imagen a Supabase Storage via API HTTP directa
                with open(ruta_temp, "rb") as f:
                    datos_binarios = f.read()
                
                nombre_limpio = archivo.name.replace(" ", "_")
                url_upload_img = f"{SUPABASE_URL}/storage/v1/object/{nombre_bucket}/{categoria_actual}_{nombre_limpio}"
                headers_img = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "apikey": SUPABASE_KEY,
                    "Content-Type": "image/jpeg"
                }
                
                with httpx.Client() as cliente:
                    cliente.post(url_upload_img, headers=headers_img, content=datos_binarios)
                
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{nombre_bucket}/{categoria_actual}_{nombre_limpio}"
                
                # GUARDAR DIRECTAMENTE EN EL ALMACENAMIENTO ESTABLE INTERNO DE LA APP
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

# --- SECCIÓN: VER HISTORIAL ---
elif opcion == "📋 Ver Historial Completo":
    st.header(f"📋 Galería de Carreras de {tipo_animal}")
    if not historial_actual:
        st.info(f"Aún no hay carreras guardadas en la categoría de {tipo_animal}.")
    else:
        st.write(f"Mostrando un total de **{len(historial_actual)}** carreras guardadas:")
        for elemento in historial_actual:
            with st.expander(f"🖼️ Archivo: {elemento['nombre_archivo']}"):
                st.image(elemento['url_imagen'], use_container_width=True)

# --- SECCIÓN: BUSCADOR ---
elif opcion == "🔍 Buscar Carrera":
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
                    st.image(mejor["url"], use_container_width=True)
                else:
                    st.warning("No hay coincidencia exacta. Carreras más parecidas encontradas:")
                    for res in resultados_similitud[:3]:
                        with st.expander(f"📋 {res['nombre']} ({res['similitud']:.1f}%)"):
                            st.image(res["url"], use_container_width=True)
