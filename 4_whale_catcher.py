import os
import httpx
import pymysql
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# CONFIGURACION DE CREDENCIALES (UNUSUAL WHALES Y XAMPP)
UW_API_URL = "https://api.unusualwhales.com/api/option-trades/flow-alerts"
UW_HEADERS = {
    "Authorization": f"Bearer {os.getenv('UNUSUAL_WHALES_TOKEN', '')}",
    "UW-CLIENT-API-ID": os.getenv("UW_CLIENT_API_ID", "100001"),
}
API_LIMIT_BACKOFF_SECONDS = 3600

DB_CONFIG = {
    "host": "127.0.0.1",  # IP local estable para XAMPP
    "user": "root",
    "password": "",  # Si no conecta, prueba "root" o "admin"
    "database": "firm_intelligence_db",
    "port": 3306,  # Puerto por defecto de XAMPP
}


def conectar_base_datos():
    return pymysql.connect(**DB_CONFIG)


def capturar_flujo_real():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Escaner Tactico: Conectando a Unusual Whales...")

    # Parametros estrictos basados en tus reglas de oro
    params = {
        "min_premium": 100000,  # Filtro de ballena: Minimo $100k
        "size_greater_oi": True,  # REGLA DE ORO 1: El tamano de la orden debe superar el Open Interest
        "limit": 50,
    }

    try:
        with httpx.Client() as client:
            response = client.get(UW_API_URL, headers=UW_HEADERS, params=params, timeout=15)

            # Control de consumo de API (Monitoreo en cabeceras)
            req_hoy = response.headers.get("x-uw-daily-req-count", "N/A")
            req_limite = response.headers.get("x-uw-token-req-limit", "N/A")
            print(f"Consumo de API hoy: {req_hoy}/{req_limite} peticiones.")

            if response.status_code == 200:
                return response.json().get("data", [])
            elif response.status_code == 429:
                print("Limite diario de Unusual Whales agotado. El escaner hara pausa de 1 hora antes de reintentar.")
                time.sleep(API_LIMIT_BACKOFF_SECONDS)
                return []
            else:
                print(f"Error de API ({response.status_code}): {response.text}")
                return []
    except Exception as e:
        print(f"Error de conexion con los servidores de Unusual Whales: {e}")
        return []


def procesar_e_inyectar_alertas(alertas):
    if not alertas:
        print("No se detectaron rafagas institucionales nuevas que rompan el OI en esta lectura.")
        return

    conexion = conectar_base_datos()
    cursor = conexion.cursor()

    sql_insertar = """
    INSERT INTO detected_whales
    (ticker, contract_type, strike, expiry, contracts_volume, open_interest, premium_value, order_type, side, oi_broken)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    contador_nuevos = 0

    for trade in alertas:
        # Forzar filtro estricto de microestructura: Solo agresividad en el ASK
        side = trade.get("side", "").upper()
        if "ASK" not in side:
            continue  # Ignora BID o MID, buscamos la intencion de compra institucional pura

        ticker = trade.get("ticker_symbol")
        is_call = trade.get("is_call")
        tipo_contrato = "CALL" if is_call else "PUT"
        strike = trade.get("strike")
        expiry = trade.get("expiry")
        volume = trade.get("size")
        oi = trade.get("open_interest", 0)
        premium = trade.get("premium", 0)
        order_type = trade.get("execution_type", "Single Leg")

        # Validacion de seguridad para confirmar ruptura de Open Interest
        oi_broken = 1 if (volume > oi and oi > 0) else 0

        try:
            cursor.execute(sql_insertar, (
                ticker,
                tipo_contrato,
                strike,
                expiry,
                volume,
                oi,
                premium,
                order_type,
                side,
                oi_broken,
            ))
            contador_nuevos += 1
        except Exception:
            # Evita duplicados si ejecutas el script seguido
            continue

    conexion.commit()
    cursor.close()
    conexion.close()

    if contador_nuevos > 0:
        print(f"EXITO! Se registraron {contador_nuevos} rafagas institucionales agresivas en el ASK superando el OI.")
    else:
        print("Filtro completado: Las ordenes leidas eran del lado del BID o duplicadas.")


# BUCLE CONTINUO: El agente opera en segundo plano de manera autonoma
if __name__ == "__main__":
    print("Departamento de Caceria (Escaner Tactico) Iniciado de forma Autonoma.")
    print("-------------------------------------------------------------------------")
    while True:
        datos_flujo = capturar_flujo_real()
        procesar_e_inyectar_alertas(datos_flujo)

        # Pausa estrategica de 2 minutos para no quemar tus creditos de la API
        print("Esperando el proximo bloque de cinta institucional (2 min)...")
        time.sleep(120)
