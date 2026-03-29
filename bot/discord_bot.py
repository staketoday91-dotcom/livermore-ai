"""
Livermore AI — Discord Bot
Handles alerts, motivational messages, tier gating, and daily reports
"""
import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, time
import asyncio
import random
import pytz

NY_TZ = pytz.timezone("America/New_York")

GUILD_ID          = int(os.getenv("DISCORD_GUILD_ID", "0"))
FREE_CHANNEL      = int(os.getenv("DISCORD_FREE_CHANNEL", "0"))
TIER1_CHANNEL     = int(os.getenv("DISCORD_TIER1_CHANNEL", "0"))
TIER2_CHANNEL     = int(os.getenv("DISCORD_TIER2_CHANNEL", "0"))
TIER3_CHANNEL     = int(os.getenv("DISCORD_TIER3_CHANNEL", "0"))
VICTORIES_CHANNEL = int(os.getenv("DISCORD_VICTORIES_CHANNEL", "0"))
MOTIVE_CHANNEL    = int(os.getenv("DISCORD_MOTIVATIONAL_CHANNEL", "0"))

ROLE_TIER1 = int(os.getenv("DISCORD_ROLE_TIER1", "0"))
ROLE_TIER2 = int(os.getenv("DISCORD_ROLE_TIER2", "0"))
ROLE_TIER3 = int(os.getenv("DISCORD_ROLE_TIER3", "0"))


MOTIVATIONAL_MESSAGES = [
    {
        "title": "El tape nunca miente",
        "body": "Livermore lo dijo hace 100 años y sigue siendo verdad hoy. No es lo que crees que va a pasar — es lo que el mercado *está* diciendo ahora mismo. El flujo institucional no tiene ego. No tiene miedo. Solo tiene intención. Aprende a leerlo.",
        "lesson": "El mercado es más sabio que cualquier opinión. Síguelo, no lo discutas."
    },
    {
        "title": "Paciencia es la habilidad más cara del trading",
        "body": "Druckenmiller pasó semanas esperando el setup correcto antes del trade de Soros contra la libra. No entró antes. No 'casi entró'. Esperó la confluencia perfecta y puso todo. El 80% del trading es no hacer nada.",
        "lesson": "Un trade al mes con el setup correcto vale más que 20 trades con prisa."
    },
    {
        "title": "El dark pool no habla — actúa",
        "body": "Cuando ves un print de $2M por encima del VWAP en pre-market, alguien que mueve millones ya tomó su decisión. No están en Twitter discutiendo niveles. Ya compraron. Tu trabajo es seguir la huella, no predecir.",
        "lesson": "Sigue el dinero real, no el ruido."
    },
    {
        "title": "Livermore perdió fortunas — y las recuperó",
        "body": "Jesse Livermore quebró cuatro veces y cada vez reconstruyó su fortuna. No porque tuviera suerte — porque entendía que el mercado es un juego de probabilidades, no de certezas. Una pérdida no es el fin. Es información.",
        "lesson": "Tu stop loss no es una derrota. Es el costo de operar con disciplina."
    },
    {
        "title": "El ICC te dice cuándo — el flujo te dice quién",
        "body": "El patrón ICC te muestra la estructura técnica. Pero cuando combinas eso con un dark pool cluster de $1.5M y un golden sweep de 3,000 contratos en el ask — eso ya no es análisis técnico. Eso es seguir a los que saben.",
        "lesson": "La confluencia de señales elimina la duda. Si el setup no confluye — no entras."
    },
    {
        "title": "La prima es el sueldo, la dirección es el bono",
        "body": "Los traders más consistentes no son los que atrapan el 10x. Son los que cobran prima cada mes cuando el mercado está lateral, y luego agarran el movimiento cuando el ICC confirma. Dos motores. Siempre trabajando.",
        "lesson": "En chop vendes prima. En tendencia sigues el flujo. El mercado siempre da algo."
    },
    {
        "title": "Un collar a tiempo vale más que un margin call",
        "body": "JPMorgan no corre el JHEQX por diversión. Lo corre porque saben que proteger las ganancias es tan importante como hacerlas. Si tu posición lleva 90 días en verde — ese verde ya te pertenece. Protégelo.",
        "lesson": "Las ganancias no realizadas pueden desaparecer. Un collar es un seguro de vida para tu trade."
    },
    {
        "title": "El pre-market es el tape más honesto del día",
        "body": "Sin opciones activas. Sin retail. Solo institucionales moviendo capital con intención pura. Cuando ves volumen 2x el día anterior en pre-market — alguien ya sabe algo. Livermore habría estado despierto a las 8am todos los días.",
        "lesson": "El pre-market es tu ventaja competitiva. La mayoría lo ignora."
    },
]

DAILY_MORNING_MESSAGES = [
    "Buenos días. El mercado abre en {mins} minutos. El sistema está escaneando {tickers} tickers. Que el tape te hable claro hoy.",
    "Apertura en {mins} minutos. Pre-market activity detectada en {hot_tickers}. El sistema está listo.",
    "Nuevo día. Nuevas oportunidades. El sistema ha procesado el overnight flow. Watchlist activa: {tickers} tickers bajo vigilancia.",
]


class LivermoreBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.scanner = None

    async def setup_hook(self):
        self.morning_message.start()
        self.pre_open_briefing.start()
        self.midday_report.start()
        self.close_report.start()
        self.evening_livermore.start()
        print("✓ Discord bot tasks started")

    async def on_ready(self):
        print(f"✓ Livermore Bot online as {self.user}")

    # ─── ALERT SENDER ────────────────────────────────────────
    async def send_alert(self, result: dict, alert_id: int):
        """Send formatted alert to appropriate tier channels"""
        channels = result.get("channels", [])
        score    = result["score"]
        ticker   = result["ticker"]

        # Determine which Discord channels to post to
        if 1 in channels:
            await self._post_alert_tier1(result, alert_id)
        if 2 in channels:
            await self._post_alert_tier2(result, alert_id)
        if 3 in channels:
            await self._post_alert_tier3(result, alert_id)

        # Always post teaser to free channel (delayed, no contract)
        await self._post_free_teaser(result)

    async def _post_free_teaser(self, result: dict):
        """Teaser for free channel — no contract details"""
        ch = self.get_channel(FREE_CHANNEL)
        if not ch:
            return

        score = result["score"]
        tier  = result["tier"]
        emoji = "🔶" if tier == "ALERT" else "🔥" if tier == "PREMIUM" else "⚡"

        embed = discord.Embed(
            title=f"{emoji} Señal detectada — {result['ticker']}",
            color=0xC9A84C,
        )
        embed.add_field(name="Score", value=f"**{score}/100**", inline=True)
        embed.add_field(name="Dirección", value=result["direction"], inline=True)
        embed.add_field(name="Régimen", value=result["regime"], inline=True)
        embed.add_field(
            name="Detalles completos",
            value="🔒 Contrato, niveles exactos y señal completa disponibles en Tier 1+\n[Acceder aquí](https://whop.com/livermore-ai)",
            inline=False
        )
        embed.set_footer(text=f"Livermore AI • {datetime.now(NY_TZ).strftime('%I:%M %p ET')}")
        await ch.send(embed=embed)

    async def _post_alert_tier1(self, result: dict, alert_id: int):
        """Full alert for Tier 1"""
        ch = self.get_channel(TIER1_CHANNEL)
        if not ch:
            return

        score = result["score"]
        color = 0x2ecc71 if score >= 90 else 0xC9A84C

        embed = discord.Embed(
            title=f"🎯 {result['ticker']} — Score {score}/100",
            description=f"**{result['reason'][:200]}**",
            color=color,
        )
        embed.add_field(name="Contrato", value=result.get("contract", "Stock"), inline=False)
        embed.add_field(name="Entrada", value=f"${result['entry']:.2f}", inline=True)
        embed.add_field(name="Stop Loss", value=f"${result['stop_loss']:.2f}", inline=True)
        embed.add_field(name="Target 1", value=f"${result['target1']:.2f}", inline=True)
        embed.add_field(name="Target 2", value=f"${result['target2']:.2f}", inline=True)
        embed.add_field(name="Sesión", value=result["session"], inline=True)
        embed.add_field(name="ICC Signal", value=result["icc_signal"], inline=True)

        score_text = (f"ICC: {result['score_breakdown']['icc']}/35 | "
                     f"DP: {result['score_breakdown']['dark_pool']}/30 | "
                     f"Flow: {result['score_breakdown']['options']}/25")
        embed.add_field(name="Score breakdown", value=score_text, inline=False)
        embed.set_footer(text=f"Alert #{alert_id} • {datetime.now(NY_TZ).strftime('%I:%M %p ET')}")
        await ch.send(embed=embed)

    async def _post_alert_tier2(self, result: dict, alert_id: int):
        """Enhanced alert for Tier 2 — adds pre/post market context"""
        ch = self.get_channel(TIER2_CHANNEL)
        if not ch:
            return

        embed = discord.Embed(
            title=f"⚡ {result['ticker']} — PREMIUM {result['score']}/100",
            color=0x9B59B6,
        )
        embed.add_field(name="Contrato", value=result.get("contract", "Stock"), inline=False)
        embed.add_field(name="Entrada", value=f"${result['entry']:.2f}", inline=True)
        embed.add_field(name="SL", value=f"${result['stop_loss']:.2f}", inline=True)
        embed.add_field(name="TP1 / TP2", value=f"${result['target1']:.2f} / ${result['target2']:.2f}", inline=True)
        if result.get("delta"):
            embed.add_field(name="Delta", value=f"{result['delta']:.2f}", inline=True)
        if result.get("premium"):
            embed.add_field(name="Prima", value=f"${result['premium']:.2f}", inline=True)
        embed.add_field(name="Señal", value=result["reason"][:300], inline=False)
        embed.set_footer(text=f"Alert #{alert_id} • Tier 2 • {datetime.now(NY_TZ).strftime('%I:%M %p ET')}")
        await ch.send(embed=embed)

    async def _post_alert_tier3(self, result: dict, alert_id: int):
        """VIP alert for Tier 3 — full detail + early delivery"""
        ch = self.get_channel(TIER3_CHANNEL)
        if not ch:
            return

        embed = discord.Embed(
            title=f"🏆 LIVERMORE SIGNAL — {result['ticker']} {result['score']}/100",
            description="**Score máximo — confluencia total detectada**",
            color=0xE74C3C,
        )
        embed.add_field(name="Contrato exacto", value=result.get("contract", "Stock directional"), inline=False)
        embed.add_field(name="Entrada", value=f"${result['entry']:.2f}", inline=True)
        embed.add_field(name="Stop Loss", value=f"${result['stop_loss']:.2f}", inline=True)
        embed.add_field(name="TP1", value=f"${result['target1']:.2f}", inline=True)
        embed.add_field(name="TP2", value=f"${result['target2']:.2f}", inline=True)
        if result.get("delta"):
            embed.add_field(name="Delta", value=f"{result['delta']:.2f}", inline=True)
        if result.get("expiration"):
            embed.add_field(name="Exp.", value=result["expiration"], inline=True)

        score_text = (f"ICC: {result['score_breakdown']['icc']}/35 | "
                     f"Dark Pool: {result['score_breakdown']['dark_pool']}/30 | "
                     f"Flow: {result['score_breakdown']['options']}/25 | "
                     f"Macro: {result['score_breakdown']['macro']}/10")
        embed.add_field(name="Score completo", value=score_text, inline=False)
        embed.add_field(name="Señal detectada", value=result["reason"][:400], inline=False)
        embed.set_footer(text=f"Alert #{alert_id} • Tier 3 VIP • {datetime.now(NY_TZ).strftime('%I:%M %p ET')}")
        await ch.send(embed=embed)

    # ─── VICTORY ANNOUNCEMENT ─────────────────────────────────
    async def announce_victory(self, ticker: str, pnl_pct: float, pnl_dollar: float, contract: str):
        """Post win to public victories channel"""
        ch = self.get_channel(VICTORIES_CHANNEL)
        if not ch:
            return

        embed = discord.Embed(
            title=f"✅ WIN — {ticker}",
            description=f"**+{pnl_pct:.1f}% | +${pnl_dollar:,.0f}**",
            color=0x2ECC71,
        )
        embed.add_field(name="Contrato", value=contract, inline=True)
        embed.add_field(name="Ganancia", value=f"**+${pnl_dollar:,.0f}**", inline=True)
        embed.add_field(
            name="Acceso completo",
            value="Los miembros Tier 1+ recibieron esta señal antes. [Únete aquí](https://whop.com/livermore-ai)",
            inline=False
        )
        embed.set_footer(text=f"Livermore AI • Sala de Victorias")
        await ch.send(embed=embed)

    # ─── SCHEDULED TASKS ──────────────────────────────────────

    @tasks.loop(time=time(7, 0, tzinfo=NY_TZ))
    async def morning_message(self):
        """7:00am — Good morning message"""
        ch = self.get_channel(MOTIVE_CHANNEL)
        if not ch:
            return

        now = datetime.now(NY_TZ)
        if now.weekday() >= 5:
            return

        embed = discord.Embed(
            title="Buenos días — El mercado abre en 2h30m",
            description="El sistema Livermore AI ha procesado el overnight flow y está listo para el día.",
            color=0xC9A84C,
        )
        embed.add_field(
            name="Qué vigilar hoy",
            value="Flujo pre-market activo en: **NVDA, AAPL, SPY**\nVIX estable. Sin eventos macro mayores.",
            inline=False
        )
        embed.add_field(
            name="Livermore dice:",
            value="*'La gran fortuna espera al trader que estudia sus movimientos antes de actuar. El mercado siempre avisa — la mayoría simplemente no escucha.'*",
            inline=False
        )
        embed.set_footer(text="Livermore AI • 7:00 AM ET")
        await ch.send(embed=embed)

    @tasks.loop(time=time(9, 15, tzinfo=NY_TZ))
    async def pre_open_briefing(self):
        """9:15am — Pre-market briefing"""
        ch = self.get_channel(TIER1_CHANNEL)
        if not ch:
            return

        now = datetime.now(NY_TZ)
        if now.weekday() >= 5:
            return

        embed = discord.Embed(
            title="Pre-apertura — 15 minutos",
            description="Resumen del pre-market para miembros Tier 1+",
            color=0x3B8FD4,
        )
        embed.add_field(name="Sesión pre-market", value="Revisando dark pool overnight...", inline=False)
        embed.add_field(name="Apertura NYSE", value="9:30 AM ET", inline=True)
        embed.add_field(name="Sistema", value="Activo — escaneando", inline=True)
        embed.set_footer(text="Livermore AI • Pre-Market Briefing")
        await ch.send(embed=embed)

    @tasks.loop(time=time(12, 0, tzinfo=NY_TZ))
    async def midday_report(self):
        """12:00pm — Midday performance update"""
        ch = self.get_channel(TIER1_CHANNEL)
        if not ch:
            return

        now = datetime.now(NY_TZ)
        if now.weekday() >= 5:
            return

        from core.models import Alert, SessionLocal
        try:
            db = SessionLocal()
            today = datetime.now(NY_TZ).date()
            alerts_today = db.query(Alert).filter(
                Alert.created_at >= datetime.combine(today, time(0, 0))
            ).all()
            db.close()

            wins = [a for a in alerts_today if a.status == "win"]
            open_alerts = [a for a in alerts_today if a.status == "open"]

            embed = discord.Embed(
                title="Reporte del mediodía",
                color=0xC9A84C,
            )
            embed.add_field(name="Alertas hoy", value=str(len(alerts_today)), inline=True)
            embed.add_field(name="Wins", value=str(len(wins)), inline=True)
            embed.add_field(name="En curso", value=str(len(open_alerts)), inline=True)

            if open_alerts:
                tickers = ", ".join(set(a.ticker for a in open_alerts[:5]))
                embed.add_field(name="Posiciones abiertas", value=tickers, inline=False)

            embed.set_footer(text="Livermore AI • Midday Report")
            await ch.send(embed=embed)
        except Exception as e:
            print(f"Midday report error: {e}")

    @tasks.loop(time=time(16, 30, tzinfo=NY_TZ))
    async def close_report(self):
        """4:30pm — End of day summary"""
        ch = self.get_channel(TIER1_CHANNEL)
        if not ch:
            return

        now = datetime.now(NY_TZ)
        if now.weekday() >= 5:
            return

        embed = discord.Embed(
            title="Cierre del día — Resumen",
            description="El mercado cerró. Revisando resultados del día.",
            color=0x2ECC71,
        )
        embed.add_field(
            name="Post-market",
            value="El sistema continúa monitoreando dark pool y futuros. Los prints de post-market son inteligencia para mañana.",
            inline=False
        )
        embed.add_field(
            name="Setup de mañana",
            value="Análisis overnight disponible a las 7:00 AM ET",
            inline=False
        )
        embed.set_footer(text="Livermore AI • EOD Report")
        await ch.send(embed=embed)

    @tasks.loop(time=time(20, 0, tzinfo=NY_TZ))
    async def evening_livermore(self):
        """8:00pm — Motivational message"""
        ch = self.get_channel(MOTIVE_CHANNEL)
        if not ch:
            return

        msg = random.choice(MOTIVATIONAL_MESSAGES)

        embed = discord.Embed(
            title=f"📖 {msg['title']}",
            description=msg["body"],
            color=0xC9A84C,
        )
        embed.add_field(name="Lección del día", value=msg["lesson"], inline=False)
        embed.set_footer(text="Livermore AI • Mensaje diario")
        await ch.send(embed=embed)

    # ─── COMMANDS ─────────────────────────────────────────────
    @commands.command(name="stats")
    async def stats_command(self, ctx):
        """Show system stats"""
        from core.models import Alert, SessionLocal
        try:
            db = SessionLocal()
            total  = db.query(Alert).count()
            wins   = db.query(Alert).filter(Alert.status == "win").count()
            losses = db.query(Alert).filter(Alert.status == "loss").count()
            open_  = db.query(Alert).filter(Alert.status == "open").count()
            db.close()

            wr = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0

            embed = discord.Embed(title="Livermore AI — Estadísticas", color=0xC9A84C)
            embed.add_field(name="Total alertas", value=str(total), inline=True)
            embed.add_field(name="Win rate", value=f"{wr}%", inline=True)
            embed.add_field(name="Abiertas", value=str(open_), inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @commands.command(name="scan")
    @commands.has_permissions(administrator=True)
    async def manual_scan(self, ctx):
        """Trigger manual scan"""
        await ctx.send("⚡ Iniciando scan manual...")
        if self.scanner:
            await self.scanner.run_scan()
            await ctx.send("✅ Scan completado")
        else:
            await ctx.send("❌ Scanner no inicializado")


def create_bot() -> LivermoreBot:
    return LivermoreBot()
