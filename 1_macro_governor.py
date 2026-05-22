import yfinance as yf
import pymysql
import time
from datetime import datetime

# CONFIGURACION DE BASE DE DATOS
DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "firm_intelligence_db",
    "port": 3306,
}


def evaluar_entorno_macro():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Gobernador Macro: Analizando termometros de liquidez global...")

    try:
        # 1. Consultar tickers clave en Yahoo Finance.
        dxy = yf.Ticker("DX-Y.NYB")
        vix = yf.Ticker("^VIX")
        spy = yf.Ticker("SPY")

        # Obtener precios de cierre recientes.
        hist_dxy = dxy.history(period="5d")
        hist_vix = vix.history(period="1d")
        hist_spy = spy.history(period="50d")

        precio_dxy = hist_dxy["Close"].iloc[-1]
        precio_dxy_previo = hist_dxy["Close"].iloc[-2]
        precio_vix = hist_vix["Close"].iloc[-1]

        # Calcular media movil simple de 50 dias para el SPY.
        precio_spy = hist_spy["Close"].iloc[-1]
        sma_50_spy = hist_spy["Close"].mean()

        # Aplicacion de reglas de liquidez y sesgo.
        dxy_trend = "BULLISH" if precio_dxy > precio_dxy_previo else "BEARISH"

        puntos_riesgo = 0
        if precio_vix > 20:
            puntos_riesgo += 1
        if dxy_trend == "BULLISH":
            puntos_riesgo += 1
        if precio_spy < sma_50_spy:
            puntos_riesgo += 1

        if puntos_riesgo >= 2:
            market_bias = "RISK_OFF"
            liquidity_index = "LOW"
        elif puntos_riesgo == 1:
            market_bias = "NEUTRAL"
            liquidity_index = "MEDIUM"
        else:
            market_bias = "RISK_ON"
            liquidity_index = "HIGH"

        print(f"DXY: {precio_dxy:.2f} ({dxy_trend}) | VIX: {precio_vix:.2f} | SPY vs SMA50: {precio_spy:.2f}/{sma_50_spy:.2f}")
        print(f"Veredicto Macro Dictado: {market_bias} (Liquidez: {liquidity_index})")

        # Guardar o actualizar en la tabla macro_status de XAMPP.
        conexion = pymysql.connect(**DB_CONFIG)
        cursor = conexion.cursor()

        sql = """
        INSERT INTO macro_status (evaluation_date, fed_policy, liquidity_index, dxy_trend, market_bias)
        VALUES (CURDATE(), 'MONITORING', %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        liquidity_index = VALUES(liquidity_index),
        dxy_trend = VALUES(dxy_trend),
        market_bias = VALUES(market_bias);
        """

        cursor.execute(sql, (liquidity_index, dxy_trend, market_bias))
        conexion.commit()
        cursor.close()
        conexion.close()
        print("Veredicto macroeconomico archivado con exito en phpMyAdmin.")

    except Exception as e:
        print(f"Error en el Departamento Macro: {e}")


if __name__ == "__main__":
    print("Gobernador Macro del Portafolio Iniciado de forma Autonoma.")
    print("-------------------------------------------------------------------------")
    while True:
        evaluar_entorno_macro()
        # Se ejecuta cada hora para monitorear cambios durante la sesion.
        print("Gobernador en pausa. Siguiente reevaluacion de liquidez en 1 hora...")
        time.sleep(3600)
