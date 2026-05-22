"""
Crea el canal #unusual-whales en Sanchez Forge y publica instrucciones.
Requiere permiso 'Gestionar canales' del bot (o creación manual del canal).

Uso: python scripts/setup_discord_uw_channel.py
"""
from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
CHANNEL_NAME = os.getenv("DISCORD_UW_CHANNEL_NAME", "unusual-whales")
EXISTING_ID = os.getenv("DISCORD_UW_CHANNEL", "").strip()

API = "https://discord.com/api/v10"
HEADERS = lambda: {"Authorization": f"Bot {TOKEN}"}

WELCOME = (
    "**Terminal Unusual Whales (privado por usuario)**\n\n"
    "Escribe `/` y elige los comandos del grupo **uw**. "
    "Solo **tú** ves cada respuesta; el resto del servidor no.\n\n"
    "• `/uw flow ticker:SPY` — flujo del ticker\n"
    "• `/uw alerts` — alertas institucionales\n"
    "• `/uw darkpool ticker:NVDA` — dark pool\n"
    "• `/uw tide` — market tide\n\n"
    "_Datos vía API Unusual Whales · cooldown ~12s por usuario_"
)


def main() -> int:
    if not TOKEN or not GUILD_ID:
        print("Falta DISCORD_BOT_TOKEN o DISCORD_GUILD_ID en .env")
        return 1

    with httpx.Client(timeout=20, headers=HEADERS()) as client:
        channel_id = EXISTING_ID
        if channel_id:
            ch = client.get(f"{API}/channels/{channel_id}")
            if ch.status_code == 200:
                print(f"Usando canal existente: #{ch.json().get('name')} ({channel_id})")
            else:
                channel_id = ""

        if not channel_id:
            channels = client.get(f"{API}/guilds/{GUILD_ID}/channels")
            if channels.status_code != 200:
                print(f"Error listando canales: {channels.status_code}")
                return 1
            for ch in channels.json():
                if ch.get("name") == CHANNEL_NAME and ch.get("type") == 0:
                    channel_id = str(ch["id"])
                    print(f"Canal encontrado: #{CHANNEL_NAME} ({channel_id})")
                    break

        if not channel_id:
            created = client.post(
                f"{API}/guilds/{GUILD_ID}/channels",
                json={
                    "name": CHANNEL_NAME,
                    "type": 0,
                    "topic": "Consultas Unusual Whales — respuestas privadas (/uw)",
                },
            )
            if created.status_code not in (200, 201):
                print(
                    "El bot no puede crear canales (falta permiso).\n\n"
                    "Haz esto en Discord (Sanchez Forge):\n"
                    "  1. Clic derecho en la lista de canales → Crear canal → Texto\n"
                    f"  2. Nombre: **{CHANNEL_NAME}**\n"
                    "  3. Clic derecho en el canal → Copiar ID del canal "
                    "(activa Modo desarrollador en Ajustes → Avanzado)\n"
                    "  4. En .env añade: DISCORD_UW_CHANNEL=<ese id>\n"
                    "  5. Vuelve a ejecutar: python scripts/setup_discord_uw_channel.py\n\n"
                    "Opcional: Integraciones → Livermore Bot → activar "
                    "'Gestionar canales' para que el script lo cree solo.\n"
                )
                print(f"Detalle API: {created.status_code}")
                return 1
            channel_id = str(created.json()["id"])
            print(f"Canal creado: #{CHANNEL_NAME} ({channel_id})")

        posted = client.get(f"{API}/channels/{channel_id}/messages", params={"limit": 25})
        has_welcome = False
        if posted.status_code == 200:
            for msg in posted.json():
                if "Terminal Unusual Whales" in (msg.get("content") or ""):
                    has_welcome = True
                    break

        if not has_welcome:
            send = client.post(
                f"{API}/channels/{channel_id}/messages",
                json={"content": WELCOME},
            )
            if send.status_code not in (200, 201):
                print(f"Error publicando mensaje: {send.status_code}")
                return 1
            msg_id = send.json()["id"]
            pin = client.put(f"{API}/channels/{channel_id}/pins/{msg_id}")
            if pin.status_code not in (200, 204):
                print("(Aviso: no pude fijar el mensaje; falta permiso 'Gestionar mensajes')")
            print("Mensaje de bienvenida publicado.")

    print("\n--- Añade a tu .env ---")
    print(f"DISCORD_UW_CHANNEL={channel_id}")
    print("----------------------\n")
    print("Redeploy en Render (livermore-ai) para activar comandos /uw.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
