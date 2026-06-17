"""
Agente de Diagnóstico de Marca — Interfaz Web (Streamlit)
Cada participante abre la URL en su navegador y tiene su propia sesión.
"""

import os
import json
import smtplib
import datetime
import anthropic
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── Configuración ────────────────────────────────────────────────────────────

OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")
SMTP_USER   = os.getenv("SMTP_USER", "")
SMTP_PASS   = os.getenv("SMTP_PASS", "")

MODEL_CONVERSACION = "claude-haiku-4-5-20251001"
MODEL_DIAGNOSTICO  = "claude-sonnet-4-6"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "diagnosticos")

# ─── Prompts ──────────────────────────────────────────────────────────────────

SYSTEM_CONVERSACION = """Sos un consultor de marca amable y cercano que está facilitando un taller
con dueños y responsables de pymes latinoamericanas. Tu trabajo es recopilar información sobre su
empresa haciéndoles preguntas una por una, de manera conversacional y cálida.

Reglas importantes:
- Hacé UNA sola pregunta a la vez. Nunca hagas más de una pregunta en el mismo mensaje.
- Usá un tono cercano, sin tecnicismos, como si fuera una charla distendida.
- Si la respuesta es vaga, podés pedir una aclaración breve antes de pasar a la siguiente pregunta.
- Cuando el participante responda, confirmá brevemente lo que entendiste y avanzá a la siguiente.
- Cuando hayas recopilado todos los datos, devolvé EXACTAMENTE este texto (sin nada antes ni después):
  DATOS_COMPLETOS_JSON: seguido del JSON con los datos en una sola línea.

Campos a recopilar (en este orden):
1. nombre_persona, rol, email
2. nombre_empresa, sector
3. industria (industria o rubro específico de la empresa)
4. cantidad_empleados (cantidad aproximada de empleados)
5. problema_clientes (qué problema resuelven para sus clientes)
6. diferencial (qué los diferencia según sus mejores clientes)
7. valores (valores que definen cómo trabajan)
8. personalidad_marca (3 adjetivos: si su marca fuera una persona, sería...)
9. cliente_ideal (perfil del cliente ideal)
10. motivacion_eleccion (qué mueve a ese cliente a elegirlos)
11. canales_captacion (dónde encuentran a sus clientes hoy)
12. canales_comunicacion (canales de comunicación actuales)
13. presencia_online (qué encuentra un cliente nuevo si los busca online)
14. coherencia_autopercibida (número del 1 al 5: coherencia entre identidad y comunicación)
15. decision_comunicacion (quién toma las decisiones de comunicación)
16. produccion_contenido (quién produce el contenido)
17. uso_ia (usan IA en su comunicación, cómo)
18. plan_comunicacion (tienen plan o calendario de comunicación: SÍ/NO + detalle)
19. objetivo_comunicacion (con qué objetivo comunican)
20. metricas (miden algo de su comunicación)
21. publicidad_paga (hacen publicidad paga como Meta o Google Ads, y cuánto invierten por mes aproximadamente)

Cuando tengas todos los datos, devolvé solo:
DATOS_COMPLETOS_JSON: {"nombre_persona": "...", "rol": "...", ...}"""

SYSTEM_DIAGNOSTICO = """Sos un consultor de marca con experiencia en pymes latinoamericanas.
Tu trabajo es analizar la información que una empresa compartió sobre sí misma y generar un
diagnóstico honesto, constructivo y accionable sobre la coherencia entre su identidad real
y su comunicación actual."""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def extraer_json_datos(texto: str):
    marcador = "DATOS_COMPLETOS_JSON:"
    if marcador not in texto:
        return None
    try:
        parte_json = texto.split(marcador, 1)[1].strip()
        return json.loads(parte_json)
    except (json.JSONDecodeError, IndexError):
        return None


def construir_prompt_diagnostico(datos: dict) -> str:
    return f"""Datos de la empresa:
Nombre y rol: {datos.get('nombre_persona')} | {datos.get('rol')} | {datos.get('email')}
Empresa y sector: {datos.get('nombre_empresa')} | {datos.get('sector')}
Industria: {datos.get('industria')}
Cantidad de empleados: {datos.get('cantidad_empleados')}
Problema que resuelven para sus clientes: {datos.get('problema_clientes')}
Qué los diferencia, según sus mejores clientes: {datos.get('diferencial')}
Valores que definen cómo trabajan: {datos.get('valores')}
Si su marca fuera una persona, sería: {datos.get('personalidad_marca')}
Cliente ideal (perfil): {datos.get('cliente_ideal')}
Qué mueve a ese cliente a elegirlos: {datos.get('motivacion_eleccion')}
Dónde encuentran a sus clientes hoy: {datos.get('canales_captacion')}
Canales de comunicación actuales: {datos.get('canales_comunicacion')}
Qué encuentra un cliente nuevo si los busca online: {datos.get('presencia_online')}
Coherencia autopercibida entre identidad y comunicación (1 al 5): {datos.get('coherencia_autopercibida')}
Quién toma las decisiones de comunicación: {datos.get('decision_comunicacion')}
Quién produce el contenido: {datos.get('produccion_contenido')}
Usan IA en su comunicación (cómo): {datos.get('uso_ia')}
Tienen plan o calendario de comunicación: {datos.get('plan_comunicacion')}
Con qué objetivo comunican: {datos.get('objetivo_comunicacion')}
Miden algo de su comunicación: {datos.get('metricas')}
Publicidad paga e inversión mensual: {datos.get('publicidad_paga')}

Generá el diagnóstico con exactamente esta estructura:

{datos.get('nombre_empresa')} — Diagnóstico de Coherencia de Marca
Lo que sos: [2-3 oraciones que sintetizan la identidad real de la empresa, basadas en sus respuestas. Integrá valores, diferencial y buyer persona en una lectura coherente.]

La tensión principal: [El punto donde hay más distancia entre quiénes dicen ser y cómo se muestran o actúan. Sé específico: mencioná qué canal, qué mensaje, qué práctica crea la incoherencia. Si la coherencia autopercibida es baja, explorá por qué. Si es alta pero las acciones no lo reflejan, señalalo.]

Una oportunidad concreta: [Una sola acción específica y accionable que podrían implementar para reducir la tensión identificada. Que sea realista para una pyme, sin mencionar herramientas pagas ni servicios de terceros. Derivá de lo que ya tienen, no de lo que les falta comprar.]"""


def enviar_email(datos: dict, diagnostico: str):
    """Envia el diagnostico por email. Devuelve (ok: bool, error: str)."""
    if not all([OWNER_EMAIL, SMTP_USER, SMTP_PASS]):
        faltantes = [k for k, v in {"OWNER_EMAIL": OWNER_EMAIL, "SMTP_USER": SMTP_USER, "SMTP_PASS": SMTP_PASS}.items() if not v]
        return False, f"Faltan variables de entorno: {', '.join(faltantes)}"
    try:
        def limpiar(s):
            return str(s).encode("ascii", "replace").decode("ascii")

        persona = limpiar(datos.get("nombre_persona", "participante"))
        empresa = limpiar(datos.get("nombre_empresa", "empresa")).replace(" ", "_")

        lineas = [
            "NUEVO DIAGNOSTICO DE MARCA",
            "=" * 50,
            f"PARTICIPANTE: {persona} <{limpiar(datos.get('email', ''))}>",
            f"EMPRESA: {empresa}",
            "",
            "DATOS RECOPILADOS:",
        ]
        for k, v in datos.items():
            lineas.append(f"  {limpiar(k)}: {limpiar(v)}")
        lineas += ["", "DIAGNOSTICO:", "=" * 50, limpiar(diagnostico)]
        cuerpo = "\n".join(lineas)

        asunto = limpiar(f"[Taller Marca] Diagnostico de {empresa} - {persona}")

        import email.message
        msg = email.message.EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = SMTP_USER
        msg["To"] = OWNER_EMAIL
        msg.set_content(cuerpo)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True, ""
    except Exception as e:
        return False, str(e)


def guardar_y_notificar(datos: dict, diagnostico: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    empresa = datos.get("nombre_empresa", "empresa").replace(" ", "_")
    ruta = os.path.join(OUTPUT_DIR, f"diagnostico_{empresa}_{timestamp}.json")

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.datetime.now().isoformat(),
            "datos_participante": datos,
            "diagnostico": diagnostico,
        }, f, ensure_ascii=False, indent=2)

    enviar_email(datos, diagnostico)


def obtener_respuesta_agente(client: anthropic.Anthropic, historial: list) -> str:
    respuesta = client.messages.create(
        model=MODEL_CONVERSACION,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": SYSTEM_CONVERSACION,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=historial,
    )
    return respuesta.content[0].text


def generar_diagnostico(client: anthropic.Anthropic, datos: dict) -> str:
    respuesta = client.messages.create(
        model=MODEL_DIAGNOSTICO,
        max_tokens=1500,
        system=[{
            "type": "text",
            "text": SYSTEM_DIAGNOSTICO,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": construir_prompt_diagnostico(datos),
        }],
    )
    return respuesta.content[0].text


# ─── Inicialización del estado de sesión ─────────────────────────────────────

def init_session():
    if "historial_api" not in st.session_state:
        st.session_state.historial_api = []       # mensajes para la API
    if "mensajes_chat" not in st.session_state:
        st.session_state.mensajes_chat = []       # mensajes para mostrar en el chat
    if "datos_completos" not in st.session_state:
        st.session_state.datos_completos = None   # dict con datos cuando estén listos
    if "diagnostico" not in st.session_state:
        st.session_state.diagnostico = None       # texto del diagnóstico
    if "iniciado" not in st.session_state:
        st.session_state.iniciado = False


# ─── App principal ────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Diagnóstico de Marca",
        page_icon="🎯",
        layout="centered",
    )

    # CSS para un look limpio y profesional
    st.markdown("""
    <style>
        .stApp { background-color: #f8f6f2; }
        .main-header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            padding: 2rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            text-align: center;
        }
        .main-header h1 { margin: 0; font-size: 1.8rem; }
        .main-header p { margin: 0.5rem 0 0; opacity: 0.8; font-size: 0.95rem; }
        .diagnostico-box {
            background: white;
            border-left: 4px solid #e63946;
            padding: 1.5rem 2rem;
            border-radius: 8px;
            margin: 1rem 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .stChatMessage { border-radius: 12px; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="main-header">
        <h1>🎯 Diagnóstico de Coherencia de Marca</h1>
        <p>Taller de identidad y comunicación para pymes</p>
    </div>
    """, unsafe_allow_html=True)

    init_session()

    # ── Panel de prueba de email (sidebar) ───────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Panel de administración")
        if st.button("📧 Probar envío de email"):
            datos_prueba = {
                "nombre_persona": "Prueba",
                "rol": "Admin",
                "email": SMTP_USER,
                "nombre_empresa": "Test",
            }
            ok, error = enviar_email(datos_prueba, "Este es un email de prueba del sistema.")
            if ok:
                st.success(f"✅ Email enviado correctamente a {OWNER_EMAIL}")
            else:
                st.error(f"❌ Error: {error}")
        st.markdown("---")
        st.caption(f"OWNER_EMAIL: `{OWNER_EMAIL or '⚠️ no configurado'}`")
        st.caption(f"SMTP_USER: `{SMTP_USER or '⚠️ no configurado'}`")
        st.caption(f"SMTP_PASS: `{'✅ configurado' if SMTP_PASS else '⚠️ no configurado'}`")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("⚠️ Falta configurar la variable de entorno `ANTHROPIC_API_KEY`.")
        st.stop()

    client = anthropic.Anthropic(api_key=api_key)

    # ── Fase 1: Diagnóstico ya generado ──────────────────────────────────────
    if st.session_state.diagnostico:
        st.success("✅ ¡Tu diagnóstico está listo!")

        empresa = st.session_state.datos_completos.get("nombre_empresa", "Tu empresa")
        st.markdown(f"<div class='diagnostico-box'>{st.session_state.diagnostico.replace(chr(10), '<br>')}</div>",
                    unsafe_allow_html=True)

        st.download_button(
            label="📥 Descargar diagnóstico (.txt)",
            data=st.session_state.diagnostico,
            file_name=f"diagnostico_{empresa.replace(' ', '_')}.txt",
            mime="text/plain",
        )

        st.info("¡Gracias por participar del taller! 🎉")
        return

    # ── Fase 2: Generando diagnóstico ────────────────────────────────────────
    if st.session_state.datos_completos and not st.session_state.diagnostico:
        with st.spinner("⏳ Analizando tu marca y generando el diagnóstico..."):
            diagnostico = generar_diagnostico(client, st.session_state.datos_completos)
            st.session_state.diagnostico = diagnostico
            guardar_y_notificar(st.session_state.datos_completos, diagnostico)
        st.rerun()

    # ── Fase 3: Conversación ─────────────────────────────────────────────────

    # Primer mensaje del agente si la conversación no inició
    if not st.session_state.iniciado:
        with st.spinner("Iniciando..."):
            primer_usuario = "Hola, estoy listo para hacer el diagnóstico."
            st.session_state.historial_api.append({
                "role": "user", "content": primer_usuario
            })
            respuesta = obtener_respuesta_agente(client, st.session_state.historial_api)
            st.session_state.historial_api.append({
                "role": "assistant", "content": respuesta
            })
            st.session_state.mensajes_chat.append({
                "role": "assistant", "content": respuesta
            })
            st.session_state.iniciado = True
        st.rerun()

    # Mostrar historial del chat
    for msg in st.session_state.mensajes_chat:
        with st.chat_message(msg["role"], avatar="🎯" if msg["role"] == "assistant" else "👤"):
            st.markdown(msg["content"])

    # Input del participante
    if entrada := st.chat_input("Escribí tu respuesta aquí..."):
        # Mostrar mensaje del usuario
        st.session_state.mensajes_chat.append({"role": "user", "content": entrada})
        with st.chat_message("user", avatar="👤"):
            st.markdown(entrada)

        # Agregar al historial de la API
        st.session_state.historial_api.append({"role": "user", "content": entrada})

        # Obtener respuesta del agente
        with st.chat_message("assistant", avatar="🎯"):
            with st.spinner("Pensando..."):
                respuesta = obtener_respuesta_agente(client, st.session_state.historial_api)

            # Verificar si los datos están completos
            datos = extraer_json_datos(respuesta)

            if datos:
                st.session_state.datos_completos = datos
                st.session_state.historial_api.append({
                    "role": "assistant", "content": respuesta
                })
                mensaje_cierre = "¡Perfecto! Tengo toda la información. Ahora voy a generar tu diagnóstico de marca personalizado... 🔍"
                st.session_state.mensajes_chat.append({
                    "role": "assistant", "content": mensaje_cierre
                })
                st.markdown(mensaje_cierre)
            else:
                st.session_state.historial_api.append({
                    "role": "assistant", "content": respuesta
                })
                st.session_state.mensajes_chat.append({
                    "role": "assistant", "content": respuesta
                })
                st.markdown(respuesta)

        st.rerun()


if __name__ == "__main__":
    main()
