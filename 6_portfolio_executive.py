import pymysql
import time
from datetime import datetime

# CONFIGURACION
DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "firm_intelligence_db",
    "port": 3306,
}

UMBRAL_CONVICCION = 65  # Score minimo del Auditor Gamma.


def obtener_contexto_empresa(ticker, conexion):
    """Consulta macro y sector para obtener las condiciones climaticas del mercado."""
    cursor = conexion.cursor(pymysql.cursors.DictCursor)

    # 1. Obtener el ultimo sesgo dictado por el Gobernador Macro.
    cursor.execute("SELECT market_bias FROM macro_status ORDER BY id DESC LIMIT 1;")
    macro = cursor.fetchone()
    bias = macro["market_bias"] if macro else "NEUTRAL"

    # 2. Mapear el ticker a su sector correspondiente.
    sector_map = {
        "NVDA": "XLK",
        "AAPL": "XLK",
        "MSFT": "XLK",
        "AMD": "XLK",
        "XOM": "XLE",
        "CVX": "XLE",
        "JPM": "XLF",
        "BAC": "XLF",
        "AMZN": "XLY",
        "TSLA": "XLY",
    }
    sector_ticker = sector_map.get(ticker.upper(), "XLK")

    # 3. Obtener el estado de salud de ese sector especifico hoy.
    sql_sector = "SELECT status FROM sector_rotation WHERE sector_ticker = %s ORDER BY id DESC LIMIT 1;"
    cursor.execute(sql_sector, (sector_ticker,))
    sector = cursor.fetchone()
    sector_status = sector["status"] if sector else "NEUTRAL"

    cursor.close()
    return bias, sector_ticker, sector_status


def obtener_auditorias_sin_plan(conexion):
    cursor = conexion.cursor(pymysql.cursors.DictCursor)
    sql = """
    SELECT a.id as audit_id, w.id as whale_id, w.ticker, w.contract_type, w.strike,
           w.premium_value, a.spot_gex_support, a.spot_gex_resistance, a.conviction_score
    FROM microstructure_audit a
    JOIN detected_whales w ON a.whale_id = w.id
    LEFT JOIN trading_plans p ON w.id = p.whale_id
    WHERE p.id IS NULL;
    """
    cursor.execute(sql)
    resultados = cursor.fetchall()
    cursor.close()
    return resultados


def evaluar_y_estructurar_comite():
    conexion = pymysql.connect(**DB_CONFIG)
    auditorias = obtener_auditorias_sin_plan(conexion)

    if not auditorias:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Comite de Inversion: Analizando cola de XAMPP... Sin ordenes pendientes.")
        conexion.close()
        return

    print(f"\nComite de Inversion: Evaluando {len(auditorias)} operaciones bajo el filtro corporativo integral...")
    cursor = conexion.cursor()

    sql_insertar_plan = """
    INSERT INTO trading_plans (whale_id, ticker, entry_zone, stop_loss, target_zone, execution_status)
    VALUES (%s, %s, %s, %s, %s, %s)
    """

    for trade in auditorias:
        whale_id = trade["whale_id"]
        ticker = trade["ticker"]
        tipo = trade["contract_type"]
        strike = float(trade["strike"])
        score = trade["conviction_score"]
        gex_soporte = float(trade["spot_gex_support"]) if trade["spot_gex_support"] else None
        gex_resistencia = float(trade["spot_gex_resistance"]) if trade["spot_gex_resistance"] else None

        # Cruce de contexto: macro y sector.
        macro_bias, sector_ticker, sector_status = obtener_contexto_empresa(ticker, conexion)

        # Reglas de control sistemico.
        motivo_bloqueo = None
        if macro_bias == "RISK_OFF":
            motivo_bloqueo = "BLOQUEO MACRO: Entorno global en RISK_OFF (Liquidez drenada)."
        elif sector_status == "DISTRIBUTION":
            motivo_bloqueo = f"BLOQUEO SECTORIAL: El capital esta huyendo de {sector_ticker} ({sector_status})."
        elif score < UMBRAL_CONVICCION:
            motivo_bloqueo = f"RECHAZO TACTICO: Score de microestructura {score}/100 por debajo del minimo."

        # Si una regla salta, invalidamos el plan antes de arriesgar capital.
        if motivo_bloqueo:
            print(f"Orden Archivada | {ticker} -> {motivo_bloqueo}")
            cursor.execute(
                sql_insertar_plan,
                (whale_id, ticker, "RECHAZADO_FILTRO_CORPORATIVO", 0.00, motivo_bloqueo, "INVALIDATED"),
            )
            continue

        # Luz verde: macro, sector y microestructura alineados.
        zona_entrada = f"Bloque de ASK original cerca de strike {strike}"
        stop_loss = gex_soporte * 0.98 if gex_soporte else strike * 0.95
        zona_objetivo = f"Pared Gamma en {gex_resistencia}" if gex_resistencia else f"Target OI en {strike * 1.05}"

        cursor.execute(sql_insertar_plan, (whale_id, ticker, zona_entrada, stop_loss, zona_objetivo, "PENDING"))

        print("\n=========================================================================")
        print(f"ALINEACION TOTAL: PLAN INSTITUCIONAL APROBADO PARA {ticker} ({tipo})")
        print(f"Contexto Global: Macro {macro_bias} | Sector {sector_ticker} en {sector_status}")
        print(f"Score Tecnico: {score}/100 (Estructura de Alta Conviccion)")
        print(f"Entrada Ejecutiva: {zona_entrada}")
        print(f"Stop Dinamico (Muro GEX): {stop_loss:.2f}")
        print(f"Objetivo Estrategico: {zona_objetivo}")
        print("=========================================================================")

    conexion.commit()
    cursor.close()
    conexion.close()


if __name__ == "__main__":
    print("Comite Estrategico de Inversion (Version Integrada de Alta Conviccion) Iniciado.")
    print("----------------------------------------------------------------------------------")
    while True:
        evaluar_y_estructurar_comite()
        time.sleep(300)
