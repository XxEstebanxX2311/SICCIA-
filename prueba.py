import os
import re
import html
import time
import concurrent.futures
import requests
import urllib.parse
import markdown
from dotenv import load_dotenv
from weasyprint import HTML
from openai import OpenAI

# ==========================================
# 1. CREDENCIALES
# ==========================================
load_dotenv()

client_groq = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
client_google = OpenAI(api_key=os.getenv("GOOGLE_API_KEY"), base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
client_openrouter = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1")
API_KEY_UNSPLASH = os.getenv("UNSPLASH_API_KEY")

# ==========================================
# 2. SISTEMA DE FALLBACKS ANTI-CAÍDAS
# ==========================================
# Equipos de IA por perfil. Si el titular falla, entra el suplente automáticamente.
EQUIPO_ESTUDIANTE = [
    {"cliente": client_google, "modelo": "models/gemini-3.6-flash", "nombre": "Gemini"},
    {"cliente": client_groq, "modelo": "qwen/qwen3.8-27b", "nombre": "Groq (Qwen)"}
]

EQUIPO_DOCENTE = [
    {"cliente": client_openrouter, "modelo": "nvidia/nemotron-3-ultra-550b-a55b:free", "nombre": "Nvidia (Nemotron)"},
    {"cliente": client_groq, "modelo": "qwen/qwen3.8-27b", "nombre": "Groq (Qwen)"}
]

EQUIPO_BASE = [
    {"cliente": client_groq, "modelo": "qwen/qwen3.8-27b", "nombre": "Groq (Qwen)"},
    {"cliente": client_google, "modelo": "models/gemini-3.6-flash", "nombre": "Gemini"}
]

def llamar_modelo_robusto(equipo, sistema, prompt, max_tokens=2000, temperatura=0.7):
    for opcion in equipo:
        cliente = opcion["cliente"]
        modelo = opcion["modelo"]
        nombre = opcion["nombre"]
        
        try:
            response = cliente.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperatura,
                max_tokens=max_tokens,
                timeout=45,
            )
            
            # Validación robusta de la respuesta (evita el error 'NoneType')
            if hasattr(response, 'choices') and response.choices and response.choices[0].message.content:
                return response.choices[0].message.content
            else:
                raise Exception("Respuesta vacía de la API (NoneType)")
                
        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                print(f"      [⚠ {nombre} saturado (Error 429). Esperando 3s y saltando...]")
                time.sleep(3)
            else:
                print(f"      [⚠ {nombre} falló: {error_str[:30]}... Saltando a suplente]")
            continue # Salta a la siguiente IA de la lista
            
    return "<p><em>(Contenido en revisión técnica por saturación de servidores. Intente generar de nuevo.)</em></p>"

def md(texto):
    texto = (texto or "").replace("```markdown", "").replace("```", "").strip()
    return markdown.markdown(texto, extensions=["tables", "sane_lists"])

def obtener_imagen_unsplash(palabra_clave):
    kw_segura = urllib.parse.quote(palabra_clave.strip())
    url = f"https://api.unsplash.com/search/photos?query={kw_segura}&client_id={API_KEY_UNSPLASH}&per_page=1&orientation=landscape"
    try:
        r = requests.get(url, timeout=10).json()
        if r.get("results"):
            return f"<img src='{r['results'][0]['urls']['regular']}' alt='{html.escape(palabra_clave)}' class='img-tema'/>"
    except:
        pass
    return ""

# ==========================================
# 3. AGENTES CONCURRENTES (NIVEL 3 y 4)
# ==========================================
def generar_modulo_estudiante(modulo, contexto_dba, grado):
    # Condicional dinámico adaptativo (Camaleón)
    sistema = f"Eres un instructor experto. Tu audiencia directa es: {grado}. Adapta tu vocabulario, tono y nivel de profundidad ESTRICTAMENTE a este perfil. Si son niños: usa un tono lúdico. Si son adultos/universitarios: usa un tono académico y técnico. NUNCA incluyas metodologías para docentes."
    prompt = f"Tema: '{modulo}'.\nBasado en este marco de competencias: {contexto_dba}\nCrea en Markdown:\n1. Explicación del tema (Totalmente adaptada al perfil de {grado}).\n2. Un ejemplo práctico o caso de estudio.\n3. 3 Ejercicios o retos (solo enunciados)."
    
    texto = llamar_modelo_robusto(EQUIPO_ESTUDIANTE, sistema, prompt, temperatura=0.8)
    kw = llamar_modelo_robusto(EQUIPO_BASE, "Devuelve 1 sola palabra en INGLÉS para buscar una foto de esto.", f"Tema: {modulo}", max_tokens=10, temperatura=0.1)
    
    html_salida = f"<div class='modulo'><h1>{html.escape(modulo)}</h1>"
    html_salida += obtener_imagen_unsplash(kw)
    html_salida += md(texto)
    html_salida += "</div>"
    return html_salida

def generar_modulo_docente(modulo, contexto_dba, grado, metodologia):
    sistema = f"Eres un experto en diseño instruccional. Escribe en tono formal, técnico y metodológico dirigido al FACILITADOR/PROFESOR que va a dictar esta clase a: {grado}."
    prompt = f"Tema: '{modulo}'. Metodología: {metodologia}. \nCompetencias a cumplir: {contexto_dba}\nCrea en Markdown:\n1. Justificación y Resultados de Aprendizaje para este nivel.\n2. Secuencia Didáctica o Actividad de Aprendizaje (Paso a paso).\n3. Rúbrica de evaluación estructurada.\n4. Solucionario técnico de los ejercicios del estudiante."
    
    texto = llamar_modelo_robusto(EQUIPO_DOCENTE, sistema, prompt, temperatura=0.5)
    
    html_salida = f"<div class='modulo'><h1>Guía Docente: {html.escape(modulo)}</h1>"
    html_salida += md(texto)
    html_salida += "</div>"
    return html_salida

def procesar_modulo_paralelo(modulo, contexto_dba, grado, metodologia):
    print(f"   -> Procesando en paralelo: {modulo}")
    time.sleep(2.5) # Pausa preventiva para darle respiro a las APIs gratuitas y evitar el 429
    
    # Hilos de ejecución concurrente
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futuro_est = executor.submit(generar_modulo_estudiante, modulo, contexto_dba, grado)
        futuro_doc = executor.submit(generar_modulo_docente, modulo, contexto_dba, grado, metodologia)
        
        resultado_estudiante = futuro_est.result()
        resultado_docente = futuro_doc.result()
        
    return resultado_estudiante, resultado_docente

# ==========================================
# 4. CONFIGURADOR Y AGENTES BASE (NIVEL 1 y 2)
# ==========================================
print("\n" + "=" * 60)
print("🎓 SICCIA: GENERACIÓN DOBLE CONCURRENTE ROBUSTA 🎓")
print("=" * 60)

tema = input("📚 1. Tema del curso (ej. Matemáticas, Finanzas, Historia): ")
grado = input("🏫 2. Perfil / Grado (ej. 3ro Primaria Colombia, Universitarios 6to semestre): ")
duracion = input("⏱️ 3. Duración (ej. 10 horas): ")
metodologia = input("🧠 4. Metodología de aprendizaje: ")

print(f"\n🔎 Agente Investigador extrayendo marco normativo/competencias para '{grado}'...")
sistema_inv = "Eres un experto en diseño curricular y estándares educativos."
prompt_inv = f"Identifica los lineamientos obligatorios o competencias clave para el tema '{tema}' dirigido Específicamente a: '{grado}'. Si es educación básica en Colombia usa DBA. Si es educación superior/adultos usa estándares profesionales. Enumera en viñetas muy concisas."
contexto_dba = llamar_modelo_robusto(EQUIPO_BASE, sistema_inv, prompt_inv, temperatura=0.2)

print("📐 Agente Estructurador creando módulos adaptados al nivel...")
sistema_est = "Eres un planificador curricular. Devuelve ÚNICAMENTE una lista numerada de módulos (uno por línea), sin texto introductorio."
prompt_est = f"Crea los títulos de los módulos para un curso de {tema} para {grado}, basándote estrictamente en este marco:\n{contexto_dba}"
temario_crudo = llamar_modelo_robusto(EQUIPO_BASE, sistema_est, prompt_est, max_tokens=400, temperatura=0.4)

modulos = []
for linea in (temario_crudo or "").split("\n"):
    if re.match(r"^[#*\-•\s]*(m[oó]dulo\s*)?\d+", linea.strip(), re.I):
        modulos.append(re.sub(r"^[#*\-•\s]+", "", linea).replace("**", "").strip())
if not modulos:
    modulos = ["1. Fundamentos Básicos"]

# ==========================================
# 5. EJECUCIÓN CONCURRENTE DE MÓDULOS
# ==========================================
print(f"\n⚡ Iniciando procesamiento Multi-Agente de {len(modulos)} módulos...")
cuerpo_estudiante = ""
cuerpo_docente = ""

for modulo in modulos:
    html_est, html_doc = procesar_modulo_paralelo(modulo, contexto_dba, grado, metodologia)
    cuerpo_estudiante += html_est
    cuerpo_docente += html_doc

# ==========================================
# 6. GENERACIÓN DE LOS 2 PDFs
# ==========================================
print("\n🖨 Generando archivos PDF independientes...")

estilos_comunes = """
@page { margin: 2.5cm; @bottom-center { content: counter(page); font-size: 9pt; color: #95a5a6; } }
body { font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #2c3e50; }
.portada { text-align: center; margin-top: 150px; }
.portada h1 { font-size: 28pt; color: #2980b9; text-transform: uppercase; }
.meta { margin-top: 30px; background: #f8f9fa; padding: 20px; border-radius: 10px; display: inline-block; text-align: left; }
.modulo { page-break-before: always; }
h1 { font-size: 20pt; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 5px; }
h2 { font-size: 16pt; color: #e67e22; margin-top: 20px; }
p, li { text-align: justify; margin-bottom: 12px; }
table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 10pt; }
th, td { border: 1px solid #bdc3c7; padding: 10px; text-align: left; }
th { background-color: #34495e; color: white; }
.img-tema { max-width: 70%; height: auto; border-radius: 8px; margin: 20px auto; display: block; }
"""

portada_est = f"<div class='portada'><h1>Cuaderno del Estudiante<br>{html.escape(tema)}</h1><div class='meta'><p><strong>Perfil / Nivel:</strong> {html.escape(grado)}</p></div></div>"
portada_doc = f"<div class='portada'><h1>Manual del Docente / Facilitador<br>{html.escape(tema)}</h1><div class='meta'><p><strong>Perfil / Nivel:</strong> {html.escape(grado)}</p><p><strong>Metodología:</strong> {html.escape(metodologia)}</p><p><strong>Duración:</strong> {html.escape(duracion)}</p></div></div>"

html_final_estudiante = f"<html><head><meta charset='utf-8'><style>{estilos_comunes}</style></head><body>{portada_est}{cuerpo_estudiante}</body></html>"
html_final_docente = f"<html><head><meta charset='utf-8'><style>{estilos_comunes}</style></head><body>{portada_doc}{cuerpo_docente}</body></html>"

nombre_base = re.sub(r'[^A-Za-z0-9]+', '_', tema)[:20]
HTML(string=html_final_estudiante).write_pdf(f"Cuaderno_Estudiante_{nombre_base}.pdf")
HTML(string=html_final_docente).write_pdf(f"Manual_Docente_{nombre_base}.pdf")

print(f"✅ ¡Éxito! Se han generado dos documentos:")
print(f"   📄 Cuaderno_Estudiante_{nombre_base}.pdf")
print(f"   📄 Manual_Docente_{nombre_base}.pdf")