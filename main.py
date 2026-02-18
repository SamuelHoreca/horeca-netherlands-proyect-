import requests
import csv
from datetime import datetime
import time
import os

APIKEY = os.getenv("API_KEY")  # API key de overheid.io

BASE_URL = "https://api.overheid.io/v3/openkvk"
HEADERS = {"ovio-api-key": APIKEY}


def buscar_empresas(ciudad, page=1, size=100):
    """Busca empresas filtrando por ciudad exacta (bezoeklocatie.plaats)."""
    params = {
        "filters[bezoeklocatie.plaats]": ciudad,  # ✅ filtro exacto por ciudad
        "size": size,
        "page": page,
        # Solicitar campos extra en el listado para evitar llamadas extra de perfil
        "fields[]": ["bezoeklocatie.straat", "bezoeklocatie.huisnummer",
                     "bezoeklocatie.postcode", "sbi", "website"],
    }
    resp = requests.get(BASE_URL, headers=HEADERS, params=params)

    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"Error {resp.status_code}: {resp.text}")
        return None


def obtener_perfil(slug):
    """
    Obtiene el perfil completo de una empresa por su slug.
    slug proviene de _links.self.href, ej: '/v3/openkvk/hoofdvestiging-58488340-downsized'
    """
    url = f"https://api.overheid.io{slug}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return None


def extraer_datos_empresa(item):
    """
    item es un elemento de _embedded.bedrijf del listado v3.
    naam es string. bezoeklocatie es dict. sbi es lista de strings.
    """
    kvk = item.get("kvknummer", "")
    nombre = item.get("naam", "")  # ✅ es string, no lista en el listado

    bezoek = item.get("bezoeklocatie") or {}
    ciudad = bezoek.get("plaats", "")
    calle = bezoek.get("straat", "")
    numero = bezoek.get("huisnummer", "")
    direccion = f"{calle} {numero}".strip()

    # sector: lista de códigos SBI
    sbi_list = item.get("sbi") or []
    sector = ", ".join(sbi_list)

    # website del listado (si se pidió en fields[])
    website = item.get("website", "")

    # Para startdatum y activiteitomschrijving hace falta el perfil detallado.
    # Usamos el slug del _links.self.href para obtenerlo.
    fecha_inicio = ""
    descripcion = ""

    slug = (item.get("_links") or {}).get("self", {}).get("href", "")
    if slug:
        perfil = obtener_perfil(slug)
        if perfil:
            fecha_inicio = perfil.get("updated_at", "")
            # activiteitomschrijving es la descripción de actividad
            descripcion = perfil.get("activiteitomschrijving", "")
            # Si website no vino en el listado, lo cogemos del perfil
            if not website:
                website = perfil.get("website", "")

    return {
        "kvk_numero": kvk,
        "nombre": nombre,
        "ciudad": ciudad,
        "direccion": direccion,
        "sector": sector,
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

            # ✅ el array de resultados está en _embedded.bedrijf
            items = datos.get("_embedded", {}).get("bedrijf", [])
            if not items:
                break

            for empresa in items:
                time.sleep(0.2)  # ~5 reqs/s para no superar límites
                info = extraer_datos_empresa(empresa)
                todas_empresas.append(info)
                print(f"✅ {info['nombre']} - {info['ciudad']}")

            # paginación: pageCount está en la raíz de la respuesta
            page_count = datos.get("pageCount", 1)
            if page >= page_count:
                break

            page += 1

    # exportar a CSV
    fecha = datetime.today().strftime("%Y%m%d")
    nombre_archivo = f"empresas_holanda_{fecha}.csv"

    with open(nombre_archivo, "w", newline="", encoding="utf-8") as f:
        campos = ["kvk_numero", "nombre", "ciudad", "direccion",
                  "sector", "website", "fecha_inicio", "fecha_captura"]
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(todas_empresas)

    print(f"\n✅ Exportadas {len(todas_empresas)} empresas → {nombre_archivo}")
    return nombre_archivo


def filtrar_empresas_nuevas(empresas, dias=7):
    """Filtra empresas actualizadas en los últimos N días."""
    hoy = datetime.today()
    nuevas = []

    for e in empresas:
        if e["fecha_inicio"]:
            try:
                # updated_at viene en formato YYYY-MM-DD
                fecha = datetime.strptime(str(e["fecha_inicio"]), "%Y-%m-%d")
                if (hoy - fecha).days <= dias:
                    nuevas.append(e)
            except Exception:
                pass

    return nuevas


if __name__ == "__main__":
    capturar_empresas_holanda()
