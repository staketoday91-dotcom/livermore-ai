"""
Livermore AI — Discord Bot
Alertas automaticas, mensajes diarios, reportes
"""
import os
import logging
import asyncio
from datetime import datetime, time
import pytz
import discord
from discord.ext import commands, tasks

logger = logging.getLogger("livermore.discord")
NY_TZ  = pytz.timezone("America/New_York")

# ─── Channel IDs ─────────────────────────────────────────────────────────────
GUILD_ID         = int(os.getenv("DISCORD_GUILD_ID",         "0"))
FREE_CH          = int(os.getenv("DISCORD_FREE_CHANNEL",     "0"))
TIER1_CH         = int(os.getenv("DISCORD_TIER1_CHANNEL",    "0"))
TIER2_CH         = int(os.getenv("DISCORD_TIER2_CHANNEL",    "0"))
TIER3_CH         = int(os.getenv("DISCORD_TIER3_CHANNEL",    "0"))
VIP_CH           = int(os.getenv("DISCORD_VIP_CHANNEL",      "0"))
VICTORIES_CH     = int(os.getenv("DISCORD_VICTORIES_CHANNEL","0"))
MOTIVACION_CH    = int(os.getenv("DISCORD_MOTIVACION_CHANNEL","0"))

# Tier → channel mapping
TIER_CHANNELS = {
    "ALERT":     [TIER1_CH],
    "PREMIUM":   [TIER1_CH, TIER2_CH],
    "LIVERMORE": [TIER1_CH, TIER2_CH, TIER3_CH, VIP_CH],
}

LIVERMORE_QUOTES = [
    "El mercado nunca miente — aprende a leerlo.",
    "La gran fortuna espera al trader que estudia sus movimientos antes de actuar.",
    "No es el pensamiento lo que hace el dinero — es la paciencia.",
    "El precio es la única opinión que importa.",
    "Nunca discutas con el tape. El tape siempre tiene razón.",
    "Los mercados no son aleatorios — son el reflejo de la codicia y el miedo humano.",
    "Compra en el breakout, vende en la debilidad. El timing lo es todo.",
    "El trader exitoso actúa — el trader perdedor reacciona.",
]


class LivermoreBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self._quote_index = 0

    async def setup_hook(self):
        self.daily_tasks.start()
        logger.info("Discord bot tasks iniciados")

    async def on_ready(self):
        logger.info(f"Bot conectado como {self.user} — Guild: {GUILD_ID}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="el tape — Livermore AI"
            )
        )

    def _get_channel(self, channel_id: int):
        return self.get_channel(channel_id)

    # ─── ALERTA PRINCIPAL ────────────────────────────────────────────────────
    async def send_alert(self, result: dict, alert_id: int = 0):
        """Envia alerta a los canales correspondientes segun tier"""
        tier     = result.get("tier", "ALERT")
        score    = result.get("score", 0)
        ticker   = result.get("ticker", "")
        contract = result.get("contract", "")
        entry    = result.get("entry", 0)
        sl       = result.get("stop_loss", 0)
        tp1      = result.get("target1", 0)
        tp2      = result.get("target2", 0)
        reason   = result.get("reason", "")
        direction = result.get("direction", "BULLISH")
        breakdown = result.get("score_breakdown", {})
        session  = result.get("session", "REGULAR")
        regime   = result.get("regime", "")

        now_et = datetime.now(NY_TZ).strftime("%I:%M %p ET")

        # Color por tier
        color = {
            "LIVERMORE": 0xD4A832,   # dorado
            "PREMIUM":   0xE8921A,   # amber
            "ALERT":     0x4A9E6B,   # verde
        }.get(tier, 0x4A9E6B)

        # Emoji por direccion
        dir_emoji = "🟢" if direction == "BULLISH" else "🔴"
        dir_text  = "ALCISTA" if direction == "BULLISH" else "BAJISTA"

        # Score bars
        def bar(val, max_val):
            filled = round((val / max_val) * 8)
            return "█" * filled + "░" * (8 - filled)

        # ─── EMBED PRINCIPAL ─────────────────────────────────────────────────
        embed = discord.Embed(
            title=f"{dir_emoji} {ticker} — Score {score}/100",
            color=color,
            timestamp=datetime.now(NY_TZ)
        )

        embed.set_author(name=f"Livermore AI — {tier}", icon_url="")

        if contract:
            embed.add_field(
                name="Contrato recomendado",
                value=f"```{contract}```",
                inline=False
            )

        embed.add_field(
            name="Niveles",
            value=(
                f"```\n"
                f"Entrada:   ${entry:.2f}\n"
                f"Stop Loss: ${sl:.2f}\n"
                f"Target 1:  ${tp1:.2f}\n"
                f"Target 2:  ${tp2:.2f}\n"
                f"```"
            ),
            inline=True
        )

        embed.add_field(
            name="Score breakdown",
            value=(
                f"```\n"
                f"ICC        {bar(breakdown.get('icc', 0), 35)} {breakdown.get('icc', 0)}/35\n"
                f"Dark Pool  {bar(breakdown.get('dark_pool', 0), 30)} {breakdown.get('dark_pool', 0)}/30\n"
                f"Flow       {bar(breakdown.get('options', 0), 25)} {breakdown.get('options', 0)}/25\n"
                f"Macro      {bar(max(breakdown.get('macro', 0), 0), 10)} {breakdown.get('macro', 0)}/10\n"
                f"```"
            ),
            inline=True
        )

        embed.add_field(
            name="Senales activas",
            value=reason[:200] if reason else "—",
            inline=False
        )

        embed.set_footer(text=f"Sesion: {session} | Regimen: {regime} | {now_et} | ID #{alert_id}")

        # ─── ENVIAR A CANALES DEL TIER ────────────────────────────────────────
        channels_to_notify = TIER_CHANNELS.get(tier, [TIER1_CH])

        for ch_id in channels_to_notify:
            ch = self._get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error enviando a canal {ch_id}: {e}")

        # Teaser en free channel (sin contrato ni niveles completos)
        free_ch = self._get_channel(FREE_CH)
        if free_ch:
            teaser = discord.Embed(
                title=f"{dir_emoji} Senal detectada — {ticker}",
                description=(
                    f"Score: **{score}/100** | Tier: **{tier}** | {dir_text}\n\n"
                    f"*Contrato y niveles disponibles para suscriptores.*\n"
                    f"Upgrade en whop.com/livermore-ai"
                ),
                color=0x2a2a2a
            )
            teaser.set_footer(text=f"Livermore AI | {now_et}")
            try:
                await free_ch.send(embed=teaser)
            except Exception as e:
                logger.error(f"Error en free channel: {e}")

    # ─── WIN ANNOUNCEMENT ────────────────────────────────────────────────────
    async def send_victory(self, ticker: str, contract: str, entry: float,
                           exit_price: float, pnl_pct: float, alert_id: int = 0):
        ch = self._get_channel(VICTORIES_CH)
        if not ch:
            return

        emoji = "🏆" if pnl_pct >= 50 else "✅"
        embed = discord.Embed(
            title=f"{emoji} WIN — {ticker}",
            color=0xD4A832,
            timestamp=datetime.now(NY_TZ)
        )
        embed.add_field(name="Contrato", value=f"`{contract}`", inline=False)
        embed.add_field(name="Entrada",  value=f"${entry:.2f}",      inline=True)
        embed.add_field(name="Salida",   value=f"${exit_price:.2f}", inline=True)
        embed.add_field(name="P&L",      value=f"+{pnl_pct:.0f}%",  inline=True)
        embed.set_footer(text=f"Livermore AI | Alerta #{alert_id}")

        await ch.send(embed=embed)

    # ─── TAREAS DIARIAS ──────────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def daily_tasks(self):
        now = datetime.now(NY_TZ)
        h, m = now.hour, now.minute

        # 7:00 AM — Good morning
        if h == 7 and m == 0:
            await self._send_good_morning()

        # 9:15 AM — Pre-apertura briefing
        elif h == 9 and m == 15:
            await self._send_premarket_briefing()

        # 4:30 PM — Cierre
        elif h == 16 and m == 30:
            await self._send_close_report()

        # 8:00 PM — Motivacion
        elif h == 20 and m == 0:
            await self._send_motivacion()

    @daily_tasks.before_loop
    async def before_daily_tasks(self):
        await self.wait_until_ready()

    async def _send_good_morning(self):
        ch = self._get_channel(MOTIVACION_CH)
        if not ch:
            return
        now_str = datetime.now(NY_TZ).strftime("%A, %B %d")
        embed = discord.Embed(
            title="Buenos dias — Livermore AI",
            description=(
                f"**{now_str}**\n\n"
                "El scanner está activo. Monitoreando SPY, QQQ, NVDA y 7 tickers más.\n\n"
                "Pre-market briefing en 15 minutos en #alertas-tier1."
            ),
            color=0xD4A832
        )
        embed.set_footer(text="Livermore AI — El mercado nunca miente.")
        await ch.send(embed=embed)

    async def _send_premarket_briefing(self):
        ch = self._get_channel(TIER1_CH)
        if not ch:
            return
        embed = discord.Embed(
            title="Pre-apertura — 9:15 AM ET",
            description=(
                "Scanner activo. Primera ventana institucional: **9:30 - 11:00 AM**\n\n"
                "Alertas activas cuando score >= 75.\n"
                "Livermore alerts (95+) tienen prioridad maxima."
            ),
            color=0xE8921A
        )
        embed.set_footer(text="Livermore AI")
        await ch.send(embed=embed)

    async def _send_close_report(self):
        ch = self._get_channel(TIER1_CH)
        if not ch:
            return
        embed = discord.Embed(
            title="Cierre de mercado — 4:30 PM ET",
            description=(
                "Sesion regular cerrada.\n\n"
                "Revisa #sala-de-victorias para el P&L del dia.\n"
                "Post-market activo hasta las 8:00 PM ET."
            ),
            color=0x4A9E6B
        )
        embed.set_footer(text="Livermore AI")
        await ch.send(embed=embed)

    async def _send_motivacion(self):
        ch = self._get_channel(MOTIVACION_CH)
        if not ch:
            return
        quote = LIVERMORE_QUOTES[self._quote_index % len(LIVERMORE_QUOTES)]
        self._quote_index += 1
        embed = discord.Embed(
            description=f'*"{quote}"*\n\n— Jesse Livermore',
            color=0x1a1a1a
        )
        embed.set_footer(text="Livermore AI — 8:00 PM ET")
        await ch.send(embed=embed)


# ─── RUNNER ──────────────────────────────────────────────────────────────────
def create_bot() -> LivermoreBot:
    return LivermoreBot()


async def run_bot(bot: LivermoreBot):
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        logger.warning("DISCORD_BOT_TOKEN no configurado — bot desactivado")
        return
    try:
        await bot.start(token)
    except Exception as e:
        logger.error(f"Discord bot error: {e}")
