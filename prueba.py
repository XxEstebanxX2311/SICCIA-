import os
import re
import html
import time
import csv
import requests
import urllib.parse
import markdown
from dotenv import load_dotenv
from weasyprint import HTML
from openai import OpenAI

load_dotenv()

# ==========================================
# 1. CONFIGURACIÓN SICCIA
# ==========================================
MODELO_GROQ = "qwen/qwen3.8-27b"
MODELO_GOOGLE = "models/gemini-3.6-flash"
MODELO_OPENROUTER = "nvidia/nemotron-3-ultra-550b-a55b:free"

MAX_MODULOS = 6
MAX_TEMAS = 3
MAX_AFIRMACIONES = 5
USAR_FUENTES_EXTERNAS = True       
FILTRO_RESTRICCIONES = "advertir"  
PAUSA = 1.0                        

API_KEY_UNSPLASH = os.getenv("UNSPLASH_API_KEY")

# Regla estricta para evitar la tipografía rota en el PDF
ANTI_LATEX = "REGLA ESTRICTA: Usa ÚNICAMENTE Markdown estándar. ESTÁ TOTALMENTE PROHIBIDO usar LaTeX, MathJax, o símbolos de dólar ($ o $$). Escribe las fórmulas como texto plano (ej. a + b = c)."

def crear_cliente(var, url):
    k = os.getenv(var)
    return OpenAI(api_key=k, base_url=url) if k else None

groq = crear_cliente("GROQ_API_KEY", "https://api.groq.com/openai/v1")
google = crear_cliente("GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/")
openrouter = crear_cliente("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1")

def equipo(*items):
    return [{"cliente": c, "modelo": m, "nombre": n} for c, m, n in items if c]

EQUIPO_BASE = equipo((groq, MODELO_GROQ, "Groq"), (google, MODELO_GOOGLE, "Gemini"))
EQUIPO_ESTUDIANTE = equipo((google, MODELO_GOOGLE, "Gemini"), (groq, MODELO_GROQ, "Groq"))
EQUIPO_DOCENTE = equipo((groq, MODELO_GROQ, "Groq"), (openrouter, MODELO_OPENROUTER, "OpenRouter"), (google, MODELO_GOOGLE, "Gemini"))
EQUIPO_VERIF = equipo((groq, MODELO_GROQ, "Groq"), (openrouter, MODELO_OPENROUTER, "OpenRouter"))

RIGOR = {
    "1": "fuentes académicas formales (artículos revisados por pares, normas, organismos oficiales)",
    "2": "fuentes divulgativas confiables y organismos oficiales",
}

TIPOS_EVAL = {
    "1": ("Selección múltiple", "5 preguntas de selección múltiple con 4 opciones (A-D) y una única respuesta correcta."),
    "2": ("Preguntas abiertas", "3 preguntas abiertas que exijan una respuesta elaborada."),
    "3": ("Caso de estudio", "Un caso práctico y 3 preguntas de análisis sobre él.")
}

CATEGORIAS = "educación clínica, actividades peligrosas, asesoría legal/financiera, adoctrinamiento, contenido sexual, actividades ilícitas"

# ==========================================
# 2. UTILIDADES Y REGISTRO CSV (PAPER)
# ==========================================
def log_prueba(proveedor, modelo, tarea, r, segundos):
    """Guarda automáticamente los consumos en CSV para el artículo académico."""
    u = getattr(r, "usage", None)
    pt = getattr(u, "prompt_tokens", 0) if u else 0
    ct = getattr(u, "completion_tokens", 0) if u else 0
    
    archivo = "registro_pruebas_siccia.csv"
    es_nuevo = not os.path.exists(archivo)
    
    with open(archivo, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        if es_nuevo:
            writer.writerow(["Fecha", "Proveedor", "Modelo", "Tarea", "Prompt_Tokens", "Completion_Tokens", "Tiempo_Segundos"])
        writer.writerow([time.strftime("%Y-%m-%d %H:%M"), proveedor, modelo, tarea, pt, ct, round(segundos, 1)])

def llamar(eq, sistema, prompt, tarea="General", max_tokens=2000, temperatura=0.5, min_chars=1):
    """Llamada robusta con reintentos y logging de tokens."""
    for _ in range(2):
        for o in eq:
            try:
                t0 = time.time()
                r = o["cliente"].chat.completions.create(
                    model=o["modelo"],
                    messages=[{"role": "system", "content": sistema}, {"role": "user", "content": prompt}],
                    temperature=temperatura, max_tokens=max_tokens, timeout=60,
                )
                t1 = time.time()
                txt = (r.choices[0].message.content or "") if r.choices else ""
                txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
                
                if len(txt) >= min_chars:
                    log_prueba(o["nombre"], o["modelo"], tarea, r, t1 - t0)
                    time.sleep(PAUSA)
                    return txt
                print(f"      [⚠ {o['nombre']}: respuesta vacía]")
            except Exception as e:
                msg = str(e).splitlines()[0][:60]
                if "429" in msg:
                    print(f"      [⚠ {o['nombre']}: Error 429. Pausa de 5s...]")
                    time.sleep(5)
                else:
                    print(f"      [⚠ {o['nombre']}: {msg}]")
                continue
        time.sleep(5)
    return ""

def md(texto):
    texto = (texto or "").replace("```markdown", "").replace("```", "").strip()
    if not texto: return "<p><em>(Error en generación de contenido)</em></p>"
    return markdown.markdown(texto, extensions=["tables", "sane_lists"])

def obtener_imagen_unsplash(kw):
    if not API_KEY_UNSPLASH or not kw: return ""
    url = f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(kw)}&client_id={API_KEY_UNSPLASH}&per_page=1&orientation=landscape"
    try:
        r = requests.get(url, timeout=10).json()
        if r.get("results"):
            img = r["results"][0]
            return f"<img src='{img['urls']['regular']}' alt='{html.escape(kw)}' class='img-tema'/><p class='caption'>Foto por {html.escape(img['user']['name'])} en Unsplash</p>"
    except: pass
    return ""

def parsear_estructura(txt):
    mods = []
    for linea in (txt or "").splitlines():
        linea = linea.strip()
        if not linea: continue
        if "||" in linea:
            tit, temas = linea.split("||", 1)
            mods.append({"titulo": re.sub(r"^[#*\-•\s]+", "", tit).strip(), "temas": [t.strip() for t in temas.split(";") if t.strip()][:MAX_TEMAS]})
    return mods[:MAX_MODULOS]

# ==========================================
# 3. AGENTES SICCIA
# ==========================================
def estructurar(tema, grado, duracion, marco):
    sistema = "Eres un planificador curricular. Devuelve SOLO líneas con este formato: Título del Módulo || Tema 1; Tema 2"
    prompt = f"Curso '{tema}' para {grado}, duración {duracion}.\nMarco de referencia:\n{marco}\nPropón entre 3 y {MAX_MODULOS} módulos."
    parsed = parsear_estructura(llamar(EQUIPO_BASE, sistema, prompt, tarea="Orquestar_Estructura", max_tokens=700, temperatura=0.4))
    return parsed or [{"titulo": "1. Fundamentos Básicos", "temas": ["Introducción"]}]

def generar_tema_estudiante(cfg, mod_titulo, tema_nombre, marco):
    sistema = f"Eres un instructor experto. Audiencia: {cfg['grado']}. Adapta tono y profundidad a este perfil. NO incluyas guías docentes ni respuestas. {ANTI_LATEX}"
    prompt = f"Curso: '{cfg['tema']}'. Módulo: '{mod_titulo}'. Tema: '{tema_nombre}'.\nMarco:\n{marco}\n\nEscribe en Markdown: #### Explicación, #### Ejemplo, #### Actividad Práctica (solo 3 ejercicios numerados)."
    txt = llamar(EQUIPO_ESTUDIANTE, sistema, prompt, tarea="Generar_Tema_Estudiante", max_tokens=1800, temperatura=0.6, min_chars=300)
    kw = llamar(EQUIPO_BASE, "Devuelve 1 palabra clave en INGLÉS para buscar una foto.", f"Tema: {tema_nombre}", tarea="Buscar_Palabra_Clave", max_tokens=20) or "Learning"
    return txt, kw

def generar_guia_docente(cfg, mod_titulo, marco, textos_estudiante):
    contenido_real = "\n\n".join(textos_estudiante)
    sistema = f"Eres experto en diseño instruccional. Escribe formalmente para el FACILITADOR de {cfg['grado']}. {ANTI_LATEX}"
    prompt = f"Curso: '{cfg['tema']}'. Módulo: '{mod_titulo}'. Metodología: {cfg['metodologia']}.\n\nCONTENIDO REAL DEL ESTUDIANTE:\n{contenido_real}\n\nEscribe en Markdown: ### Secuencia didáctica y ### Solucionario EXACTO de los ejercicios planteados al estudiante."
    return llamar(EQUIPO_DOCENTE, sistema, prompt, tarea="Generar_Guia_Docente", max_tokens=2000, temperatura=0.3, min_chars=200)

def generar_evaluacion(cfg, tipo_ev, contexto_global):
    nombre_tipo, instr = TIPOS_EVAL[tipo_ev]
    sis_est = f"Eres diseñador de evaluaciones para {cfg['grado']}. Genera SOLO el enunciado para el estudiante, sin respuestas. {ANTI_LATEX}"
    prompt_est = f"Tipo: {nombre_tipo}. {instr}\nBasa TODO en este contenido enseñado:\n{contexto_global}"
    preguntas = llamar(EQUIPO_ESTUDIANTE, sis_est, prompt_est, tarea="Generar_Eval_Estudiante", max_tokens=1500)
    
    if not preguntas: return "", ""
    
    sis_doc = f"Eres diseñador de evaluaciones. {ANTI_LATEX}"
    prompt_doc = f"PREGUNTAS EXACTAS DEL ESTUDIANTE:\n{preguntas}\n\nEntrega en Markdown la clave de respuestas EXACTA y retroalimentación para el docente."
    clave = llamar(EQUIPO_DOCENTE, sis_doc, prompt_doc, tarea="Generar_Eval_Docente", max_tokens=2000, temperatura=0.2)
    return preguntas, clave

def verificar_tema(texto):
    if not USAR_FUENTES_EXTERNAS: return ""
    sis = "Extraes afirmaciones verificables. Responde en líneas: Afirmación en español || query corto en inglés"
    raw = llamar(EQUIPO_VERIF, sis, f"Texto:\n{texto}", tarea="Extraer_Afirmaciones", max_tokens=400, temperatura=0.1)
    
    bloques = []
    for linea in raw.splitlines()[:MAX_AFIRMACIONES]:
        if "||" in linea:
            a, q = linea.split("||", 1)
            try:
                r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search", params={"query": q.strip(), "limit": 2, "fields": "title,year,abstract"}, timeout=10)
                evidencia = [f"{p['title']}: {p.get('abstract','')[:200]}" for p in r.json().get("data", []) if p.get('abstract')]
                bloques.append(f"Afirmación: {a}\nEvidencia: {' | '.join(evidencia) if evidencia else 'Ninguna'}")
            except: pass
            
    if not bloques: return ""
    
    sis_j = "Eres verificador riguroso. Responde SOLO con tabla Markdown: # | Afirmación | Veredicto (CORRECTA/IMPRECISA/INCORRECTA) | Motivo"
    return llamar(EQUIPO_VERIF, sis_j, "\n\n".join(bloques), tarea="Juzgar_Afirmaciones", max_tokens=1000, temperatura=0.1)

# ==========================================
# 4. FLUJO PRINCIPAL
# ==========================================
if not (EQUIPO_BASE and EQUIPO_ESTUDIANTE and EQUIPO_DOCENTE):
    raise SystemExit("❌ Falta GROQ_API_KEY o GOOGLE_API_KEY en el archivo .env")

print("\n" + "=" * 60)
print("🎓 SICCIA: GENERADOR CON REGISTRO ACADÉMICO 🎓")
print("=" * 60)

cfg = {
    "tema": input("📚 1. Tema del curso: "),
    "grado": input("🏫 2. Público / Nivel: "),
    "duracion": input("⏱️ 3. Duración estimada: ") or "No especificada",
    "metodologia": input("🧠 4. Metodología: ") or "Teórico-práctica",
}
tipo_ev = input("📝 5. Tipo de Evaluación [1: Selección Múltiple, 2: Abiertas, 3: Caso]: ") or "1"
if tipo_ev not in TIPOS_EVAL: tipo_ev = "1"

print("\n🔎 Investigando marco curricular (DBA/Competencias)...")
marco = llamar(EQUIPO_BASE, "Eres experto en estándares educativos de Colombia.", f"Lineamientos clave para '{cfg['tema']}' en '{cfg['grado']}'.", tarea="Investigar_Marco", max_tokens=1000, temperatura=0.2)
if not marco: raise SystemExit("❌ Falla crítica en la investigación inicial.")

print("📐 Estructurando Módulos...")
modulos = estructurar(cfg['tema'], cfg['grado'], cfg['duracion'], marco)

cuerpo_estudiante = ""
cuerpo_docente = ""
contexto_global_curso = ""

print("\n⚡ Iniciando procesamiento en Cascada...")
for i, mod in enumerate(modulos, 1):
    print(f"\n📦 Módulo {i}: {mod['titulo']}")
    
    html_mod_est = f"<div class='modulo'><h1>Módulo {i}: {html.escape(mod['titulo'])}</h1>"
    textos_est_brutos = []
    
    for tema in mod['temas']:
        print(f"   -> Tema: {tema}")
        txt_est, kw = generar_tema_estudiante(cfg, mod['titulo'], tema, marco)
        textos_est_brutos.append(txt_est)
        contexto_global_curso += txt_est + "\n"
        
        html_mod_est += f"<h2>{html.escape(tema)}</h2>{obtener_imagen_unsplash(kw)}{md(txt_est)}"
        
        # Verificación en segundo plano (Opcional)
        print("      🛡️ Verificando veracidad...")
        veredicto = verificar_tema(txt_est)
        if veredicto:
            cuerpo_docente += f"<div class='alerta-verificacion'><h4>Resultados de Veracidad: {html.escape(tema)}</h4>{md(veredicto)}</div>"

    html_mod_est += "</div>"
    cuerpo_estudiante += html_mod_est
    
    # El docente se genera basado en lo que escribió el estudiante
    print("   👩‍🏫 Generando Guía Docente y Solucionario...")
    guia_doc = generar_guia_docente(cfg, mod['titulo'], marco, textos_est_brutos)
    cuerpo_docente += f"<div class='modulo'><h1>Guía Docente - Módulo {i}: {html.escape(mod['titulo'])}</h1>{md(guia_doc)}</div>"

print("\n📝 Generando Evaluación Global del Curso...")
eval_est, eval_doc = generar_evaluacion(cfg, tipo_ev, contexto_global_curso)

cuerpo_estudiante += f"<div class='modulo'><h1>Evaluación Final</h1>{md(eval_est)}</div>"
cuerpo_docente += f"<div class='modulo'><h1>Clave de Respuestas - Evaluación</h1>{md(eval_doc)}</div>"

# ==========================================
# 5. RENDERIZADO DE PDFs
# ==========================================
print("\n🖨 Guardando PDFs...")

css = """
@page { margin: 2.5cm; @bottom-center { content: counter(page); font-size: 9pt; color: #7f8c8d; } }
body { font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #2c3e50; }
.portada { text-align: center; margin-top: 30%; }
.portada h1 { font-size: 28pt; color: #2980b9; text-transform: uppercase; }
.meta { background: #f8f9fa; padding: 20px; border-radius: 10px; margin-top: 20px; text-align: left; display: inline-block; }
.modulo { page-break-before: always; }
h1 { color: #2c3e50; border-bottom: 2px solid #3498db; }
h2 { color: #e67e22; margin-top: 20px; border-bottom: 1px solid #eee; }
h4 { color: #16a085; }
.img-tema { max-width: 65%; border-radius: 8px; display: block; margin: 10px auto; }
.caption { text-align: center; font-size: 8pt; color: #95a5a6; }
.alerta-verificacion { border-left: 4px solid #e74c3c; background: #fadbd8; padding: 10px; margin: 15px 0; }
table { width: 100%; border-collapse: collapse; margin-top: 15px; }
th, td { border: 1px solid #bdc3c7; padding: 8px; text-align: left; }
th { background-color: #34495e; color: white; }
"""

p_est = f"<div class='portada'><h1>Cuaderno del Estudiante<br>{html.escape(cfg['tema'])}</h1><div class='meta'><b>Nivel:</b> {html.escape(cfg['grado'])}</div></div>"
p_doc = f"<div class='portada'><h1>Manual del Docente<br>{html.escape(cfg['tema'])}</h1><div class='meta'><b>Nivel:</b> {html.escape(cfg['grado'])}<br><b>Metodología:</b> {html.escape(cfg['metodologia'])}</div></div>"

nombre_archivo = re.sub(r'[^A-Za-z0-9]+', '_', cfg['tema'])[:20]
HTML(string=f"<html><head><style>{css}</style></head><body>{p_est}{cuerpo_estudiante}</body></html>").write_pdf(f"Cuaderno_Estudiante_{nombre_archivo}.pdf")
HTML(string=f"<html><head><style>{css}</style></head><body>{p_doc}{cuerpo_docente}</body></html>").write_pdf(f"Manual_Docente_{nombre_archivo}.pdf")

print("✅ Curso guardado exitosamente.")
print("📊 El registro de tokens y tiempos fue guardado en: registro_pruebas_siccia.csv")