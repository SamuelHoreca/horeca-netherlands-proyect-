import requests
import csv
import os
import base64
from datetime import datetime
import time

# === CONFIGURACIÓN DE LA API DE OVERHEID.IO ===
APIKEY = os.getenv("API_KEY")  # API key de overheid.io
BASE_URL = "https://api.overheid.io/v3/openkvk"
HEADERS = {"ovio-api-key": APIKEY}

# Archivo persistente donde se guardan todos los KVK numbers ya vistos
SEEN_FILE = "seen_kvk.txt"

# GitHub config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "SamuelHoreca/horeca-netherlands-proyect-"
GITHUB_BRANCH = "main"


def cargar_kvk_vistos():
    """
    Carga el conjunto de KVK numbers ya procesados en ejecuciones anteriores.
    Si el archivo no existe, devuelve un conjunto vacío.
    """
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def guardar_kvk_vistos(kvk_set):
    """
    Sobreescribe el archivo de KVK vistos con el conjunto actualizado.
    """
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for kvk in sorted(kvk_set):
            f.write(kvk + "\n")


def subir_archivo_github(ruta_local, ruta_repo):
    """
    Sube o actualiza un archivo en GitHub via API REST.
    ruta_local: path del archivo en el contenedor
    ruta_repo: path destino dentro del repositorio (ej: 'exports/empresas.csv')
    """
    if not GITHUB_TOKEN:
        print("⚠️ GITHUB_TOKEN no configurado, no se sube a GitHub")
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
        print(f"✅ CSV subido a GitHub: {download_url}")
    else:
        print(f"❌ Error al subir a GitHub: {resp.status_code} - {resp.text}")


def buscar_empresas(ciudad, page=1, size=100):
    """
    Busca empresas filtrando por ciudad.
    Los corchetes en los parámetros deben enviarse como string literal
    porque requests los codifica mal con dicts normales.
    """
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
    """
    url = f"https://api.overheid.io{slug}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    return None


def extraer_datos_empresa(item):
    """
    Extrae datos del item del listado y enriquece con perfil detallado.
    """
    kvk = item.get("kvknummer", "")
    nombre = item.get("naam", "")
    bezoek = item.get("bezoeklocatie") or {}
    ciudad = bezoek.get("plaats", "")
    calle = bezoek.get("straat", "")
    numero = bezoek.get("huisnummer", "")
    direccion = f"{calle} {numero}".strip()
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
    """Captura empresas NUEVAS (no vistas antes) de las principales ciudades de Holanda."""
    ciudades = [
        "Amsterdam", "Rotterdam", "Den Haag", "Utrecht",
        "Eindhoven", "Groningen", "Tilburg", "Almere",
        "Breda", "Nijmegen", "Enschede", "Haarlem",
        "Arnhem", "Zaandam", "Amersfoort", "Apeldoorn",
        "'s-Hertogenbosch", "Hoofddorp", "Maastricht", "Leiden",
    ]

    kvk_vistos = cargar_kvk_vistos()
    print(f"\n📋 KVK numbers ya vistos en ejecuciones anteriores: {len(kvk_vistos)}")

    nuevas_empresas = []
    nuevos_kvk = set()

    for ciudad in ciudades:
        print(f"\n🔍 Buscando empresas nuevas en {ciudad}...")
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
            print(f"  📄 Página {page}/{page_count} — {len(items)} empresas encontradas")

            for empresa in items:
                kvk = str(empresa.get("kvknummer", "")).strip()

                if kvk in kvk_vistos or kvk in nuevos_kvk:
                    saltadas_ciudad += 1
                    continue

                time.sleep(0.2)
                info = extraer_datos_empresa(empresa)
                nuevas_empresas.append(info)
                nuevos_kvk.add(kvk)
                encontradas_ciudad += 1
                print(f"  ✅ {info['nombre']} ({kvk}) - {info['ciudad']}")

            if page >= page_count:
                break
            page += 1

        print(f"  📊 {ciudad}: {encontradas_ciudad} nuevas, {saltadas_ciudad} ya vistas")

    # Actualizar el archivo de KVK vistos
    kvk_vistos.update(nuevos_kvk)
    guardar_kvk_vistos(kvk_vistos)
    print(f"\n💾 Registro actualizado: {len(kvk_vistos)} KVK numbers en total")

    # Exportar a CSV
    fecha = datetime.today().strftime("%Y%m%d")
    nombre_archivo = f"empresas_holanda_{fecha}.csv"

    if nuevas_empresas:
        with open(nombre_archivo, "w", newline="", encoding="utf-8") as f:
            campos = [
                "kvk_numero", "nombre", "ciudad", "direccion",
                "sector", "website", "fecha_inicio", "fecha_captura",
            ]
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            writer.writerows(nuevas_empresas)
        print(f"✅ Exportadas {len(nuevas_empresas)} empresas nuevas → {nombre_archivo}")

        # Subir CSV a GitHub
        ruta_repo = f"exports/{nombre_archivo}"
        subir_archivo_github(nombre_archivo, ruta_repo)
    else:
        print("ℹ️ No hay empresas nuevas para exportar hoy.")

    return nombre_archivo


def filtrar_empresas_nuevas(empresas, dias=7):
    """Filtra empresas actualizadas en los últimos N días."""
    hoy = datetime.today()
    nuevas = []
    for e in empresas:
        if e["fecha_inicio"]:
            try:
                fecha = datetime.strptime(str(e["fecha_inicio"]), "%Y-%m-%d")
                if (hoy - fecha).days <= dias:
                    nuevas.append(e)
            except Exception:
                pass
    return nuevas


if __name__ == "__main__":
    capturar_empresas_holanda()
