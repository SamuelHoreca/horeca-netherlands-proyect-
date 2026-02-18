import requests
import json
import csv
from datetime import datetime, timedelta
import time
import os

# === CONFIGURACIÓN DE LA API DE KVK ===
APIKEY = os.environ.get("API_KEY")

BASE_URL = "https://api.kvk.nl/api/v2/zoeken"

BASE_URL_PERFIL = "https://api.kvk.nl/api/v1/basisprofielen"

HEADERS = {
    "apikey": APIKEY
}

# === FUNCIONES PRINCIPALES ===

def buscar_empresas(ciudad=None, sbi_code=None, pagina=1, resultados_por_pagina=100):
    """Busca empresas en la API de KVK"""
    params = {
        "pagina": pagina,
        "resultatenPerPagina": resultados_por_pagina,
        "type": "hoofdvestiging"  # Solo sedes principales
    }
    
    if ciudad:
        params["plaats"] = ciudad
    if sbi_code:
        params["sbiCode"] = sbi_code
    
    response = requests.get(BASE_URL, headers=HEADERS, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

# === FUNCIÓN PARA OBTENER PERFIL DETALLADO ===

def obtener_perfil(kvk_numero):
    """Obtiene el perfil completo de una empresa por su KVK"""
    url = f"{BASE_URL_PERFIL}/{kvk_numero}"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        return response.json()
    return None

# === EXTRACCIÓN DE DATOS ===

def extraer_datos_empresa(empresa):
    """Extrae los datos clave de una empresa"""
    kvk = empresa.get("kvkNummer", "")
    nombre = empresa.get("naam", "")
    direccion = empresa.get("adres", {}).get("binnenlandsAdres", {})
    ciudad = direccion.get("plaats", "")
    calle = direccion.get("straatnaam", "")
    
    # === OBTENER PERFIL DETALLADO ===
    perfil = obtener_perfil(kvk)
    website = ""
    telefono = ""
    fecha_inicio = ""
    descripcion = ""
    
    if perfil:
        fecha_inicio = perfil.get("startdatum", "")
        
        # === OBTENER ACTIVIDAD SBI (SECTOR) ===
        sbi_actividades = perfil.get("sbiActiviteiten", [])
        if sbi_actividades:
            descripcion = sbi_actividades[0].get("sbiOmschrijving", "")
        
        # === WEB Y TELÉFONO SI ESTÁN DISPONIBLES ===
        website = perfil.get("websites", [""])[0] if perfil.get("websites") else ""
    
    return {
        "kvk_numero": kvk,
        "nombre": nombre,
        "ciudad": ciudad,
        "direccion": calle,
        "sector": descripcion,
        "website": website,
        "fecha_inicio": fecha_inicio,
        "fecha_captura": datetime.today().strftime("%Y-%m-%d")
    }

# === CAPTURA MASIVA DE EMPRESAS ===

def capturar_empresas_holanda():
    """Captura empresas de todos los Países Bajos"""    # === CIUDADES PRINCIPALES DE LOS PAÍSES BAJOS ===

    todas_empresas = []
    
    print(f"\n🔍 Buscando empresas en Países Bajos...")
    pagina = 1        
        while True:
            datos = buscar_empresas(ciudad=None, pagina=pagina)            
            if not datos or not datos.get("resultaten"):
                break
            
            for empresa in datos["resultaten"]:
                time.sleep(0.1)  # Respetar límite de 100 reqs/min
                info = extraer_datos_empresa(empresa)
                todas_empresas.append(info)
                print(f"✅ {info['nombre']} - {info['ciudad']}")
            
            total = datos.get("totaal", 0)
            if pagina * 100 >= total or pagina >= 50:  # Máx 5000 empresas totales                break
            
            pagina += 1
    
    # === EXPORTAR A CSV ===
    fecha = datetime.today().strftime("%Y%m%d")
    nombre_archivo = f"empresas_holanda_{fecha}.csv"
    
    with open(nombre_archivo, "w", newline="", encoding="utf-8") as f:
        campos = ["kvk_numero", "nombre", "ciudad", "direccion", "sector", "website", "fecha_inicio", "fecha_captura"]
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(todas_empresas)
    
    print(f"\n✅ Exportadas {len(todas_empresas)} empresas → {nombre_archivo}")
    return nombre_archivo

# === EJECUCIÓN ===
if __name__ == "__main__":
    capturar_empresas_holanda()

def filtrar_empresas_nuevas(empresas, dias=7):
    """Filtra empresas registradas en los últimos N días"""
    hoy = datetime.today()
    nuevas = []
    
    for e in empresas:
        if e["fecha_inicio"]:
            try:
                fecha = datetime.strptime(str(e["fecha_inicio"]), "%Y%m%d")
                if (hoy - fecha).days <= dias:
                    nuevas.append(e)
            except:
                pass
    
    return nuevas
