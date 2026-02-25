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
            "q": texto[:500],
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

    resp = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH})
    sha = None
    if resp.status_code == 200:
        sha = resp.json().get("sha")

    fecha = datetime.today().strftime("%Y-%m-%d")
    payload = {
        "message": f"CSV empresas Holanda {fecha}",
        "content": contenido_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

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
    Extrae datos del item y genera enlace de Google Maps.
    El sector se traduce del neerlandés al español.
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

    sector_nl = descripcion if descripcion else sector
    sector_es = traducir_nl_es(sector_nl) if sector_nl else ""

    return {
        "kvk_numero": kvk,
        "nombre": nombre,
        "ciudad": ciudad,
        "direccion": direccion_base,
        "google_maps": maps_url,
        "sector": sector_es,
        "website": website,
        "fecha_inicio": fecha_inicio,
        "fecha_captura": datetime.today().strftime("%Y-%m-%d"),
    }


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
            f.write(kvk + "\n")


def capturar_empresas_holanda():
    """Captura TODAS las empresas de las principales ciudades de Holanda."""
    ciudades = [
        "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven",
        "Groningen", "Tilburg", "Almere", "Breda", "Nijmegen",
        "Enschede", "Haarlem", "Arnhem", "Zaandam", "Amersfoort",
        "Apeldoorn", "'s-Hertogenbosch", "Hoofddorp", "Maastricht", "Leiden",
    ]

    kvk_vistos = cargar_kvk_vistos()
    print(f"\n📋 KVK numbers ya vistos: {len(kvk_vistos)}")

    nuevas_empresas = []
    nuevos_kvk = set()
    nombres_vistos = set()  # 🆕 Capa secundaria: (nombre_lower, ciudad_lower)

    for ciudad in ciudades:
        print(f"\n🔍 Buscando empresas en {ciudad}...")
        page = 1
        size = 100
        encontradas_ciudad = 0
        saltadas_ciudad = 0

        while True:
            datos = buscar_empresas(ciudad=ciudad, page=page, size=size)
            if not datos:
                break
            items = datos.get("_embedded", {}).get("bedrijf", [])
            if not items:
                print(f"  ⚠️ Sin resultados en página {page}")
                break

            page_count = datos.get("pageCount", 1)
            print(f"  📄 Página {page}/{page_count} — {len(items)} empresas")

            for empresa in items:
                kvk = str(empresa.get("kvknummer", "")).strip()

                # 🆕 Saltar si no tiene KVK (no se puede deduplicar de forma fiable)
                if not kvk:
                    saltadas_ciudad += 1
                    continue

                # Deduplicación primaria: por KVK
                if kvk in kvk_vistos or kvk in nuevos_kvk:
                    saltadas_ciudad += 1
                    continue

                # 🆕 Deduplicación secundaria: por nombre + ciudad
                bezoek = empresa.get("bezoeklocatie") or {}
                nombre_raw = str(empresa.get("naam", "")).strip().lower()
                ciudad_raw = str(bezoek.get("plaats", "")).strip().lower()
                clave_nombre = (nombre_raw, ciudad_raw)

                if clave_nombre in nombres_vistos:
                    saltadas_ciudad += 1
                    continue

                time.sleep(0.2)
                info = extraer_datos_empresa(empresa)

                nuevas_empresas.append(info)
                nuevos_kvk.add(kvk)
                nombres_vistos.add(clave_nombre)  # 🆕
                encontradas_ciudad += 1
                print(f"  ✅ {info['nombre']} ({kvk}) — {info['ciudad']}")

            if page >= page_count:
                break
            page += 1

        print(f"  📊 {ciudad}: {encontradas_ciudad} nuevas, {saltadas_ciudad} ya vistas/duplicadas")

    kvk_vistos.update(nuevos_kvk)
    guardar_kvk_vistos(kvk_vistos)
    print(f"\n💾 Registro actualizado: {len(kvk_vistos)} KVK numbers en total")

    if nuevas_empresas:
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
        print(f"✅ Exportadas {len(nuevas_empresas)} empresas → {nombre_archivo}")

        ruta_repo = f"exports/{nombre_archivo}"
        subir_archivo_github(nombre_archivo, ruta_repo)
    else:
        print("ℹ️ No hay empresas nuevas para exportar hoy.")

    return nombre_archivo


if __name__ == "__main__":
    capturar_empresas_holanda()
