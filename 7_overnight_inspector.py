import os
import httpx
import pymysql
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# CONFIGURACION
UW_BASE_URL = "https://api.unusualwhales.com/api/stock/{ticker}/option-chains"
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


def obtener_ballenas_pendientes():
    """Extrae de XAMPP las rafagas capturadas que aun no han sido validadas."""
    conexion = pymysql.connect(**DB_CONFIG)
    cursor = conexion.cursor(pymysql.cursors.DictCursor)

    # Buscamos alertas guardadas que no tengan registro en la tabla de validacion overnight.
    sql = """
    SELECT w.id, w.ticker, w.contract_type, w.strike, w.expiry, w.contracts_volume, w.open_interest
    FROM detected_whales w
    LEFT JOIN overnight_validation v ON w.id = v.whale_id
    WHERE v.id IS NULL AND DATE(w.capture_time) < CURDATE();
    """
    cursor.execute(sql)
    resultados = cursor.fetchall()

    cursor.close()
    conexion.close()
    return resultados


def consultar_nuevo_oi_api(ticker, expiry, strike, contract_type):
    """Consulta la cadena de opciones actual en UW para extraer el Open Interest actualizado."""
    url = UW_BASE_URL.format(ticker=ticker.lower())
    params = {"expiry": expiry}

    try:
        with httpx.Client() as client:
            response = client.get(url, headers=UW_HEADERS, params=params, timeout=15)
            if response.status_code == 200:
                cadenas = response.json().get("data", [])

                # Buscamos el contrato especifico en la cadena.
                for contrato in cadenas:
                    es_call = contrato.get("is_call")
                    tipo = "CALL" if es_call else "PUT"

                    # Convertimos a flotantes para evitar problemas de redondeo en el strike.
                    if float(contrato.get("strike")) == float(strike) and tipo == contract_type:
                        return contrato.get("open_interest", 0)
            return None
    except Exception as e:
        print(f"Error consultando OI en API para {ticker}: {e}")
        return None


def auditar_posiciones_overnight():
    ballenas = obtener_ballenas_pendientes()
    if not ballenas:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Inspector Overnight: No hay ballenas de dias anteriores pendientes de auditoria.")
        return

    print(f"Inspector Overnight: Iniciando auditoria para {len(ballenas)} contratos capturados ayer...")

    conexion = pymysql.connect(**DB_CONFIG)
    cursor = conexion.cursor()

    sql_insertar_status = """
    INSERT INTO overnight_validation (whale_id, verification_date, previous_oi, new_oi, oi_change_percent, verdict)
    VALUES (%s, CURDATE(), %s, %s, %s, %s)
    """

    for whale in ballenas:
        whale_id = whale["id"]
        ticker = whale["ticker"]
        expiry = whale["expiry"]
        strike = whale["strike"]
        tipo = whale["contract_type"]
        volumen_ayer = whale["contracts_volume"]
        oi_previo = whale["open_interest"]

        # Consultamos el OI fresco de esta manana.
        nuevo_oi = consultar_nuevo_oi_api(ticker, expiry, strike, tipo)

        if nuevo_oi is None:
            print(f"No se pudo obtener el OI actualizado para {ticker}. Se procesara en la siguiente ejecucion.")
            continue

        # Calcular el cambio absoluto y porcentual del Open Interest.
        cambio_oi_real = nuevo_oi - oi_previo
        cambio_porcentual = ((nuevo_oi - oi_previo) / oi_previo * 100) if oi_previo > 0 else 100.0

        # Regla de oro: si el OI absorbe una parte significativa del volumen, hay conviccion.
        if nuevo_oi > oi_previo and (cambio_oi_real >= (volumen_ayer * 0.7)):
            veredicto = "CONVICCION_CONFIRMADA"
            print(f"BALLENA CONFIRMADA: {ticker} {strike} {tipo} -> El OI subio de {oi_previo} a {nuevo_oi}. El dinero se quedo adentro.")
        elif nuevo_oi <= oi_previo:
            veredicto = "COBERTURA_CERRADA"
            print(f"TRAMPA DETECTADA: {ticker} {strike} {tipo} -> El OI no subio o disminuyo ({oi_previo} -> {nuevo_oi}). Posicion cerrada intradia.")
        else:
            veredicto = "FALSIFICACION"
            print(f"DUDA STRUCTURAL: {ticker} -> El OI subio levemente pero no justifica el volumen institucional de ayer.")

        # Guardamos el veredicto en la base de datos para uso de los futuros agentes.
        cursor.execute(sql_insertar_status, (whale_id, oi_previo, nuevo_oi, cambio_porcentual, veredicto))

    conexion.commit()
    cursor.close()
    conexion.close()
    print("Auditoria matutina de Open Interest finalizada y archivada en XAMPP.")


if __name__ == "__main__":
    print("Departamento de Verificacion e Inspeccion Overnight Iniciado.")
    print("-------------------------------------------------------------------------")
    auditar_posiciones_overnight()
