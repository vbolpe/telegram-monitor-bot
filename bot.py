import os
import socket
import logging
from datetime import datetime

import pandas as pd
from ping3 import ping
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
EXCEL_PATH = os.getenv("EXCEL_PATH", "/data/red.xlsx")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Utilidades de red
# ─────────────────────────────────────────────

def check_ping(host: str, timeout: float = 2.0) -> bool:
    if not host or str(host).strip().lower() in ("nan", ""):
        return False
    try:
        result = ping(str(host).strip(), timeout=timeout, unit="s")
        return result is not None and result is not False
    except Exception:
        return False


def check_port(host: str, port: int, timeout: float = 3.0) -> bool:
    if not host or str(host).strip().lower() in ("nan", ""):
        return False
    try:
        with socket.create_connection((str(host).strip(), port), timeout=timeout):
            return True
    except Exception:
        return False


def es_vacio(val: str) -> bool:
    return not val or val.strip().lower() in ("nan", "")


# ─────────────────────────────────────────────
#  Lógica de monitoreo
#  Devuelve (resumen_str, [detalle_str, ...])
# ─────────────────────────────────────────────

def monitorear_red():
    try:
        df = pd.read_excel(EXCEL_PATH, dtype=str)
    except Exception as e:
        return f"❌ *Error al leer el Excel:*\n`{e}`", []

    df.columns = [c.strip() for c in df.columns]

    columnas_requeridas = [
        "Sistema", "ROUTER", "IPMI",
        "SERVIDOR (UIP)", "PROXMOX",
        "Puesto 1", "Puesto 2", "Puesto 3 (Director)"
    ]
    for col in columnas_requeridas:
        if col not in df.columns:
            return f"❌ *Columna faltante:* `{col}`", []

    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    total_sedes = len(df)
    caidas = 0

    resumen_lineas = [
        "🖥️ *MONITOREO DE RED — RESUMEN*",
        f"🕐 `{ahora}` — {total_sedes} sedes",
        "─" * 34,
    ]

    detalles = []  # lista de strings, uno por sede

    for _, row in df.iterrows():
        sistema = str(row.get("Sistema", "Sin nombre")).strip()
        if es_vacio(sistema):
            sistema = "Sin nombre"

        router_ip = str(row.get("ROUTER", "")).strip()

        # ── Chequeo del router ─────────────────
        router_ok = check_ping(router_ip)

        if not router_ok:
            caidas += 1
            resumen_lineas.append(f"🔴 {sistema}")
            detalles.append(
                f"📍 *{sistema}*\n"
                f"  🔴 *TOTALMENTE CAÍDO*\n"
                f"  Router `{router_ip}` sin respuesta"
            )
            continue

        # ── Servidor UIP (puerto 80) ───────────
        uip_ip = str(row.get("SERVIDOR (UIP)", "")).strip()
        if not es_vacio(uip_ip):
            uip_ok = check_port(uip_ip, 80)
        else:
            uip_ok = None

        # ── Proxmox (puerto 8006) ──────────────
        proxmox_ip = str(row.get("PROXMOX", "")).strip()
        if not es_vacio(proxmox_ip):
            prox_ok = check_port(proxmox_ip, 8006)
        else:
            prox_ok = None

        # ── Puestos (ping) ─────────────────────
        puestos_ips = [
            str(row.get("Puesto 1", "")).strip(),
            str(row.get("Puesto 2", "")).strip(),
            str(row.get("Puesto 3 (Director)", "")).strip(),
        ]
        puestos_resultados = []
        activos = 0
        total_puestos = 0
        for ip in puestos_ips:
            if not es_vacio(ip):
                total_puestos += 1
                ok = check_ping(ip)
                if ok:
                    activos += 1
                puestos_resultados.append((ip, ok))

        # ── IPMI ──────────────────────────────
        ipmi_ip = str(row.get("IPMI", "")).strip()
        if not es_vacio(ipmi_ip):
            ipmi_ok = check_ping(ipmi_ip)
        else:
            ipmi_ok = None

        # ── Icono resumen de la sede ───────────
        problemas = []
        if uip_ok is False:
            problemas.append("UIP")
        if prox_ok is False:
            problemas.append("Proxmox")
        if total_puestos > 0 and activos < total_puestos:
            problemas.append(f"Puestos {activos}/{total_puestos}")

        if problemas:
            icono_sede = "⚠️"
        else:
            icono_sede = "✅"

        resumen_lineas.append(f"{icono_sede} {sistema}")

        # ── Detalle completo de la sede ────────
        det = [f"📍 *{sistema}*"]
        det.append(f"  🌐 Router: ✅ `{router_ip}`")

        if uip_ok is None:
            det.append("  🖥️  UIP: ⚠️ No configurado")
        else:
            det.append(f"  🖥️  UIP: {'✅' if uip_ok else '❌'} `{uip_ip}:80`")

        if prox_ok is None:
            det.append("  📦 Proxmox: ⚠️ No configurado")
        else:
            det.append(f"  📦 Proxmox: {'✅' if prox_ok else '❌'} `{proxmox_ip}:8006`")

        if total_puestos > 0:
            icono_p = "✅" if activos == total_puestos else ("❌" if activos == 0 else "⚠️")
            det.append(f"  💻 Puestos: {icono_p} {activos}/{total_puestos}")
            partes = [f"`{ip}` {'✅' if ok else '❌'}" for ip, ok in puestos_resultados]
            det.append(f"     {' | '.join(partes)}")
        else:
            det.append("  💻 Puestos: ⚠️ No configurados")

        if ipmi_ok is None:
            det.append("  🔧 IPMI: ⚠️ No configurado")
        else:
            det.append(f"  🔧 IPMI: {'✅' if ipmi_ok else '❌'} `{ipmi_ip}`")

        detalles.append("\n".join(det))

    # ── Pie del resumen ────────────────────────
    sedes_ok = total_sedes - caidas
    resumen_lineas.append("─" * 34)
    resumen_lineas.append(
        f"✅ Operativas: {sedes_ok}/{total_sedes}  |  🔴 Caídas: {caidas}"
    )
    resumen_lineas.append("_Ver mensajes siguientes para detalle_")

    return "\n".join(resumen_lineas), detalles


# ─────────────────────────────────────────────
#  Envío del informe
# ─────────────────────────────────────────────

async def enviar_informe(bot, chat_id: str):
    logger.info("Ejecutando monitoreo...")
    resumen, detalles = monitorear_red()

    # 1. Mensaje de resumen
    await bot.send_message(chat_id=chat_id, text=resumen, parse_mode="Markdown")

    # 2. Agrupar detalles en bloques de ~4000 chars
    bloque = []
    largo_bloque = 0

    for det in detalles:
        if largo_bloque + len(det) + 2 > 4000:
            await bot.send_message(
                chat_id=chat_id,
                text="\n\n".join(bloque),
                parse_mode="Markdown"
            )
            bloque = []
            largo_bloque = 0
        bloque.append(det)
        largo_bloque += len(det) + 2

    if bloque:
        await bot.send_message(
            chat_id=chat_id,
            text="\n\n".join(bloque),
            parse_mode="Markdown"
        )

    logger.info("Informe enviado.")


# ─────────────────────────────────────────────
#  Tarea programada
# ─────────────────────────────────────────────

async def tarea_monitoreo(context: ContextTypes.DEFAULT_TYPE):
    await enviar_informe(context.bot, CHAT_ID)


# ─────────────────────────────────────────────
#  Handlers
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bot de Monitoreo de Red activo.*\n\n"
        "• `/chequear` — Chequeo manual inmediato\n"
        "• `/estado` — Próximo chequeo programado",
        parse_mode="Markdown"
    )


async def cmd_chequear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Iniciando chequeo, aguardá...")
    await enviar_informe(context.bot, update.effective_chat.id)


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = context.job_queue.get_jobs_by_name("monitoreo_red")
    if jobs:
        proximo = jobs[0].next_t
        texto = f"⏰ Próximo chequeo:\n`{proximo.strftime('%d/%m/%Y %H:%M:%S')}`"
    else:
        texto = "⚠️ No hay tareas programadas."
    await update.message.reply_text(texto, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  post_init y main
# ─────────────────────────────────────────────

async def post_init(application: Application):
    application.job_queue.run_once(tarea_monitoreo, when=10, name="monitoreo_inicial")
    application.job_queue.run_repeating(
        tarea_monitoreo, interval=43200, first=43200, name="monitoreo_red"
    )
    logger.info("Jobs registrados: inicio en 10 s, luego cada 12 hs.")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("chequear", cmd_chequear))
    app.add_handler(CommandHandler("estado", cmd_estado))

    logger.info("Bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
