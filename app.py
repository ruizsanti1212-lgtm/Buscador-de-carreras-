import streamlit as st
import easyocr
import pandas as pd
from PIL import Image
import os
import json
import httpx

# Configuración de página móvil
st.set_page_config(page_title="Historial Carreras", layout="centered")
st.title("🏁 Buscador Permanente de Carreras")

# --- CONEXIÓN SEGURA A SUPABASE ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# Carga optimizada del lector OCR
@st.cache_resource
def cargar_ocr():
    return easyocr.Reader(['es', 'en'], gpu=False)

reader = cargar_ocr()

# Inicializar base de datos local permanente en el servidor de la app
if "historial_nube" not in st.session_state:
    st.session_state.historial_nube = []

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

# --- MENÚ MÓVIL ---
opcion = st.sidebar.radio("Ir a:", ["🔍 Buscar Carrera", "📥 Cargar Historial"])

# --- SECCIÓN: CARGA ---
if opcion == "📥 Cargar Historial":
    st.header("📥 Guardar en el Historial")
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
                url_upload_api = f"{SUPABASE_URL}/storage/v1/object/imagenes-carreras/{nombre_limpio}"
                headers_api = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "apikey": SUPABASE_KEY,
                    "Content-Type": "image/jpeg"
                }
                
                with httpx.Client() as cliente:
                    cliente.post(url_upload_api, headers=headers_api, content=datos_binarios)
                
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/imagenes-carreras/{nombre_limpio}"
                
                # Guardar el registro en la memoria estable de la aplicación móvil
                st.session_state.historial_nube.append({
                    "nombre_archivo": nombre_limpio,
                    "url_imagen": url_publica,
                    "palabras_clave": palabras_clave
                })
                
                if os.path.exists(ruta_temp):
                    os.remove(ruta_temp)
                progreso.progress((i + 1) / len(archivos_historial))
                
            st.success(f"¡{len(archivos_historial)} carreras respaldadas exitosamente!")
        else:
            st.warning("Selecciona archivos primero.")

# --- SECCIÓN: BUSCADOR ---
if opcion == "🔍 Buscar Carrera":
    st.header("🔍 Buscar Carrera")
    
    origen_foto = st.radio("Origen de la imagen:", ["Galería del Celular", "Cámara del Celular"])
    archivo_busqueda = st.file_uploader("Sube la imagen", type=["jpg", "png", "jpeg"]) if origen_foto == "Galería del Celular" else st.camera_input("Toma la foto")

    if archivo_busqueda:
        with st.spinner("Buscando en tu historial..."):
            ruta_buscar = "temp_buscar.jpg"
            optimizar_imagen(archivo_busqueda, ruta_buscar)
                
            textos_busqueda = reader.readtext(ruta_buscar, detail=0)
            palabras_busqueda = set([t.lower().strip() for t in textos_busqueda])
            
            if os.path.exists(ruta_buscar):
                os.remove(ruta_buscar)
            
            historial_actual = st.session_state.historial_nube
            
            if not historial_actual:
                st.error("Tu historial está vacío. Carga imágenes primero en el menú lateral.")
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
                    st.image(mejor["url"], caption=f"Historial: {mejor['nombre']}", use_container_width=True)
                else:
                    st.warning("No hay coincidencia exacta. Carreras más parecidas del historial:")
                    for res in resultados_similitud[:3]:
                        with st.expander(f"📋 {res['nombre']} ({res['similitud']:.1f}%)"):
                            st.image(res["url"], use_container_width=True)
