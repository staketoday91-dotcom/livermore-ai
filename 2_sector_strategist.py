import yfinance as yf
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

# Canasta de ETFs institucionales mapeada en el manual.
SECTORES = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB"]


def analizar_rotacion_capital():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Estratega Sectorial: Midiendo el mapa de flujo de dinero...")

    resultados_sectores = []

    try:
        for ticker in SECTORES:
            etf = yf.Ticker(ticker)
            hist = etf.history(period="20d")

            # Calculamos rendimiento acumulado y posicion respecto a su precio inicial.
            precio_actual = hist["Close"].iloc[-1]
            precio_inicio = hist["Close"].iloc[0]
            rendimiento = ((precio_actual - precio_inicio) / precio_inicio) * 100

            if rendimiento > 2.0:
                status = "ACCUMULATION"
            elif rendimiento < -2.0:
                status = "DISTRIBUTION"
            else:
                status = "NEUTRAL"

            resultados_sectores.append({
                "ticker": ticker,
                "rendimiento": rendimiento,
                "status": status,
            })

        # Ordenamos sectores del mas fuerte al mas debil.
        resultados_sectores = sorted(resultados_sectores, key=lambda x: x["rendimiento"], reverse=True)

        # Guardamos el estatus de cada sector en XAMPP.
        conexion = pymysql.connect(**DB_CONFIG)
        cursor = conexion.cursor()

        sql = """
        INSERT INTO sector_rotation (check_date, sector_ticker, capital_flow_rank, status)
        VALUES (CURDATE(), %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        capital_flow_rank = VALUES(capital_flow_rank),
        status = VALUES(status);
        """

        print("\nRANKING DE FUERZA SECTORIAL DE HOY:")
        for rank, sec in enumerate(resultados_sectores, start=1):
            cursor.execute(sql, (sec["ticker"], rank, sec["status"]))
            print(f"Rank {rank}: {sec['ticker']} | Retorno 20D: {sec['rendimiento']:.2f}% | Estado: {sec['status']}")

        conexion.commit()
        cursor.close()
        conexion.close()
        print("\nMapa de rotacion sectorial actualizado y guardado en phpMyAdmin.")

    except Exception as e:
        print(f"Error en el Departamento de Rotacion: {e}")


if __name__ == "__main__":
    print("Estratega de Rotacion e Intermercado Iniciado.")
    print("-------------------------------------------------------------------------")
    while True:
        analizar_rotacion_capital()
        # Se ejecuta dos veces al dia: pre-mercado y post-mercado.
        print("Estratega en espera hasta el proximo corte de flujo (4 horas)...")
        time.sleep(14400)
