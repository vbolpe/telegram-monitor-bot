import os
import socket
import asyncio
import logging
from datetime import datetime

import pandas as pd
from ping3 import ping
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
    """Devuelve True si el host responde a ping."""
    if not host or str(host).strip().lower() in ("nan", ""):
        return False
    try:
        result = ping(str(host).strip(), timeout=timeout, unit="s")
        return result is not None and result is not False
    except Exception:
        return False


def check_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Devuelve True si el puerto TCP está abierto."""
    if not host or str(host).strip().lower() in ("nan", ""):
        return False
    try:
        with socket.create_connection((str(host).strip(), port), timeout=timeout):
            return True
    except Exception:
        return False


# ─────────────────────────────────────────────
#  Lógica de monitoreo
# ─────────────────────────────────────────────

def monitorear_red() -> str:
    """Lee el Excel y ejecuta los chequeos. Devuelve el mensaje formateado."""
    try:
        df = pd.read_excel(EXCEL_PATH, dtype=str)
    except Exception as e:
        return f"❌ *Error al leer el archivo Excel:*\n`{e}`"

    # Normalizar nombres de columnas (quitar espacios extra)
    df.columns = [c.strip() for c in df.columns]

    columnas_requeridas = [
        "Sistema", "ROUTER", "IPMI",
        "SERVIDOR (UIP)", "PROXMOX",
        "Puesto 1", "Puesto 2", "Puesto 3 (Director)"
    ]
    for col in columnas_requeridas:
        if col not in df.columns:
            return f"❌ *Columna faltante en el Excel:* `{col}`"

    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    lineas = [
        f"🖥️ *MONITOREO DE RED*",
        f"🕐 `{ahora}`",
        "─" * 32,
    ]

    for _, row in df.iterrows():
        sistema = str(row.get("Sistema", "Sin nombre")).strip()
        if sistema.lower() == "nan":
            sistema = "Sin nombre"

        router_ip = str(row.get("ROUTER", "")).strip()

        lineas.append(f"\n📍 *{sistema}*")

        # ── 1. Chequeo del ROUTER ──────────────────
        router_ok = check_ping(router_ip)
        if not router_ok:
            lineas.append(f"  🔴 *TOTALMENTE CAÍDO* (Router `{router_ip}` sin respuesta)")
            lineas.append("─" * 32)
            continue

        lineas.append(f"  🌐 Router: ✅ `{router_ip}`")

        # ── 2. Servidor UIP (puerto 80) ────────────
        uip_ip = str(row.get("SERVIDOR (UIP)", "")).strip()
        if uip_ip and uip_ip.lower() != "nan":
            uip_ok = check_port(uip_ip, 80)
            estado_uip = "✅" if uip_ok else "❌"
            lineas.append(f"  🖥️  Servidor UIP: {estado_uip} `{uip_ip}:80`")
        else:
            lineas.append("  🖥️  Servidor UIP: ⚠️ No configurado")

        # ── 3. Proxmox (puerto 8006) ───────────────
        proxmox_ip = str(row.get("PROXMOX", "")).strip()
        if proxmox_ip and proxmox_ip.lower() != "nan":
            prox_ok = check_port(proxmox_ip, 8006)
            estado_prox = "✅" if prox_ok else "❌"
            lineas.append(f"  📦 Proxmox: {estado_prox} `{proxmox_ip}:8006`")
        else:
            lineas.append("  📦 Proxmox: ⚠️ No configurado")

        # ── 4. Puestos de trabajo ──────────────────
        puestos = {
            "Puesto 1": str(row.get("Puesto 1", "")).strip(),
            "Puesto 2": str(row.get("Puesto 2", "")).strip(),
            "Puesto 3": str(row.get("Puesto 3 (Director)", "")).strip(),
        }

        activos = 0
        total = 0
        detalles_puestos = []

        for nombre, ip in puestos.items():
            if ip and ip.lower() != "nan":
                total += 1
                ok = check_ping(ip)
                if ok:
                    activos += 1
                detalles_puestos.append(f"`{ip}` {'✅' if ok else '❌'}")

        if total > 0:
            if activos == total:
                icono_puestos = "✅"
            elif activos == 0:
                icono_puestos = "❌"
            else:
                icono_puestos = "⚠️"
            lineas.append(f"  💻 Puestos: {icono_puestos} {activos}/{total} activos")
            lineas.append(f"     {' | '.join(detalles_puestos)}")
        else:
            lineas.append("  💻 Puestos: ⚠️ No configurados")

        # ── 5. IPMI (solo ping informativo) ───────
        ipmi_ip = str(row.get("IPMI", "")).strip()
        if ipmi_ip and ipmi_ip.lower() != "nan":
            ipmi_ok = check_ping(ipmi_ip)
            estado_ipmi = "✅" if ipmi_ok else "❌"
            lineas.append(f"  🔧 IPMI: {estado_ipmi} `{ipmi_ip}`")

        lineas.append("─" * 32)

    lineas.append("\n_Próximo chequeo en 12 hs_")
    return "\n".join(lineas)


# ─────────────────────────────────────────────
#  Envío del informe
# ─────────────────────────────────────────────

async def enviar_informe(bot: Bot):
    logger.info("Ejecutando monitoreo de red...")
    mensaje = monitorear_red()
    try:
        # Telegram tiene límite de 4096 chars por mensaje
        max_len = 4000
        for i in range(0, len(mensaje), max_len):
            await bot.send_message(
                chat_id=CHAT_ID,
                text=mensaje[i:i + max_len],
                parse_mode="Markdown"
            )
        logger.info("Informe enviado correctamente.")
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {e}")


# ─────────────────────────────────────────────
#  Handlers de Telegram
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bot de Monitoreo de Red activo.*\n\n"
        "Comandos disponibles:\n"
        "• `/chequear` — Ejecuta un chequeo inmediato\n"
        "• `/estado` — Muestra el próximo chequeo programado",
        parse_mode="Markdown"
    )


async def cmd_chequear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Iniciando chequeo manual, aguardá un momento...")
    mensaje = monitorear_red()
    max_len = 4000
    for i in range(0, len(mensaje), max_len):
        await update.message.reply_text(mensaje[i:i + max_len], parse_mode="Markdown")


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scheduler: AsyncIOScheduler = context.bot_data.get("scheduler")
    if scheduler:
        jobs = scheduler.get_jobs()
        if jobs:
            proximo = jobs[0].next_run_time
            texto = f"⏰ Próximo chequeo automático:\n`{proximo.strftime('%d/%m/%Y %H:%M:%S')}`"
        else:
            texto = "⚠️ No hay tareas programadas."
    else:
        texto = "⚠️ Scheduler no disponible."
    await update.message.reply_text(texto, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Registrar comandos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("chequear", cmd_chequear))
    app.add_handler(CommandHandler("estado", cmd_estado))

    # Scheduler cada 12 horas
    scheduler = AsyncIOScheduler(timezone="America/Argentina/Buenos_Aires")
    scheduler.add_job(
        enviar_informe,
        trigger="interval",
        hours=12,
        args=[app.bot],
        id="monitoreo_red",
        next_run_time=datetime.now()  # Ejecutar al arrancar
    )
    scheduler.start()
    app.bot_data["scheduler"] = scheduler

    logger.info("Bot iniciado. Esperando mensajes...")
    await app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    asyncio.run(main())
