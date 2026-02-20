import requests
import csv
import os
import base64
from datetime import datetime
import time
from urllib.parse import quote

# === CONFIGURACIÓN DE LA API DE OVERHEID.IO ===
APIKEY = os.getenv("API_KEY")  # API key de overheid.io
BASE_URL = "https://api.overheid.io/v3/openkvk"
HEADERS = {"ovio-api-key": APIKEY}

# GitHub config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "SamuelHoreca/horeca-netherlands-proyect-"
GITHUB_BRANCH = "main"

# === MODO TEST: limitar empresas capturadas (0 = sin límite) ===
MAX_EMPRESAS_TEST = 20


def traducir_nl_es(texto):
    """
    Traduce un texto del neerlandés al español usando la API gratuita de MyMemory.
    Devuelve el texto original si la traducción falla.
    """
    if not texto or not texto.strip():
        return texto
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": texto[:500],  # MyMemory limita a 500 chars por petición
            "langpair": "nl|es",
        }
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            traduccion = data.get("responseData", {}).get("translatedText", "")
            if traduccion and traduccion.upper() != texto.upper():
                return traduccion
    except Exception:
        pass
    return texto


def subir_archivo_github(ruta_local, ruta_repo):
    """
    Sube o actualiza un archivo en GitHub via API REST.
    ruta_local: path del archivo en el contenedor
    ruta_repo: path destino dentro del repositorio (ej: 'exports/empresas.csv')
    """
    if not GITHUB_TOKEN:
        print("\u26a0\ufe0f GITHUB_TOKEN no configurado, no se sube a GitHub")
        return

    with open(ruta_local, "rb") as f:
        contenido_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{ruta_repo}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    # Comprobar si el archivo ya existe para obtener su SHA (necesario para actualizar)
    resp = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH})
    sha = None
    if resp.status_code == 200:
        sha = resp.json().get("sha")

    # Preparar payload
    fecha = datetime.today().strftime("%Y-%m-%d")
    payload = {
        "message": f"CSV empresas Holanda {fecha}",
        "content": contenido_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha  # necesario para sobreescribir

    resp = requests.put(url, headers=headers, json=payload)
    if resp.status_code in (200, 201):
        download_url = resp.json()["content"]["download_url"]
        print(f"\u2705 CSV subido a GitHub: {download_url}")
    else:
        print(f"\u274c Error al subir a GitHub: {resp.status_code} - {resp.text}")


def buscar_empresas(ciudad, page=1, size=100):
    """
    Busca empresas filtrando por ciudad.
    """
    url = (
        f"{BASE_URL}"
        f"?filters[bezoeklocatie.plaats]={ciudad}"
        f"&fields[]=naam"
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
    """
    url = f"https://api.overheid.io{slug}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return None


def extraer_datos_empresa(item):
    """
    Extrae datos del item del listado y enriquece con perfil detallado.
    El sector/descripción se traduce del neerlandés al español.
    Genera un enlace a Google Maps basado en la dirección y ciudad.
    """
    kvk = item.get("kvknummer", "")
    nombre = item.get("naam", "")
    bezoek = item.get("bezoeklocatie") or {}
    ciudad = bezoek.get("plaats", "")
    calle = bezoek.get("straat", "")
    numero = bezoek.get("huisnummer", "")
    direccion_base = f"{calle} {numero}".strip()

    # Generar enlace Google Maps
    maps_url = ""
    if direccion_base and ciudad:
        query_maps = f"{direccion_base}, {ciudad}, Netherlands"
        maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(query_maps)}"

    sbi_list = item.get("sbi") or []
    sector = ", ".join(sbi_list)
    website = item.get("website", "")

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
            if not sector:
                sbi_list = perfil.get("sbi") or []
                sector = ", ".join(sbi_list)

    # Texto base del sector (descripción tiene prioridad sobre código SBI)
    sector_nl = descripcion if descripcion else sector

    # Traducir al español
    sector_es = traducir_nl_es(sector_nl) if sector_nl else ""

    return {
        "kvk_numero": kvk,
        "nombre": nombre,
        "ciudad": ciudad,
        "direccion": direccion_base,
        "google_maps": maps_url,  # Nueva columna
        "sector": sector_es,
        "website": website,
        "fecha_inicio": fecha_inicio,
        "fecha_captura": datetime.today().strftime("%Y-%m-%d"),
    }


def capturar_empresas_holanda():
    """Captura todas las empresas de las principales ciudades de Holanda."""
    ciudades = [
        "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven",
        "Groningen", "Tilburg", "Almere", "Breda", "Nijmegen",
        "Enschede", "Haarlem", "Arnhem", "Zaandam", "Amersfoort",
        "Apeldoorn", "'s-Hertogenbosch", "Hoofddorp", "Maastricht", "Leiden",
    ]

    if MAX_EMPRESAS_TEST > 0:
        print(f"\u26a0\ufe0f MODO TEST: limitando a {MAX_EMPRESAS_TEST} empresas en total")

    kvk_vistos = cargar_kvk_vistos()
    print(f"
\U0001f4cb KVK numbers ya vistos en ejecuciones anteriores: {len(kvk_vistos)}")

    nuevas_empresas = []
    nuevos_kvk = set()

    for ciudad in ciudades:
        # Salir del bucle de ciudades si ya alcanzamos el límite de test
        if MAX_EMPRESAS_TEST > 0 and len(nuevas_empresas) >= MAX_EMPRESAS_TEST:
            print(f"\u2705 L\u00edmite de prueba alcanzado ({MAX_EMPRESAS_TEST} empresas). Deteniendo b\u00fasqueda.")
            break

        print(f"
\U0001f50d Buscando empresas en {ciudad}...")
        page = 1
        size = 100
        encontradas_ciudad = 0
        saltadas_ciudad = 0

        while True:
            # Salir del bucle de páginas si ya alcanzamos el límite de test
            if MAX_EMPRESAS_TEST > 0 and len(nuevas_empresas) >= MAX_EMPRESAS_TEST:
                break

            datos = buscar_empresas(ciudad=ciudad, page=page, size=size)
            if not datos:
                break
            items = datos.get("_embedded", {}).get("bedrijf", [])
            if not items:
                print(f"  \u26a0\ufe0f Sin resultados en página {page}")
                break

            page_count = datos.get("pageCount", 1)
            print(f"  \U0001f4c4 Página {page}/{page_count} — {len(items)} empresas")

            for empresa in items:
                if MAX_EMPRESAS_TEST > 0 and len(nuevas_empresas) >= MAX_EMPRESAS_TEST:
                    break

                kvk = str(empresa.get("kvknummer", "")).strip()

                if kvk in kvk_vistos or kvk in nuevos_kvk:
                    saltadas_ciudad += 1
                    continue

                time.sleep(0.2)
                info = extraer_datos_empresa(empresa)
                nuevas_empresas.append(info)
                nuevos_kvk.add(kvk)
                encontradas_ciudad += 1
                print(f"  \u2705 {info['nombre']} ({kvk}) — {info['ciudad']}")

            if page >= page_count:
                break
            page += 1

        print(f"  \U0001f4ca {ciudad}: {encontradas_ciudad} nuevas, {saltadas_ciudad} ya vistas")

    # Actualizar el archivo de KVK vistos
    kvk_vistos.update(nuevos_kvk)
    guardar_kvk_vistos(kvk_vistos)
    print(f"
\U0001f4be Registro actualizado: {len(kvk_vistos)} KVK numbers en total")

    if nuevas_empresas:
        # Exportar a CSV
        fecha = datetime.today().strftime("%Y%m%d")
        nombre_archivo = f"empresas_holanda_{fecha}.csv"

        with open(nombre_archivo, "w", newline="", encoding="utf-8") as f:
            campos = [
                "kvk_numero", "nombre", "ciudad", "direccion", "google_maps",
                "sector", "website", "fecha_inicio", "fecha_captura",
            ]
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            writer.writerows(nuevas_empresas)
        print(f"\u2705 Exportadas {len(nuevas_empresas)} empresas \u2192 {nombre_archivo}")

        # Subir CSV a GitHub
        ruta_repo = f"exports/{nombre_archivo}"
        subir_archivo_github(nombre_archivo, ruta_repo)
    else:
        print("\u2139\ufe0f No hay empresas nuevas para exportar hoy.")

    return nombre_archivo


def cargar_kvk_vistos():
    SEEN_FILE = "seen_kvk.txt"
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())


def guardar_kvk_vistos(kvk_set):
    SEEN_FILE = "seen_kvk.txt"
    with open(SEEN_FILE, "w") as f:
        for kvk in kvk_set:
            f.write(kvk + "
")


if __name__ == "__main__":
    capturar_empresas_holanda()
