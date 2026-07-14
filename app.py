import streamlit as st
import easyocr
from PIL import Image
import os
import uuid
import gc
import threading  
import time  
import io
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
        respuesta = supabase.table("historial_carreras").select("*").eq("categoria", categoria).order("id", descending=True).execute()
        return respuesta.data
    except Exception as e:
        return []

historial_actual = cargar_historial_desde_base_datos(categoria_actual)

def optimizar_imagen_rapido(raw_bytes, ruta_destino):
    """Procesa la imagen directamente desde los bytes guardados de forma segura en memoria."""
    img = Image.open(io.BytesIO(raw_bytes))
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
    """Ejecuta el OCR de forma aislada, compresión y subida a Supabase sin interferir en la UI."""
    client_local = create_client(url_sb, key_sb)
    reader_local = easyocr.Reader(['es', 'en'], gpu=False)
    
    for archivo in lista_archivos:
        id_unico = uuid.uuid4().hex[:8]
        nombre_limpio = f"{id_unico}_{archivo['name'].replace(' ', '_')}"
        ruta_temp = f"temp_{nombre_limpio}"
        
        try:
            # Procesar los bytes clonados inmunes al ciclo de vida de Streamlit
            optimizar_imagen_rapido(archivo["data"], ruta_temp)
            
            # Ejecución OCR
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
    
    if st.session_state["tareas_activas"]:
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
            archivos_clonados = []
            for a in archivos_historial:
                # Extraemos los bytes crudos inmediatamente para evitar pérdidas de datos al refrescar
                archivos_clonados.append({
                    "name": a.name,
                    "data": a.read()  
                })
            
            hilo = threading.Thread(
                target=tarea_subida_segundo_plano,
                args=(archivos_clonados, categoria_actual, SUPABASE_URL, SUPABASE_KEY, nombre_bucket)
            )
            hilo.start()
            
            st.session_state["tareas_activas"].append(hilo)
            st.session_state["uploader_key"] = str(uuid.uuid4())
            
            st.success("✅ **¡Imágenes enviadas al segundo plano con éxito!**")
            time.sleep(1.5)
            st.rerun()
        else:
            st.warning("⚠️ Selecciona primero los archivos de tu galería.")

# --- SECCIÓN: VER HISTORIAL ---
elif opcion == "📋 Ver Historial Completo":
    st.header(f"📋 Historial de Resultados Finales ({tipo_animal})")
    if st.session_state["tareas_activas"]:
        st.caption("🔄 *Nota: Algunas imágenes podrían estar indexándose en este momento de fondo.*")
        
    if not historial_actual:
        st.info(f"Aún no hay carreras registradas en esta categoría.")
    else:
        for item in historial_actual:
            with st.container(border=True):
                st.image(item["url_imagen"], use_container_width=True)
                tags = ", ".join(item["palabras_clave"]) if item["palabras_clave"] else "Sin etiquetas"
                st.caption(f"🔑 **Datos detectados:** {tags}")

# --- SECCIÓN: BUSCAR CARRERA ---
elif opcion == "🔍 Buscar Carrera":
    st.header(f"🔍 Buscador Inteligente ({tipo_animal})")
    
    termino_busqueda = st.text_input("Introduce el nombre del ejemplar, número o pista:", "").strip().lower()
    
    if termino_busqueda:
        resultados_encontrados = []
        
        for item in historial_actual:
            coincidencia_alta = False
            max_similitud = 0.0
            
            for palabra in item["palabras_clave"]:
                if termino_busqueda in palabra:
                    coincidencia_alta = True
                    break
                
                similitud = calcular_similitud_texto(termino_busqueda, palabra)
                if similitud > max_similitud:
                    max_similitud = similitud
            
            if coincidencia_alta or max_similitud >= 0.75:
                # Almacenamos la tupla con el valor numérico para poder ordenar de forma segura
                resultados_encontrados.append((item, max_similitud if not coincidencia_alta else 1.0))
        
        # Ordenamos usando explícitamente el índice numérico [1] (el puntaje de similitud)
        resultados_encontrados.sort(key=lambda x: x[1], reverse=True)
        
        if resultados_encontrados:
            st.success(f"✨ Se encontraron {len(resultados_encontrados)} resultados posibles:")
            for res, score in resultados_encontrados:
                with st.container(border=True):
                    st.image(res["url_imagen"], use_container_width=True)
                    tags = ", ".join(res["palabras_clave"])
                    st.caption(f"🔑 **Datos detectados:** {tags}")
                    if score < 1.0 and score > 0.0:
                        st.caption(f"🎯 *Precisión de coincidencia: {int(score * 100)}%*")
        else:
            st.warning("❌ No se encontraron registros que coincidan con tu búsqueda.")
