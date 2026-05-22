import os
import httpx
import pymysql
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# CONFIGURACION
UW_GEX_URL = "https://api.unusualwhales.com/api/stock/{ticker}/spot-exposures/strike"
UW_DARKPOOL_URL = "https://api.unusualwhales.com/api/darkpool/{ticker}/historical"
UW_HEADERS = {
    "Authorization": f"Bearer {os.getenv('UNUSUAL_WHALES_TOKEN', '')}",
    "UW-CLIENT-API-ID": os.getenv("UW_CLIENT_API_ID", "100001"),
}

DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "firm_intelligence_db",
    "port": 3306,
}


def obtener_whales_sin_auditar():
    """Extrae las ballenas capturadas que aun no han pasado por auditoria."""
    conexion = pymysql.connect(**DB_CONFIG)
    cursor = conexion.cursor(pymysql.cursors.DictCursor)

    sql = """
    SELECT w.id, w.ticker, w.strike, w.premium_value, w.contract_type
    FROM detected_whales w
    LEFT JOIN microstructure_audit a ON w.id = a.whale_id
    WHERE a.id IS NULL;
    """
    cursor.execute(sql)
    resultados = cursor.fetchall()

    cursor.close()
    conexion.close()
    return resultados


def analizar_gex_paredes(ticker):
    """Consulta Spot GEX en UW para localizar niveles maximos de soporte/resistencia gamma."""
    url = UW_GEX_URL.format(ticker=ticker.lower())
    try:
        with httpx.Client() as client:
            response = client.get(url, headers=UW_HEADERS, timeout=15)
            if response.status_code == 200:
                data = response.json().get("data", [])
                if not data:
                    return None, None

                # Ordenamos por gamma absoluta para encontrar los niveles institucionales mas fuertes.
                gex_ordenado = sorted(data, key=lambda x: abs(float(x.get("gamma_exposure", 0))), reverse=True)

                # Extraemos los dos strikes con mayor exposicion como paredes teoricas.
                pared_1 = float(gex_ordenado[0].get("strike", 0)) if len(gex_ordenado) > 0 else None
                pared_2 = float(gex_ordenado[1].get("strike", 0)) if len(gex_ordenado) > 1 else None

                return (
                    min(pared_1, pared_2) if pared_1 and pared_2 else pared_1,
                    max(pared_1, pared_2) if pared_1 and pared_2 else pared_1,
                )
            return None, None
    except Exception:
        return None, None


def auditar_dark_pools(ticker):
    """Verifica si hay actividad masiva registrada en dark pools para este ticker."""
    url = UW_DARKPOOL_URL.format(ticker=ticker.lower())
    try:
        with httpx.Client() as client:
            response = client.get(url, headers=UW_HEADERS, params={"limit": 5}, timeout=15)
            if response.status_code == 200:
                trades = response.json().get("data", [])
                # Si hay transacciones individuales que superen $1M, encendemos la alerta.
                for trade in trades:
                    if float(trade.get("dollar_value", 0)) > 1000000:
                        return 1
            return 0
    except Exception:
        return 0


def ejecutar_auditoria_microestructura():
    whales = obtener_whales_sin_auditar()
    if not whales:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Auditor de Microestructura: No hay ballenas nuevas pendientes de analizar en phpMyAdmin.")
        return

    print(f"Auditor de Microestructura: Analizando la arquitectura oculta de {len(whales)} transacciones...")

    conexion = pymysql.connect(**DB_CONFIG)
    cursor = conexion.cursor()

    sql_insertar = """
    INSERT INTO microstructure_audit (whale_id, spot_gex_support, spot_gex_resistance, dark_pool_accumulation, conviction_score)
    VALUES (%s, %s, %s, %s, %s)
    """

    for whale in whales:
        whale_id = whale["id"]
        ticker = whale["ticker"]
        premium = float(whale["premium_value"])

        # 1. Escaneo de zonas de friccion matematica de los Market Makers.
        soporte_gex, resistencia_gex = analizar_gex_paredes(ticker)

        # 2. Rastreo de huellas institucionales ocultas.
        dark_pool = auditar_dark_pools(ticker)

        # 3. Algoritmo de conviccion.
        score = 50
        if premium > 500000:
            score += 20
        if dark_pool == 1:
            score += 15
        if soporte_gex and resistencia_gex:
            score += 15

        score = min(score, 100)

        # Inyeccion directa a MySQL.
        cursor.execute(sql_insertar, (whale_id, soporte_gex, resistencia_gex, dark_pool, score))
        print(f"Ticker: {ticker} | GEX: [{soporte_gex} - {resistencia_gex}] | Dark Pool: {dark_pool} | Conviction Score: {score}/100")

    conexion.commit()
    cursor.close()
    conexion.close()
    print("Fase de auditoria microestructural completada y guardada con exito.")


if __name__ == "__main__":
    print("Departamento de Microestructura y Analisis Gamma Activado de forma Autonoma.")
    print("-------------------------------------------------------------------------")
    while True:
        ejecutar_auditoria_microestructura()
        # Escanea la base de datos cada 5 minutos buscando nuevos ingresos del catcher.
        print("Esperando nuevas alertas inyectadas por el escaner tactico (5 min)...")
        time.sleep(300)
