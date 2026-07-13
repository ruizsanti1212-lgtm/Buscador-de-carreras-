import streamlit as st
import easyocr
from PIL import Image
import os
import datetime
from supabase import create_client, Client

# Configuración de página móvil
st.set_page_config(page_title="Historial Carreras", layout="centered")
st.title("🏁 Buscador de Carreras Multicategoría")

# --- CONEXIÓN SEGURA Y OFICIAL A SUPABASE ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
nombre_bucket = "imagenes-carreras"

# Inicializar el cliente oficial
@st.cache_resource
def inicializar_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    supabase: Client = inicializar_supabase()
except Exception as e:
    st.error(f"Error al inicializar las credenciales de Supabase: {e}")

# Carga optimizada del lector OCR
@st.cache_resource
def cargar_ocr():
    return easyocr.Reader(['es', 'en'], gpu=False)

reader = cargar_ocr()

# --- MENÚ MÓVIL EN LA BARRA LATERAL ---
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
        st.error(f"Error al insertar datos en la tabla: {e}")
        return False

def cargar_historial_desde_base_datos(categoria):
    try:
        respuesta = supabase.table("historial_carreras").select("*").eq("categoria", categoria).execute()
        return respuesta.data
    except Exception as e:
        st.error(f"Error de autenticación o conexión (Revisa SUPABASE_KEY y URL en Secrets): {e}")
        return []

historial_actual = cargar_historial_desde_base_datos(categoria_actual)

def optimizar_imagen(imagen_uploader, ruta_destino):
    img = Image.open(imagen_uploader)
    if img.width > 1000:
        proporcion = 1000 / float(img.width)
        alto = int((float(img.height) * float(proporcion)))
        img = img.resize((1000, alto), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(ruta_destino, "JPEG", quality=80)

# --- SECCIÓN: CARGA ---
if opcion == "📥 Cargar Historial":
    st.header(f"📥 Guardar en Historial de {tipo_animal}")
    archivos_historial = st.file_uploader("Selecciona fotos de carreras:", accept_multiple_files=True, type=["jpg", "png", "jpeg"])
    
    if st.button("Procesar y Guardar Permanentemente", use_container_width=True):
        if archivos_historial:
            progreso = st.progress(0)
            exitos_guardados = 0
            
            for i, archivo in enumerate(archivos_historial):
                # Crear prefijo único usando el tiempo para evitar que se bloquee por nombres idénticos
                marca_tiempo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                nombre_limpio = f"{marca_tiempo}_{archivo.name.replace(' ', '_')}"
                ruta_temp = f"temp_{nombre_limpio}"
                
                optimizar_imagen(archivo, ruta_temp)
                
                textos_detectados = reader.readtext(ruta_temp, detail=0)
                palabras_clave = [t.lower().strip() for t in textos_detectados]
                
                ruta_almacenamiento = f"{categoria_actual}_{nombre_limpio}"
                try:
                    with open(ruta_temp, "rb") as f:
                        supabase.storage.from_(nombre_bucket).upload(
                            path=ruta_almacenamiento,
                            file=f,
                            file_options={"content-type": "image/jpeg", "x-upsert": "true"}
                        )
                except Exception as e:
                    st.error(f"Error en Supabase Storage (Asegúrate de que el bucket sea público): {e}")
                
                url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{nombre_bucket}/{ruta_almacenamiento}"
                
                guardado_exitoso = guardar_en_base_datos(categoria_actual, nombre_limpio, url_publica, palabras_clave)
                if guardado_exitoso:
                    exitos_guardados += 1
                
                if os.path.exists(ruta_temp):
                    os.remove(ruta_temp)
                
                progreso.progress((i + 1) / len(archivos_historial))
            
            if exitos_guardados > 0:
                st.success(f"¡{exitos_guardados} carreras respaldadas exitosamente!")
                st.rerun()
        else:
            st.warning("Selecciona archivos primero.")

# --- SECCIÓN: VER HISTORIAL ---
elif opcion == "📋 Ver Historial Completo":
    st.header(f"📋 Galería de Carreras de {tipo_animal}")
    if not historial_actual:
        st.info(f"Aún no hay carreras guardadas para {tipo_animal}.")
    else:
        st.write(f"Mostrando un total de **{len(historial_actual)}** carreras:")
        for elemento in historial_actual:
            with st.expander(f"🖼️ Archivo: {elemento['nombre_archivo']}"):
                st.image(elemento['url_imagen'], use_container_width=True)

# --- SECCIÓN: BUSCADOR ---
elif opcion == "🔍 Buscar Carrera":
    st.header(f"🔍 Buscar en Historial de {tipo_animal}")
    origen_foto = st.radio("Origen de la imagen:", ["Galería del Celular", "Cámara del Celular"])
    archivo_busqueda = st.file_uploader("Sube la imagen", type=["jpg", "png", "jpeg"]) if origen_foto == "Galería del Celular" else st.camera_input("Toma la foto")

    if archivo_busqueda:
        with st.spinner(f"Buscando en tu historial..."):
            ruta_buscar = "temp_buscar.jpg"
            optimizar_imagen(archivo_busqueda, ruta_buscar)
                
            textos_busqueda = reader.readtext(ruta_buscar, detail=0)
            palabras_busqueda = set([t.lower().strip() for t in textos_busqueda])
            
            if os.path.exists(ruta_buscar):
                os.remove(ruta_buscar)
            
            if not historial_actual:
                st.error("Tu historial está vacío. Carga imágenes primero.")
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
                
                if mejor["similitud"] > 50:
                    st.success(f"🎯 ¡Carrera encontrada! Similitud: {mejor['similitud']:.1f}%")
                    st.image(mejor["url"], use_container_width=True)
                else:
                    st.warning("No hay coincidencia exacta alta. Las más parecidas son:")
                    for res in resultados_similitud[:3]:
                        with st.expander(f"📋 {res['nombre']} ({res['similitud']:.1f}%)"):
                            st.image(res["url"], use_container_width=True)
