"""
Canal Unusual Whales — respuestas privadas por usuario (ephemeral).
Solo el usuario que ejecuta el comando ve la respuesta.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands
import pytz

from core.uw_fetcher import UWFetcher

logger = logging.getLogger("livermore.discord.uw")
NY_TZ = pytz.timezone("America/New_York")

UW_CHANNEL_ID = int(os.getenv("DISCORD_UW_CHANNEL", "0") or 0)
COOLDOWN_SEC = float(os.getenv("DISCORD_UW_COOLDOWN_SEC", "12") or 12)


def _money(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n:.0f}" if n > 0 else "--"


def _only_uw_channel() -> Callable:
    if not UW_CHANNEL_ID:
        def passthrough(func):
            return func
        return passthrough

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id == UW_CHANNEL_ID:
            return True
        ch = interaction.client.get_channel(UW_CHANNEL_ID)
        name = getattr(ch, "name", str(UW_CHANNEL_ID))
        await interaction.response.send_message(
            f"Usa estos comandos solo en **#{name}**.",
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)


class UWPrivateCog(commands.Cog):
    """Comandos /uw con datos de Unusual Whales (visibles solo para ti)."""

    uw = app_commands.Group(
        name="uw",
        description="Consultas Unusual Whales (solo tú ves la respuesta)",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fetcher = UWFetcher()
        self._last_call: dict[int, float] = {}

    def _rate_limit(self, user_id: int) -> Optional[str]:
        now = time.monotonic()
        last = self._last_call.get(user_id, 0)
        if now - last < COOLDOWN_SEC:
            wait = int(COOLDOWN_SEC - (now - last)) + 1
            return f"Espera **{wait}s** antes de otra consulta (límite API UW)."
        self._last_call[user_id] = now
        return None

    async def _defer_ephemeral(self, interaction: discord.Interaction) -> Optional[str]:
        if interaction.response.is_done():
            return None
        blocked = self._rate_limit(interaction.user.id)
        if blocked:
            await interaction.response.send_message(blocked, ephemeral=True)
            return blocked
        await interaction.response.defer(ephemeral=True, thinking=True)
        return None

    @uw.command(name="flow", description="Flujo de opciones reciente para un ticker")
    @app_commands.describe(ticker="Símbolo, ej. SPY, NVDA, TSLA")
    @_only_uw_channel()
    async def uw_flow(self, interaction: discord.Interaction, ticker: str):
        if await self._defer_ephemeral(interaction):
            return
        ticker = ticker.upper().strip()[:12]
        try:
            rows = await self.fetcher.get_ticker_flow(ticker)
        except Exception as e:
            logger.exception("uw flow %s", ticker)
            await interaction.followup.send(
                f"Error consultando UW: `{type(e).__name__}`",
                ephemeral=True,
            )
            return

        if not rows:
            await interaction.followup.send(
                f"Sin flujo reciente para **{ticker}** en UW.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"UW Flow — {ticker}",
            color=0x3498DB,
            timestamp=datetime.now(NY_TZ),
        )
        lines = []
        for row in rows[:6]:
            nominal = row.get("nominal_value") or row.get("accumulated_nominal") or 0
            contract = row.get("option_chain") or row.get("option_symbol") or "—"
            ask = row.get("ask_side_pct") or row.get("total_ask_side_pct")
            side = f"ask {float(ask):.0f}%" if ask is not None else "—"
            lines.append(f"• **{_money(nominal)}** `{contract}` ({side})")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Solo visible para {interaction.user.display_name} · Livermore × UW")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @uw.command(name="alerts", description="Top alertas institucionales del mercado")
    @_only_uw_channel()
    async def uw_alerts(self, interaction: discord.Interaction):
        if await self._defer_ephemeral(interaction):
            return
        try:
            rows = await self.fetcher.get_flow_alerts(min_premium=250_000)
        except Exception as e:
            logger.exception("uw alerts")
            await interaction.followup.send(
                f"Error consultando UW: `{type(e).__name__}`",
                ephemeral=True,
            )
            return

        if not rows:
            await interaction.followup.send("Sin alertas de flujo ahora.", ephemeral=True)
            return

        embed = discord.Embed(
            title="UW Flow Alerts",
            color=0x9B59B6,
            timestamp=datetime.now(NY_TZ),
        )
        lines = []
        for row in rows[:8]:
            t = (row.get("ticker") or "?").upper()
            nominal = row.get("nominal_value") or 0
            lines.append(f"• **{t}** — {_money(nominal)}")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Solo visible para {interaction.user.display_name} · Livermore × UW")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @uw.command(name="darkpool", description="Dark pool reciente de un ticker")
    @app_commands.describe(ticker="Símbolo, ej. AAPL")
    @_only_uw_channel()
    async def uw_darkpool(self, interaction: discord.Interaction, ticker: str):
        if await self._defer_ephemeral(interaction):
            return
        ticker = ticker.upper().strip()[:12]
        try:
            rows = await self.fetcher.get_dark_pool(ticker)
        except Exception as e:
            logger.exception("uw darkpool %s", ticker)
            await interaction.followup.send(
                f"Error consultando UW: `{type(e).__name__}`",
                ephemeral=True,
            )
            return

        if not rows:
            await interaction.followup.send(
                f"Sin dark pool reciente para **{ticker}**.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"UW Dark Pool — {ticker}",
            color=0x2C3E50,
            timestamp=datetime.now(NY_TZ),
        )
        lines = []
        for row in rows[:6]:
            size = row.get("size") or row.get("volume") or row.get("qty")
            price = row.get("price") or row.get("avg_price")
            ts = (row.get("created_at") or row.get("timestamp") or "")[:16]
            lines.append(f"• **{size or '?'}** @ **{price or '?'}** `{ts}`")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Solo visible para {interaction.user.display_name} · Livermore × UW")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @uw.command(name="tide", description="Sentimiento agregado (market tide)")
    @_only_uw_channel()
    async def uw_tide(self, interaction: discord.Interaction):
        if await self._defer_ephemeral(interaction):
            return
        try:
            tide = await self.fetcher.get_market_tide()
        except Exception as e:
            logger.exception("uw tide")
            await interaction.followup.send(
                f"Error consultando UW: `{type(e).__name__}`",
                ephemeral=True,
            )
            return

        if not tide:
            await interaction.followup.send("Market tide no disponible.", ephemeral=True)
            return

        embed = discord.Embed(
            title="UW Market Tide",
            color=0x1ABC9C,
            timestamp=datetime.now(NY_TZ),
        )
        for key, val in list(tide.items())[:12]:
            if isinstance(val, (dict, list)):
                continue
            embed.add_field(name=str(key).replace("_", " ").title()[:25], value=str(val)[:200], inline=True)
        embed.set_footer(text=f"Solo visible para {interaction.user.display_name} · Livermore × UW")
        await interaction.followup.send(embed=embed, ephemeral=True)
