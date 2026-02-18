import requests
import csv
from datetime import datetime
import time
import os

APIKEY = os.getenv("API_KEY")  # API key de overheid.io
BASE_URL = "https://api.overheid.io/v3/openkvk"
HEADERS = {"ovio-api-key": APIKEY}


def buscar_empresas(ciudad, page=1, size=100):
    """
    Busca empresas filtrando por ciudad.
    Los corchetes en los parámetros deben enviarse como string literal
    porque requests los codifica mal con dicts normales.
    """
    # Construimos la URL manualmente para que los [] lleguen correctamente
    url = (
        f"{BASE_URL}"
        f"?filters[bezoeklocatie.plaats]={ciudad}"
        f"&fields[]=bezoeklocatie.straat"
        f"&fields[]=bezoeklocatie.huisnummer"
        f"&fields[]=bezoeklocatie.postcode"
        f"&fields[]=bezoeklocatie.plaats"
        f"&fields[]=sbi"
        f"&fields[]=website"
        f"&size={size}"
        f"&page={page}"
    )
    resp = requests.get(url, headers=HEADERS)

    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"Error {resp.status_code}: {resp.text}")
        return None


def obtener_perfil(slug):
    """
    Obtiene el perfil completo de una empresa por su slug.
    slug viene de _links.self.href, ej: '/v3/openkvk/hoofdvestiging-58488340-downsized'
    """
    url = f"https://api.overheid.io{slug}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return None


def extraer_datos_empresa(item):
    """
    Extrae datos del item del listado y enriquece con perfil detallado.
    La respuesta del listado solo tiene: naam (str), kvknummer, _links.
    Los campos extra vienen si se pidieron con fields[].
    """
    kvk = item.get("kvknummer", "")
    nombre = item.get("naam", "")  # string en el listado

    bezoek = item.get("bezoeklocatie") or {}
    ciudad = bezoek.get("plaats", "")
    calle = bezoek.get("straat", "")
    numero = bezoek.get("huisnummer", "")
    direccion = f"{calle} {numero}".strip()

    sbi_list = item.get("sbi") or []
    sector = ", ".join(sbi_list)
    website = item.get("website", "")

    # Perfil detallado para obtener activiteitomschrijving, updated_at, etc.
    fecha_inicio = ""
    descripcion = ""
    slug = (item.get("_links") or {}).get("self", {}).get("href", "")
    if slug:
        perfil = obtener_perfil(slug)
        if perfil:
            fecha_inicio = perfil.get("updated_at", "")
            descripcion = perfil.get("activiteitomschrijving", "")
            if not website:
                website = perfil.get("website", "")
            # si sector tampoco llegó en el listado, tomarlo del perfil
            if not sector:
                sbi_list = perfil.get("sbi") or []
                sector = ", ".join(sbi_list)

    return {
        "kvk_numero": kvk,
        "nombre": nombre,
        "ciudad": ciudad,
        "direccion": direccion,
        "sector": descripcion or sector,
        "website": website,
        "fecha_inicio": fecha_inicio,
        "fecha_captura": datetime.today().strftime("%Y-%m-%d"),
    }


def capturar_empresas_holanda():
    """Captura empresas de las principales ciudades de los Países Bajos."""
    ciudades = [
        "Amsterdam", "Rotterdam", "Den Haag", "Utrecht",
        "Eindhoven", "Groningen", "Tilburg", "Almere",
    ]

    todas_empresas = []

    for ciudad in ciudades:
        print(f"\n🔍 Buscando empresas en {ciudad}...")
        page = 1
        size = 100

        while True:
            datos = buscar_empresas(ciudad=ciudad, page=page, size=size)
            if not datos:
                break

            # La respuesta siempre tiene _embedded.bedrijf
            items = datos.get("_embedded", {}).get("bedrijf", 
