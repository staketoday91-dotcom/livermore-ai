"""
Livermore AI — Discord Bot
Alertas automaticas, mensajes diarios, reportes
"""
import os
import logging
import asyncio
import re
from datetime import datetime, time
import pytz
import discord
from discord.ext import commands, tasks

from core.uw_fetcher import format_contracts_for_copy

logger = logging.getLogger("livermore.discord")
NY_TZ  = pytz.timezone("America/New_York")
_OCC_RE = re.compile(r"^([A-Z]+)\d{6}[CP]\d{8}$")


def _assert_contract_belongs(ticker: str, contract: str) -> bool:
    if not contract:
        return True
    match = _OCC_RE.match(contract.strip().upper())
    if not match or match.group(1) != ticker.upper():
        logger.error(
            f"CONTRACT MISMATCH AT PUBLISH: "
            f"ticker={ticker} contract={contract} — SKIPPING"
        )
        return False
    return True

# ─── Channel IDs ─────────────────────────────────────────────────────────────
GUILD_ID         = int(os.getenv("DISCORD_GUILD_ID",         "0"))
FREE_CH          = int(os.getenv("DISCORD_FREE_CHANNEL",     "0"))
TIER1_CH         = int(os.getenv("DISCORD_TIER1_CHANNEL",    "0"))
TIER2_CH         = int(os.getenv("DISCORD_TIER2_CHANNEL",    "0"))
TIER3_CH         = int(os.getenv("DISCORD_TIER3_CHANNEL",    "0"))
VIP_CH           = int(os.getenv("DISCORD_VIP_CHANNEL",      "0"))
VICTORIES_CH     = int(os.getenv("DISCORD_VICTORIES_CHANNEL","0"))
MOTIVACION_CH    = int(os.getenv("DISCORD_MOTIVACION_CHANNEL","0"))
UW_CH            = int(os.getenv("DISCORD_UW_CHANNEL",         "0"))

UW_WELCOME = (
    "**Terminal Unusual Whales (privado por usuario)**\n\n"
    "Escribe `/` y elige **uw**. Solo **tú** ves cada respuesta.\n\n"
    "• `/uw flow ticker:SPY` · `/uw alerts` · `/uw darkpool ticker:NVDA` · `/uw tide`"
)

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
        from bot.uw_private import UWPrivateCog

        await self.add_cog(UWPrivateCog(self))
        self.daily_tasks.start()
        logger.info("Discord bot tasks iniciados")

    async def on_ready(self):
        logger.info(f"Bot conectado como {self.user} — Guild: {GUILD_ID}")
        if GUILD_ID:
            try:
                guild = discord.Object(id=GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info(f"Slash commands /uw sincronizados: {len(synced)}")
            except Exception as e:
                logger.error(f"Error sincronizando slash commands: {e}")
        await self._ensure_uw_welcome()
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="el tape — Livermore AI"
            )
        )

    def _get_channel(self, channel_id: int):
        return self.get_channel(channel_id)

    async def _ensure_uw_welcome(self):
        if not UW_CH:
            return
        ch = self._get_channel(UW_CH)
        if not ch:
            return
        try:
            async for msg in ch.history(limit=20):
                if msg.author and msg.author.id == self.user.id and "Terminal Unusual Whales" in (msg.content or ""):
                    return
            await ch.send(UW_WELCOME)
        except Exception as e:
            logger.warning(f"No pude publicar bienvenida UW en {UW_CH}: {e}")

    # ─── ALERTA PRINCIPAL ────────────────────────────────────────────────────
    async def send_alert(self, result: dict, alert_id: int = 0):
        """Envia alerta a los canales correspondientes segun tier"""
        tier     = result.get("tier", "ALERT")
        score    = result.get("score", 0)
        ticker   = result.get("ticker", "")
        category = result.get("category", "STOCK")
        contract = result.get("contract", "")
        entry    = result.get("entry", 0)
        sl       = result.get("stop_loss", 0)
        tp1      = result.get("target1", 0)
        tp2      = result.get("target2", 0)
        direction = result.get("direction", "BULLISH")
        breakdown = result.get("score_breakdown", {})
        session  = result.get("session", "REGULAR")
        regime   = result.get("regime", "")
        nominal  = result.get("nominal_value") or result.get("accumulated_nominal") or result.get("premium") or 0
        oi_data  = result.get("oi_data") or {}
        chain_map = result.get("chain_map") or {}
        macro_calendar = result.get("macro_calendar") or {}
        delta = result.get("delta", 0.50)
        repeated_flow = bool(result.get("repeated_flow"))
        flow_count = int(result.get("flow_count", 0) or 0)
        is_single_leg = result.get("is_single_leg", True)

        now_et = datetime.now(NY_TZ).strftime("%I:%M %p ET")
        if not _assert_contract_belongs(ticker, contract):
            return

        def money_compact(value) -> str:
            try:
                n = float(value or 0)
            except (TypeError, ValueError):
                n = 0
            if n >= 1_000_000:
                return f"${n / 1_000_000:.1f}M".replace(".0M", "M")
            if n >= 1_000:
                return f"${n / 1_000:.0f}K"
            return f"${n:.0f}" if n > 0 else "--"

        def price(value) -> str:
            try:
                return f"${float(value):.2f}"
            except (TypeError, ValueError):
                return "--"

        def delta_zone(value) -> str:
            try:
                d = abs(float(value if value is not None else 0.50))
            except (TypeError, ValueError):
                d = 0.50
            if 0.30 <= d <= 0.70:
                zone = "zona conviccion"
            elif 0.15 <= d < 0.30:
                zone = "OTM moderado"
            elif d < 0.15:
                zone = "OTM extremo"
            else:
                zone = "deep ITM / posible hedge"
            return f"Δ {d:.2f} ({zone})"

        def macro_text() -> str:
            if macro_calendar.get("has_event_today"):
                events = ", ".join(macro_calendar.get("events_today", [])[:2]) or "Evento macro"
                return f"⚠️ EVENTO HOY: {events}"
            if macro_calendar.get("has_event_tomorrow"):
                events = ", ".join(macro_calendar.get("events_tomorrow", [])[:2]) or "Evento macro"
                return f"⚡ EVENTO MAÑANA: {events}"
            return "✅ Sin eventos"

        def oi_text() -> str:
            if not oi_data.get("oi_growing"):
                return "Sin datos OI"
            days = int(oi_data.get("days_growing", 0) or 0)
            return f"↑ {days} días consecutivos" if days > 0 else "↑ OI creciendo"

        # Emoji por direccion
        dir_emoji = "🟢" if direction == "BULLISH" else "🔴"
        dir_text  = "BULLISH" if direction == "BULLISH" else "BEARISH"
        color = 0xC0392B if direction == "BEARISH" else {
            "LIVERMORE": 0xC9A84C,
            "PREMIUM":   0xE8921A,
            "ALERT":     0x2ECC71,
        }.get(tier, 0x2ECC71)

        contract_text = format_contracts_for_copy(contract, chain_map)
        ladder_strikes = chain_map.get("ladder_strikes", []) or []
        ladder_text = (
            f"✓ Detectada en strikes {'/'.join(str(s) for s in ladder_strikes[:3])}"
            if chain_map.get("has_ladder") else "No detectada"
        )
        repeated_text = (
            f"✓ {flow_count} transacciones acumuladas"
            if repeated_flow else "Flujo único"
        )
        leg_text = "SINGLE LEG ✓" if is_single_leg else "MULTI-LEG ⚠️"

        # ─── EMBED PRINCIPAL ─────────────────────────────────────────────────
        embed = discord.Embed(
            title=f"{dir_emoji} {dir_text} — {ticker} {category} | Score {score}/100 | {tier}",
            color=color,
            timestamp=datetime.now(NY_TZ)
        )

        embed.set_author(name=f"Livermore AI — {tier}", icon_url="")

        if contract:
            embed.add_field(
                name="Contrato (copiar)",
                value=f"`{contract_text}`\nNominal **{money_compact(nominal)}**",
                inline=False
            )

        embed.add_field(
            name="Señales activas",
            value=(
                f"• Valor nominal: **{money_compact(nominal)}** (threshold institucional)\n"
                f"• OI: **{oi_text()}**\n"
                f"• Tipo: **{leg_text}**\n"
                f"• Delta: **{delta_zone(delta)}**\n"
                f"• Escalera: **{ladder_text}**\n"
                f"• Flujo repetido: **{repeated_text}**\n"
                f"• Macro: **{macro_text()}**"
            ),
            inline=False
        )

        embed.add_field(
            name="Niveles",
            value=f"Entry: **{price(entry)}** | SL: **{price(sl)}** | TP1: **{price(tp1)}** | TP2: **{price(tp2)}**",
            inline=False
        )

        embed.add_field(
            name="Score breakdown",
            value=f"ICC: **{breakdown.get('icc', 0)}/35** | Dark Pool: **{breakdown.get('dark_pool', 0)}/30** | Flow: **{breakdown.get('options', 0)}/25** | Macro: **{breakdown.get('macro', 0)}/10**",
            inline=False
        )

        embed.set_footer(text=f"Sesión: {session} | Régimen: {regime} | ID: #{alert_id} | {now_et}")

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
                title=f"{dir_emoji} Señal detectada — {ticker} | Score: {score}/100 | Tier: ALERT",
                description=(
                    "Contrato y niveles disponibles para suscriptores. "
                    "Upgrade en whop.com/livermore-ai"
                ),
                color=0x2ECC71
            )
            teaser.set_footer(text=f"Livermore AI | {now_et}")
            try:
                await free_ch.send(embed=teaser)
            except Exception as e:
                logger.error(f"Error en free channel: {e}")

    # ─── WIN ANNOUNCEMENT ────────────────────────────────────────────────────
    async def send_victory(self, ticker: str, contract: str, entry: float,
                           exit_price: float, pnl_pct: float, alert_id: int = 0):
        if not _assert_contract_belongs(ticker, contract):
            return

        ch = self._get_channel(VICTORIES_CH)
        if not ch:
            return

        emoji = "🏆" if pnl_pct >= 50 else "✅"
        embed = discord.Embed(
            title=f"{emoji} WIN — {ticker}",
            color=0xD4A832,
            timestamp=datetime.now(NY_TZ)
        )
        contract_copy = format_contracts_for_copy(contract)
        embed.add_field(name="Contrato (copiar)", value=f"`{contract_copy}`", inline=False)
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
