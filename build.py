"""Arma la web estática del portal Ramacontable.

Lee las notas de la carpeta notas/ (un .json por nota) y genera en sitio/:
portada, una página por sección y una página por nota.
Las claves públicas de Supabase se toman de las variables de entorno
SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY (en GitHub vienen de los Secrets).
"""
import unicodedata
import html, json, os, re, shutil, glob, datetime, urllib.request, urllib.parse

RAIZ = os.path.dirname(os.path.abspath(__file__))
VERSION = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M")  # evita que el navegador muestre archivos viejos
SALIDA = os.path.join(RAIZ, "sitio")

TITULO_SECCION = {   # título para Google de cada sección (el menú sigue diciendo "Sueldos", "Impuestos"...)
    "sueldos": "Novedades de sueldos: paritarias, escalas y aguinaldo",
    "impuestos": "Novedades de impuestos: ARCA, monotributo y Ganancias",
    "profesion": "Novedades de la profesión contable",
}
SECCIONES = {
    "sueldos": "Sueldos",
    "impuestos": "Impuestos",
    "profesion": "Profesión",
}
REDES = {
    "Instagram": "https://www.instagram.com/ramacontable",
    "YouTube": "https://www.youtube.com/@ramacontable",
    "TikTok": "https://www.tiktok.com/@ramacontable",
}
MAIL = "ramacontable@gmail.com"
MENU = {"sueldos": "Sueldos", "impuestos": "Impuestos", "guias": "Guías", "datos-al-dia": "Datos del día"}
RAMAS_GUIAS = {"sueldos": "Guías de sueldos", "impuestos": "Guías de impuestos", "profesion": "Guías contables y de la profesión"}
GRUPOS_GUIAS = {"sueldos": "Guías de sueldos", "impuestos": "Guías de impuestos", "contables": "Guías contables",
                "tramites": "Sociedades y trámites", "otras": "Otras guías"}
IMPUESTOS = [
    ("ganancias", "Ganancias", ["ganancias", "siradig", "cuarta categoria"], ["ganancias-cuarta-categoria", "siradig", "ganancias-personas-humanas", "ganancias-sociedades"]),
    ("iva", "IVA", ["iva", "valor agregado"], ["iva"]),
    ("monotributo", "Monotributo", ["monotribut", "regimen simplificado"], ["monotributo"]),
    ("autonomos", "Autónomos", ["autonomo"], ["autonomos"]),
    ("bienes-personales", "Bienes Personales", ["bienes personales"], ["bienes-personales"]),
    ("ingresos-brutos", "Ingresos Brutos", ["ingresos brutos", "arba", "agip", "convenio multilateral"], ["ingresos-brutos-arba", "convenio-multilateral"]),
    ("retenciones", "Retenciones y percepciones", ["retencion", "percepcion"], ["retenciones-percepciones"]),
    ("planes-de-pago", "Planes de pago y moratorias", ["plan de pago", "planes de pago", "moratoria", "facilidades de pago"], ["planes-de-pago-arca"]),
]
_N = lambda t: "".join(ch for ch in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(ch) != "Mn")
es_guia = lambda n: n.get("tipo") == "guia"


def sitio_url():
    try:
        u = json.load(open(os.path.join(RAIZ, "config.json"), encoding="utf-8")).get("sitio_url", "")
    except Exception:
        u = ""
    return (u or "https://vramiroventura.github.io/ramacontable-portal/").rstrip("/") + "/"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

e = html.escape
LOGO_SVG = '<svg class="isotipo" viewBox="0 0 48 48" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M24 44V24"/><path d="M24 31 12 19v-6"/><path d="M24 31l12-12v-6"/><path d="M24 24V9"/></g><g fill="#A8844F"><circle cx="12" cy="10" r="3.6"/><circle cx="24" cy="6.5" r="3.6"/><circle cx="36" cy="10" r="3.6"/></g></svg>'


def fecha_larga(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def cargar_aportes():
    """Trae los paso a paso publicados para que Google los lea (la página los vuelve a cargar al abrirse)."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key:
        return {}
    try:
        req = urllib.request.Request(
            url + "/rest/v1/pasos?select=nota,titulo,porque,texto_pdf,contenido,perfiles(nombre)&order=creado.asc",
            headers={"apikey": key, "Authorization": "Bearer " + key})
        datos = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as ex:
        print("Aviso: no se pudieron leer los aportes:", ex)
        return {}
    por_nota = {}
    for p in datos:
        por_nota.setdefault(p["nota"], []).append(p)
    return por_nota


def texto_plano(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def pasos_estaticos(lista):
    if not lista:
        return ""
    items = []
    for p in lista:
        autor = (p.get("perfiles") or {}).get("nombre", "")
        cuerpo = texto_plano(p.get("contenido"))[:3000]
        extra = (p.get("texto_pdf") or "")[:3000]
        items.append(f'<div class="aporte"><p class="autor"><b>{e(autor)}</b></p><h4>{e(p["titulo"])}</h4>'
                     f'<p>{e(cuerpo)}</p><p>{e(extra)}</p><div class="dato porque-caja"><b>¿Por qué se hace así? </b>{e(p["porque"])}</div></div>')
    return "".join(items)


VENC = []
PORTADAS_OK = set()  # notas que ya tienen su imagen para compartir  # filas de la tabla vencimientos (la arma la fábrica a diario)


def cargar_vencimientos():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key:
        return []
    try:
        req = urllib.request.Request(url + "/rest/v1/vencimientos?select=*&order=mes.asc", headers={"apikey": key, "Authorization": "Bearer " + key})
        return json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as ex:
        print("Aviso: no se pudieron leer los vencimientos:", ex)
        return []


def proximos_vencimientos(n=None):
    hoy = datetime.date.today().isoformat()
    todos = [x for fila in VENC for x in (fila.get("items") or []) if x.get("fecha", "") >= hoy]
    todos.sort(key=lambda x: (x["fecha"], x.get("concepto", "")))
    return todos[:n] if n else todos


def fecha_corta(iso):
    return f"{iso[8:10]}/{iso[5:7]}"


# Series oficiales del BCRA (API pública de estadísticas, v4.0). Se bajan en cada publicación de la web.
SERIES_BCRA = {
    "cer": (30, "CER (Coeficiente de Estabilización de Referencia)", "indice"),
    "uva": (31, "UVA (Unidad de Valor Adquisitivo)", "indice"),
    "icl": (40, "ICL (Índice para Contratos de Locación)", "indice"),
    "dolar_minorista": (4, "Dólar oficial minorista (promedio vendedor)", "indice"),
    "dolar_mayorista": (5, "Dólar mayorista de referencia (Com. A 3500)", "indice"),
    "ipc": (27, "Inflación mensual (IPC)", "mensual"),
    "justicia": (43, "Tasa pasiva uso de justicia (Com. P 14.290)", "acumulada"),
    "badlar": (7, "Tasa BADLAR bancos privados", "tna"),
    "tamar": (44, "Tasa TAMAR bancos privados", "tna"),
    "plazo_fijo": (12, "Tasa de plazo fijo a 30 días", "tna"),
    "personales": (14, "Tasa de préstamos personales", "tna"),
}


def respaldo_publicado(nombre):
    """Copia de datos/<nombre> que ya está publicada en la web. Se usa si una API no responde, para no borrar páginas."""
    import ssl
    try:
        req = urllib.request.Request(sitio_url() + "datos/" + nombre, headers={"User-Agent": "ramacontable-build"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()))
        except ssl.SSLError:
            import certifi
            return json.load(urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context(cafile=certifi.where())))
    except Exception as ex:
        print(f"Aviso: tampoco hay respaldo publicado de {nombre}:", ex)
        return None


def bajar_series(destino):
    """Escribe sitio/datos/serie-<clave>.json con {f: fechas, v: valores}. Si el BCRA no responde, esa serie queda sin archivo."""
    import ssl
    os.makedirs(destino, exist_ok=True)
    resumen = {}
    desde = "2016-01-01"
    for clave, (idv, nombre, tipo) in SERIES_BCRA.items():
        puntos = {}
        try:
            offset = 0
            while True:
                url = f"https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{idv}?desde={desde}&limit=3000&offset={offset}"
                req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ramacontable-build"})
                try:
                    datos = json.load(urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()))
                except ssl.SSLError:
                    # si el sistema no reconoce el certificado del BCRA, se prueba con la lista de certificados de certifi
                    import certifi
                    datos = json.load(urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context(cafile=certifi.where())))
                det = (datos.get("results") or [{}])[0].get("detalle") or []
                for d in det:
                    puntos[d["fecha"][:10]] = d["valor"]
                if len(det) < 3000:
                    break
                offset += 3000
        except Exception as ex:
            print(f"Aviso: no se pudo bajar la serie {clave} del BCRA:", ex)
        if not puntos:
            viejo = respaldo_publicado(f"serie-{clave}.json")
            if viejo and viejo.get("f"):
                print(f"Aviso: uso la serie {clave} ya publicada (hasta {viejo['f'][-1]})")
                puntos = dict(zip(viejo["f"], viejo["v"]))
            else:
                continue
        fechas = sorted(puntos)
        json.dump({"nombre": nombre, "tipo": tipo, "f": fechas, "v": [puntos[x] for x in fechas]},
                  open(os.path.join(destino, f"serie-{clave}.json"), "w", encoding="utf-8"), separators=(",", ":"))
        resumen[clave] = {"nombre": nombre, "tipo": tipo, "desde": fechas[0], "hasta": fechas[-1], "ultimo": puntos[fechas[-1]]}
    json.dump(resumen, open(os.path.join(destino, "series.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return resumen


def escribir_feriados(destino):
    """Lista de feriados y días no laborables (página de feriados + los que confirmó la fábrica) para contar días hábiles."""
    os.makedirs(destino, exist_ok=True)
    fechas = set(re.findall(r'data-f="(\d{4}-\d{2}-\d{2})"', open(os.path.join(RAIZ, "paginas", "feriados.html"), encoding="utf-8").read()))
    for fila in VENC:
        for x in fila.get("feriados") or []:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", str(x.get("fecha", ""))):
                fechas.add(x["fecha"])
    for ruta in glob.glob(os.path.join(RAIZ, "feriados", "*.json")):
        for x in json.load(open(ruta, encoding="utf-8")).get("feriados", []):
            fechas.add(x["fecha"])
    anios = sorted({f[:4] for f in fechas})
    json.dump({"fechas": sorted(fechas), "anios": anios}, open(os.path.join(destino, "feriados.json"), "w", encoding="utf-8"))


def notas_supabase():
    """Notas publicadas en Supabase (las escribe la fábrica y las edita el administrador)."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        req = urllib.request.Request(url + "/rest/v1/notas?select=*&estado=eq.publicada&order=fecha.desc&limit=2000",
                                     headers={"apikey": key, "Authorization": "Bearer " + key})
        # «ajuste-…»: propuestas de la fábrica para corregir guías fáciles; nunca se muestran como nota
        return [n for n in json.load(urllib.request.urlopen(req, timeout=30)) if not str(n.get("slug", "")).startswith("ajuste-")]
    except Exception as ex:
        print("Aviso: no se pudieron leer las notas de Supabase:", ex)
        return None


_NO_PUBLICADAS = None


def no_publicada(slug):
    """True si la nota existe en Supabase pero no está publicada (borrada o en revisión)."""
    global _NO_PUBLICADAS
    if _NO_PUBLICADAS is None:
        _NO_PUBLICADAS = set()
        url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
        if url and key:
            try:
                req = urllib.request.Request(url + "/rest/v1/rpc/slugs_no_publicados", data=b"{}", method="POST",
                                             headers={"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"})
                _NO_PUBLICADAS = set(json.load(urllib.request.urlopen(req, timeout=30)) or [])
            except Exception as ex:
                print("Aviso: no se pudo consultar notas retiradas:", ex)
    return slug in _NO_PUBLICADAS


def cargar_notas():
    locales = {}
    for ruta in glob.glob(os.path.join(RAIZ, "notas", "*.json")):
        with open(ruta, encoding="utf-8") as f:
            n = json.load(f)
        locales[n["slug"]] = n
    remotas = notas_supabase()
    if remotas is None and os.environ.get("SUPABASE_URL", "").strip() and os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip():
        # Supabase configurado pero no responde (p. ej. error 522): si se publicara igual, la web quedaría solo con las notas
        # del repo y se borrarían todas las demás. Se corta acá: sigue online la última versión buena y se reintenta en la próxima vuelta.
        raise SystemExit("Supabase no responde: no se publica esta vez para no borrar las notas de la web. Se reintenta en la próxima vuelta.")
    if remotas is None:
        notas = list(locales.values())
    else:
        # Supabase manda: si una nota se editó o se borró allá, vale lo de allá
        todas = {r["slug"]: r for r in remotas}
        for s, n in locales.items():
            if s in todas and n.get("preguntas") and not todas[s].get("preguntas"):
                todas[s]["preguntas"] = n["preguntas"]  # la copia de la base se cargó antes de sumarle las preguntas
            if s not in todas and not no_publicada(s):
                todas[s] = n
        notas = list(todas.values())
    for n in notas:
        if n.get("seccion") not in SECCIONES:   # el portal no tiene sección Economía: lo que quede así va a Profesión
            n["seccion"] = "profesion"
    notas.sort(key=lambda n: (str(n["fecha"]), n["slug"]), reverse=True)
    return notas


def _escala_ok(esc):
    """Una escala sirve si su tabla tiene al menos dos filas con importes."""
    t = (esc or {}).get("tabla") if isinstance(esc, dict) else None
    return bool(t) and sum(1 for f in t[1:] if isinstance(f, list) and any(re.search(r"\d", str(x)) for x in f[1:])) >= 2


def _fin_escala(esc):
    """Último mes que cubre una escala (año, mes): por los encabezados de la tabla o por el texto del período. (0, 0) si no se sabe."""
    if not isinstance(esc, dict):
        return (0, 0)
    t = esc.get("tabla") or []
    meses_cab = [_mes_col(h) for h in (t[0] if t else [])]
    meses_cab = [x for x in meses_cab if x]
    per = str(esc.get("periodo") or "").lower()
    anios = [int(a) for a in re.findall(r"20\d{2}", per)]
    meses_per = [i + 1 for pos, i in sorted((per.rfind(n), i) for i, n in enumerate(MESES) if n in per)]
    fin_per = (anios[-1], meses_per[-1]) if anios and meses_per else (0, 0)
    return max(meses_cab + [fin_per])


def _ini_escala(esc):
    """Primer mes que cubre una escala (año, mes), por encabezados o período. (9999, 12) si no se sabe."""
    if not isinstance(esc, dict):
        return (9999, 12)
    t = esc.get("tabla") or []
    cab = [x for x in (_mes_col(h) for h in (t[0] if t else [])) if x]
    per = str(esc.get("periodo") or "").lower()
    anios = [int(a) for a in re.findall(r"20\d{2}", per)]
    ms = sorted((per.find(n), i) for i, n in enumerate(MESES) if n in per)
    ini_per = (anios[0], ms[0][1] + 1) if anios and ms else None
    if ini_per and len(anios) == 1 and len(ms) > 1 and ms[0][1] > ms[-1][1]:
        ini_per = (anios[0] - 1, ini_per[1])  # «noviembre a febrero 2027»
    return min(cab + ([ini_per] if ini_per else [])) if (cab or ini_per) else (9999, 12)


def cargar_convenios():
    locales = {}
    for ruta in glob.glob(os.path.join(RAIZ, "convenios", "*.json")):
        with open(ruta, encoding="utf-8") as f:
            c = json.load(f)
        locales[c["slug"]] = c
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if url and key:
        try:
            req = urllib.request.Request(url + "/rest/v1/convenios?select=*", headers={"apikey": key, "Authorization": "Bearer " + key})
            for c in json.load(urllib.request.urlopen(req, timeout=30)):
                loc = locales.get(c["slug"]) or {}
                # escala del repo si la de la fábrica está vacía o es más vieja (p. ej. Comercio: julio en la base y octubre-diciembre en el repo)
                if _escala_ok(loc.get("escala")) and (not _escala_ok(c.get("escala")) or _fin_escala(loc["escala"]) > _fin_escala(c.get("escala"))):
                    c = dict(c, escala=loc["escala"], historial=c.get("historial") or loc.get("historial") or [],
                             actualizado=loc.get("actualizado") or c.get("actualizado"), fuente=loc.get("fuente") or c.get("fuente"))
                locales[c["slug"]] = c
        except Exception as ex:
            print("Aviso: no se pudieron leer los convenios:", ex)
    return sorted(locales.values(), key=lambda c: c["nombre"])


def tabla_html(t):
    if not t:
        return ""
    cab = "".join(f"<th>{e(str(x))}</th>" for x in t[0])
    filas = "".join("<tr>" + "".join(f"<td>{e(str(x))}</td>" for x in f) + "</tr>" for f in t[1:])
    return f'<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{filas}</tbody></table></div>'


# Cómo se busca cada convenio en Google: la sigla primero si es la forma habitual («escala UOCRA», «escala UOM»)
NOMBRE_BUSQUEDA = {  # según las sugerencias de Google («escala uocra noviembre 2026», «escala comercio», «escala smata acara»…)
    "uocra": "UOCRA", "uom": "UOM", "comercio": "Comercio", "sanidad": "Sanidad (FATSA)", "gastronomicos": "Gastronómicos (UTHGRA)",
    "encargados-edificios": "SUTERH encargados de edificio", "rurales": "UATRE (rurales)", "smata-concesionarias": "SMATA ACARA (concesionarias)",
    "smata-faatra": "SMATA FAATRA (talleres)", "casas-particulares": "Casas Particulares", "quimicos": "Químicos y petroquímicos",
    "pasteleros-heladerias": "Pasteleros y heladerías"}
CONV_IDX = {}


def nombre_busqueda(c):
    return NOMBRE_BUSQUEDA.get(c["slug"]) or c["nombre"]


def caja_escala(n):
    """En la guía de cómo liquidar un convenio, el acceso a la escala vigente (lo que más se busca)."""
    sl = str(n.get("slug", ""))
    if not sl.startswith("guia-liquidar-sueldo-"):
        return ""
    c = CONV_IDX.get(sl[len("guia-liquidar-sueldo-"):])
    if not c:
        return ""
    per = (c.get("escala") or {}).get("periodo") or ""
    return (f'<p class="ef-pro">📋 <b>Escala vigente:</b> <a href="escala-{c["slug"]}.html">Escala salarial {e(nombre_busqueda(c))} {e(per)} ({e(c.get("cct", ""))}): '
            f'valores por categoría y sumas no remunerativas →</a></p>')


_MES_ABR = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def preguntas_escala(c):
    """Preguntas frecuentes armadas con la tabla vigente: se rehacen solas cada vez que cambia la escala (y el mes, si la tabla es por meses)."""
    esc = c.get("escala") or {}
    t, per = esc.get("tabla") or [], esc.get("periodo") or ""
    filas = [f for f in t[1:] if isinstance(f, list) and len(f) > 1 and any(re.search(r"\d", str(x)) for x in f[1:])]
    if len(t) < 2 or not filas:
        return []
    cab = [str(x) for x in t[0]]
    hoy = datetime.date.today()
    col = next((i for i, h in enumerate(cab) if i and (_MES_ABR[hoy.month - 1] in h.lower() or MESES[hoy.month - 1] in h.lower())
                and (str(hoy.year) in h or str(hoy.year)[2:] in h or not re.search(r"\d{2}", h))), None)
    cuando = f"{MESES[hoy.month - 1]} {hoy.year}" if col is not None else (per[:1].lower() + per[1:])
    if col is None:
        col = next((i for i in range(1, len(cab)) if any(re.search(r"\d", str(f[i])) for f in filas if len(f) > i)), 1)
    sig = nombre_busqueda(c)
    def val(f):
        v = str(f[col]).strip() if len(f) > col else ""
        if re.fullmatch(r"\d{4,}", v):
            return "$ " + f"{int(v):,}".replace(",", ".")
        return ("$ " + v) if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?|\d+,\d+", v) else v
    de = f" ({cab[col]})" if len(cab) > col and cab[col] and col is not None and cuando == per else ""
    rige = (f" Rige {esc['vigencia'][0].lower() + esc['vigencia'][1:]}." if str(esc.get("vigencia", "")).lower().startswith("desde")
            else (f" Vigencia: {esc['vigencia']}." if esc.get("vigencia") else ""))
    qs = [{"p": f"¿Cuál es la escala salarial {sig} {cuando}?".replace("  ", " "),
           "r": f"La escala vigente de {c['nombre']} ({c.get('cct', '')}) para {cuando} tiene {len(filas)} {"categorías" if len(filas) > 1 else "categoría"}. "
                + "; ".join(f"{f[0]}: {val(f)}" for f in filas[:4]) + (", y las demás están en la tabla de esta página." if len(filas) > 4 else ".")
                + (f" Valores de la columna «{cab[col]}»." if len(cab) > col and cab[col] else "") + rige}]
    for f in filas[:2]:
        if val(f):
            qs.append({"p": f"¿Cuánto cobra la categoría {f[0]} de {sig} en {cuando}?".replace("  ", " "),
                       "r": f"Según la escala vigente ({c.get('cct', '')}), la categoría {f[0]} tiene un valor de {val(f)}{de}.{rige}"})
    return qs


def _imp(v):
    """Importe de una celda de escala («1.233.448,08», «$ 4.665,41», «211198») o None."""
    t = str(v or "").replace("$", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?|\d+(,\d+)?", t):
        return float(t.replace(".", "").replace(",", "."))
    return None


def _mes_col(h):
    """(año, mes) de un encabezado tipo «Nov 2026», «Básico nov 2026», «01/11/26» o None."""
    h = str(h).lower()
    m = re.search(r"\b(\d{2})/(\d{2})/(\d{2})\b", h) or None  # 01/11/26
    if m and 1 <= int(m.group(2)) <= 12:
        return (2000 + int(m.group(3)), int(m.group(2)))
    m = re.search(r"\b(\d{1,2})/(20\d{2})\b", h)  # 11/2026
    if m and 1 <= int(m.group(1)) <= 12:
        return (int(m.group(2)), int(m.group(1)))
    for i, a in enumerate(_MES_ABR):
        m = re.search(a + r"[a-zé]*\.?\s*(?:de\s*)?(?:y\s*\w+\s*)?-?\s*(20\d{2}|\d{2})\b", h)
        if m:
            y = int(m.group(1))
            return (y + 2000 if y < 100 else y, i + 1)
    return None


def resumen_escala(c, notas):
    """Texto propio de cada escala armado con su tabla: ejemplo de cálculo con la categoría de referencia, cuánto aumentó en el
    período y accesos (guía de cómo liquidar, calculadora, paritarias del mes). Cambia solo cuando cambia la escala o el mes."""
    esc = c.get("escala") or {}
    t = esc.get("tabla") or []
    if len(t) < 3:
        return ""
    cab = [str(x) for x in t[0]]
    filas = [f for f in t[1:] if isinstance(f, list) and len(f) > 1]
    hoy = datetime.date.today()
    rem = [i for i in range(1, len(cab)) if "no rem" not in cab[i].lower() and "nr" != cab[i].lower().strip()]
    meses = [(i, _mes_col(cab[i])) for i in rem if _mes_col(cab[i])]
    col = next((i for i, ym in meses if ym == (hoy.year, hoy.month)), None)
    if col is None:
        col = next((i for i in rem if any(_imp(f[i]) for f in filas if len(f) > i)), None)
    if col is None:
        return ""
    # categoría de referencia: la primera con valor mensual (más de $ 100.000) en esa columna
    ref = next((f for f in filas if len(f) > col and (_imp(f[col]) or 0) > 100000 and "imgr" not in str(f[0]).lower()
                and "mínimo" not in str(f[0]).lower()), None)
    sig, cuando = nombre_busqueda(c), (f"{MESES[hoy.month - 1]} {hoy.year}" if any(ym == (hoy.year, hoy.month) for _, ym in meses) else ((esc.get("periodo") or "")[:1].lower() + (esc.get("periodo") or "")[1:] or "la escala vigente"))
    partes = []
    if ref:
        b = _imp(ref[col])
        nr_col = next((i for i in range(1, len(cab)) if "no rem" in cab[i].lower() and (_mes_col(cab[i]) == _mes_col(cab[col]) or not _mes_col(cab[i]))), None)
        nr = _imp(ref[nr_col]) if nr_col is not None and len(ref) > nr_col else None
        es_mes = any(ym == (hoy.year, hoy.month) for _, ym in meses)
        nom_cat = re.sub(r"^categor[ií]a\s+", "", str(ref[0]), flags=re.I)
        cat_txt = f"la categoría <b>{e(nom_cat)}</b>"
        txt = (f"Por ejemplo, {cat_txt} de {e(sig)} tiene {'en' if es_mes else 'en el período'} {e(cuando)} un básico de <b>$ {_num(b)}</b>. "
               f"Sobre lo remunerativo se descuentan los aportes de ley: 11% de jubilación, 3% de PAMI y 3% de obra social (17% en total), "
               f"así que de ese básico quedan unos <b>$ {_num(b * 0.83)}</b>, sin contar antigüedad, presentismo ni otros adicionales del convenio "
               f"y antes de la cuota sindical.")
        if nr:
            txt += (f" Además se suman <b>$ {_num(nr)}</b> no remunerativos ({e(cab[nr_col])}): sobre esa suma no se aportan jubilación ni PAMI, "
                    f"y lo que se descuenta de obra social o sindicato depende de lo que diga el acuerdo.")
        partes.append(f"<p>{txt}</p>")
        if len(meses) >= 2 and len(ref) > max(i for i, _ in meses):
            (i0, ym0), (i1, ym1) = meses[0], meses[-1]
            v0, v1 = _imp(ref[i0]), _imp(ref[i1])
            if v0 and v1 and v1 > v0:
                partes.append(f"<p>Entre <b>{MESES[ym0[1] - 1]} {ym0[0]}</b> y <b>{MESES[ym1[1] - 1]} {ym1[0]}</b> el básico de esa categoría pasa de "
                              f"$ {_num(v0)} a $ {_num(v1)}: una suba de <b>{_num((v1 / v0 - 1) * 100)}%</b> en el período de la escala.</p>")
    links = []
    if any(n.get("slug") == f"guia-liquidar-sueldo-{c['slug']}" for n in notas):
        links.append(f'<a href="nota-guia-liquidar-sueldo-{c["slug"]}.html">Cómo liquidar un sueldo de {e(sig)} paso a paso</a>')
    calc = {"comercio": ("sueldo-comercio.html", "Calculadora de sueldo de Comercio con esta escala"),
            "casas-particulares": ("sueldo-casas-particulares.html", "Calculadora de sueldo de casas particulares")}.get(c["slug"])
    if calc:
        links.append(f'<a href="{calc[0]}">{calc[1]}</a>')
    links.append(f'<a href="paritarias-{c["slug"]}-{MESES[hoy.month - 1]}-{hoy.year}.html">Paritarias de {e(sig)} en {MESES[hoy.month - 1]} {hoy.year}</a>')
    links.append('<a href="aguinaldo.html">Calculadora de aguinaldo</a>')
    return (f'<h2>Cómo leer la escala {e(sig)}</h2>' + "".join(partes)
            + '<ul class="escala-links">' + "".join(f"<li>{x}</li>" for x in links) + "</ul>")


def pagina_indices_facpce(notas):
    """Índices FACPCE para el ajuste por inflación contable (RT 6, Res. JG 539/18), desde tablas/indices-facpce.json (copiado de la planilla oficial)."""
    ruta = os.path.join(RAIZ, "tablas", "indices-facpce.json")
    if not os.path.exists(ruta):
        return None
    d = json.load(open(ruta, encoding="utf-8"))
    ser = sorted(d["serie"], key=lambda x: x["mes"])
    idx = {x["mes"]: x["indice"] for x in ser}
    nom = lambda m: f"{MESES[int(m[5:]) - 1]} {m[:4]}"
    f4 = lambda v: f"{v:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
    pc = lambda a, b: f"{(b / a - 1) * 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "%"
    def mes_ant(m, k=1):
        y, mm = int(m[:4]), int(m[5:]) - k
        while mm < 1:
            y, mm = y - 1, mm + 12
        return f"{y}-{mm:02d}"
    ult = ser[-1]["mes"]
    anio = ult[:4]
    v = idx[ult]
    men = pc(idx[mes_ant(ult)], v) if mes_ant(ult) in idx else "—"
    ia = pc(idx[mes_ant(ult, 12)], v) if mes_ant(ult, 12) in idx else "—"
    acu = pc(idx[f"{int(anio) - 1}-12"], v) if f"{int(anio) - 1}-12" in idx else "—"
    filas = "".join(
        f"<tr><td>{nom(x['mes']).capitalize()}</td><td>{f4(x['indice'])}</td>"
        f"<td>{pc(idx[mes_ant(x['mes'])], x['indice']) if mes_ant(x['mes']) in idx else '—'}</td>"
        f"<td>{pc(idx[mes_ant(x['mes'], 12)], x['indice']) if mes_ant(x['mes'], 12) in idx else '—'}</td></tr>" for x in ser[::-1])
    opciones = "".join(f'<option value="{x["mes"]}">{nom(x["mes"]).capitalize()}</option>' for x in ser[::-1])
    datos_js = json.dumps(idx)
    titulo = f"Índices FACPCE {anio} para ajuste por inflación (RT 6): tabla mensual"
    qs = [{"p": f"¿Cuál es el último índice FACPCE?", "r": f"El de {nom(ult)}: {f4(v)}. Variación mensual {men} e interanual {ia}."},
          {"p": "¿Cómo se calcula el coeficiente de reexpresión?", "r": "Se divide el índice del mes de cierre por el índice del mes de origen de la partida. Por ejemplo, para reexpresar a octubre un importe de enero, se divide el índice de octubre por el de enero."},
          {"p": "¿Qué índice se usa para el ajuste por inflación contable?", "r": "El que define la Resolución de Junta de Gobierno FACPCE 539/18: el IPC nacional del INDEC empalmado con el IPIM para los períodos anteriores."},
          {"p": "¿Cuándo sale el índice del mes que viene?", "r": d.get("proximo") or "FACPCE lo publica después de que el INDEC difunde el IPC del mes."}]
    cuerpo = f"""<div class="grilla"><article class="nota calc">
<p class="ante">Ajuste por inflación | RT 6 · Res. JG FACPCE 539/18</p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Último índice: {nom(ult)}</p>
<div class="encorto"><b>En corto</b><p>El índice FACPCE de {nom(ult)} es <b>{f4(v)}</b>: {men} de variación mensual, {ia} interanual y {acu} en lo que va de {anio}. {e(d.get("proximo") or "")}</p></div>
<h2>Calculá el coeficiente de reexpresión</h2>
<form id="calc-facpce" class="form-calc" novalidate><div class="fila2"><label>Mes de origen<select name="origen">{opciones}</select></label>
<label>Mes de cierre<select name="cierre">{opciones}</select></label></div>
<label>Importe a reexpresar (opcional)<input name="monto" inputmode="decimal" placeholder="Ej.: 1.000.000"></label>
<button class="btn ancho">Calcular</button></form>
<section id="resultado-facpce" class="resultado" hidden></section>
<h2>Tabla de índices mes a mes</h2>
<div class="tabla"><table><thead><tr><th>Mes</th><th>Índice</th><th>Variación mensual</th><th>Variación interanual</th></tr></thead><tbody>{filas}</tbody></table></div>
<h2>Cómo se usa</h2>
<p>Para reexpresar una partida en moneda de cierre se multiplica su importe por el coeficiente: índice del mes de cierre dividido por el índice del mes de origen. El índice es el que define la Resolución de Junta de Gobierno 539/18 de la FACPCE para aplicar la RT 6: el IPC nacional del INDEC, empalmado con el IPIM para los períodos anteriores.</p>
<p>Las variaciones mensual e interanual las calculamos con los índices de la planilla oficial. La planilla completa, con la serie desde enero de 1993, está en la <a href="{e(d.get("fuente", ""))}" rel="nofollow noopener" target="_blank">página de índices de la FACPCE</a>.</p>
<p><a class="btn" href="nota-guia-ajuste-inflacion-contable.html">Guía del ajuste por inflación contable →</a></p>
{preguntas_html({"preguntas": qs})}
<p class="aviso">Información de carácter general, copiada de la planilla oficial de la FACPCE. Verificá siempre en la fuente antes de cerrar un balance.</p>
</article>{lateral(notas)}</div>
<script>(function(){{var I={datos_js};var f=document.getElementById('calc-facpce');if(!f)return;f.origen.value=(Number('{ult[:4]}')-1)+'-12';f.cierre.value='{ult}';var o=document.getElementById('resultado-facpce');
function num(t){{t=String(t||'').replace(/\$|\s/g,'');if(!t)return 0;if(/,\d{{1,4}}$/.test(t)||(t.indexOf('.')>=0&&t.indexOf(',')>=0))return Number(t.replace(/\./g,'').replace(',','.'));if(/^\d{{1,3}}(\.\d{{3}})+$/.test(t))return Number(t.replace(/\./g,''));return Number(t.replace(',','.'))}}
f.addEventListener('submit',function(ev){{ev.preventDefault();var a=I[f.origen.value],b=I[f.cierre.value];if(!a||!b)return;var c=b/a,m=num(f.monto.value);
var fm=function(n,d){{return n.toLocaleString('es-AR',{{minimumFractionDigits:d,maximumFractionDigits:d}})}};
o.innerHTML='<p class="res-grande">Coeficiente: <b>'+fm(c,4)+'</b></p><p class="ayuda">Índice de cierre '+fm(b,4)+' ÷ índice de origen '+fm(a,4)+' (variación '+fm((c-1)*100,2)+'%).</p>'+(m>0?'<p class="res-grande">Importe reexpresado: <b>$ '+fm(m*c,2)+'</b></p>':'');o.hidden=false}});}})();</script>"""
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    desc = f"Índice FACPCE de {nom(ult)}: {f4(v)} ({men} mensual, {ia} interanual). Tabla mes a mes para el ajuste por inflación contable (RT 6) y calculadora del coeficiente."
    return pagina(_titulo_seo(titulo, f"Índices FACPCE {anio} (RT 6): tabla mensual y coeficiente", f"Índices FACPCE {anio} (RT 6)"), cuerpo, "impuestos", desc[:160],
                  "indices-facpce.html", ld, [("Impuestos", "impuestos.html"), ("Índices FACPCE", "indices-facpce.html")])


def pagina_convenio(c, notas, aportes=None):
    esc = c.get("escala") or {}
    periodo = esc.get("periodo") or ""
    seccion = lambda titulo, bloques: (f"<h2>{titulo}</h2>" + "".join(bloque(x) for x in bloques)) if bloques else ""
    if esc.get("tabla"):
        escala = (f'<p class="periodo"><b>Período:</b> {e(periodo)}' + (f' · <b>Vigencia:</b> {e(esc.get("vigencia",""))}' if esc.get("vigencia") else "") + "</p>"
                  + tabla_html(esc["tabla"]) + (f'<p class="ayuda">{e(esc.get("aclaraciones",""))}</p>' if esc.get("aclaraciones") else ""))
    else:
        escala = '<div class="vacio-caja"><b>Escala pendiente de carga</b>Se actualiza automáticamente con el próximo acuerdo salarial publicado.</div>'
        PAGINAS_FINAS.add(f"escala-{c['slug']}")  # sin tabla queda flaca: no se indexa hasta que se cargue la escala
    relacionadas_c = [n for n in notas if n.get("convenio") == c["slug"]][:8]
    hist = c.get("historial") or []
    hist_html = ("<h2>Historial de escalas</h2><ul class='historial'>" + "".join(
        f'<li><b>{e(h.get("periodo",""))}</b>' + (f' · <a href="nota-{e(h["nota"])}.html">ver nota</a>' if h.get("nota") else "") + "</li>" for h in hist[::-1]) + "</ul>") if hist else ""
    notas_html = ("<h2>Notas sobre este convenio</h2><ul class='historial'>" + "".join(
        f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a> <small>{fecha_larga(n["fecha"])}</small></li>' for n in relacionadas_c) + "</ul>") if relacionadas_c else ""
    auto_q = preguntas_escala(c)
    falsa_nota = {"preguntas": auto_q + (c.get("preguntas") or [])}
    slug = "convenio-" + c["slug"]
    titulo_vis = f"Escala salarial {c['nombre']}" + (f" {periodo}" if periodo else "") + (f" ({c['cct']})" if c.get("cct", "").startswith("CCT") else "")
    contenido = f"""<div class="grilla"><article class="nota convenio" data-nota="{slug}" data-convenio="{e(c['slug'])}" data-actualizado="{e(str(c.get('actualizado') or ''))}" data-fin="{"%d-%02d" % _fin_escala(esc)}">
<script type="application/json" id="escala-pagina">{json.dumps(esc, ensure_ascii=False).replace("</", "<\\/")}</script>
<div class="nota-contenido">
<p class="miga"><a href="sueldos.html">Sueldos</a> / <a href="convenios.html">Convenios</a></p>
<p class="ante">{e(c['cct'])} | {e(c['partes'])}</p>
<h1>{e(titulo_vis)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(str(c.get('actualizado') or datetime.date.today().isoformat())[:10])}</p>
{f'<p class="intro-escala">Esta es la <b>escala salarial {e(nombre_busqueda(c))} {e(periodo)}</b> ({e(c["cct"])}) con los valores por categoría y las sumas no remunerativas del último acuerdo. Se actualiza sola cuando sale una paritaria nueva.</p>' if periodo else ""}
<div class="encorto"><b>Quiénes están comprendidos</b><p>{e(c.get('descripcion',''))}</p></div>
<h2>Escala vigente</h2>{escala}
{resumen_escala(c, notas) if esc.get("tabla") else ""}
{seccion("Qué cambió con el último acuerdo", c.get("novedades"))}
{seccion("Cómo se calcula", c.get("calculo"))}
{seccion("Sumas no remunerativas: aportes y contribuciones", c.get("nr"))}
{seccion("Cómo figura en el recibo", c.get("recibo"))}
{preguntas_html(falsa_nota)}
{hist_html}{notas_html}
{f'<p class="fuente"><b>Fuente:</b> {e(c["fuente"])}</p>' if c.get("fuente") else ""}
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en el acuerdo homologado y en las fuentes oficiales. Cada profesional es responsable de su aplicación.</p>
</div>
<section class="bloque-op" id="opiniones">
<h2 class="tit-bloque">Opiniones <span data-n="opiniones">0</span></h2>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="¿Qué opinás de esta escala?" required></textarea><button class="btn">Publicar opinión</button></form>
<div id="lista-opiniones" class="lista"></div>
<button type="button" class="btn sec ancho" id="ver-mas-op" hidden>Ver más opiniones</button>
</section>
<section class="bloque-aplica" id="aplica">
<h2 class="tit-bloque">¿Cómo se liquida? <span data-n="pasos">0</span></h2>
<p class="ayuda">Explicá cómo se liquida este convenio: un caso práctico, un recibo de ejemplo o una aclaración de la norma. Las más votadas quedan arriba.</p>
<div id="lista-pasos" class="lista">{pasos_estaticos(aportes or [])}</div>
<button class="btn ancho" data-nuevo-paso>Subir una explicación</button>
</section>
</article>{lateral(notas)}</div>"""
    nom_c = re.sub(r"\s*\([^)]*\)\s*$", "", c["nombre"])
    sig, cct_c = nombre_busqueda(c), re.sub(r"\s*\(.*\)$", "", c.get("cct") or "")
    seo_t = _titulo_seo(f"Escala {sig} {periodo} ({cct_c}): básicos y sumas NR", f"Escala {sig} {periodo} ({cct_c}): básicos y NR",
                        f"Escala {sig} {periodo} ({cct_c})", f"Escala {sig} {periodo}: básicos y NR ({cct_c})", f"Escala salarial {sig} ({cct_c}): básicos y NR", f"Escala {c['nombre']} {periodo} ({c['cct']}): básicos, NR y cómo liquidar", f"Escala {c['nombre']} {periodo} ({c['cct']}): básicos y NR",
                        f"Escala {c['nombre']} {periodo}: básicos y NR", f"Escala {c['nombre']} ({c['cct']})", f"Escala salarial {nom_c} {periodo}", f"Escala salarial {nom_c}")
    desc = (f"Escala {sig} {periodo} ({cct_c}): valores por categoría, sumas no remunerativas y cómo se liquida, con el último acuerdo." if periodo
            else f"Escala salarial vigente de {c['nombre']} ({c['cct']}): valores por categoría, sumas no remunerativas, aportes y cómo se liquida.")
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": titulo_vis[:110], "description": desc,
          "dateModified": str(c.get("actualizado") or datetime.date.today().isoformat()), "inLanguage": "es-AR",
          "author": {"@type": "Organization", "name": "Redacción Ramacontable"}, "mainEntityOfPage": f"{sitio_url()}escala-{c['slug']}.html"}
    head = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>'
    if falsa_nota["preguntas"]:
        head += '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in falsa_nota["preguntas"]]}, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    contenido = contenido.replace("</article>", '<section class="relacionadas"><h2>Paritarias por mes</h2><ul>' + "".join(
        f'<li><a href="paritarias-{c["slug"]}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html">Paritarias {e(c["nombre"])} {MESES[int(m[5:]) - 1]} {m[:4]}</a></li>' for m in _meses_paginas()) + "</ul></section></article>", 1)
    return pagina(seo_t + " | Ramacontable", contenido, "sueldos", desc, f"escala-{c['slug']}.html", head,
                  [("Sueldos", "sueldos.html"), ("Convenios", "convenios.html"), (c["nombre"], f"escala-{c['slug']}.html")])


def pagina_convenios(convenios, notas):
    items = "".join(
        f'<a class="tarjeta conv" href="escala-{c["slug"]}.html"><div class="tx"><p class="ante">{e(c["cct"])}</p><h2>Escala {e(nombre_busqueda(c))}</h2>'
        f'<p class="meta">{e(c["nombre"])} · {e((c.get("escala") or {}).get("periodo") or "Escala pendiente de carga")}</p></div></a>' for c in convenios)
    cuerpo = f'<div class="grilla"><section><h1 class="titsec">Convenios y escalas salariales</h1><p class="ayuda">Escalas vigentes, novedades de cada acuerdo, tratamiento de las sumas no remunerativas y cómo se liquida cada convenio.</p><div class="tarjetas">{items}</div></section>{lateral(notas)}</div>'
    return pagina("Escalas salariales por convenio 2026: Comercio, UOCRA, UOM, Sanidad y más | Ramacontable", cuerpo, "sueldos",
                  "Escalas salariales vigentes por convenio colectivo, con novedades, sumas no remunerativas y cómo liquidar.", "convenios.html",
                  migas=[("Sueldos", "sueldos.html"), ("Convenios", "convenios.html")])


PRINCIPALES = ["comercio", "casas-particulares", "uocra", "uom", "sanidad"]


def tira_guias(guias, seccion):
    lista = [g for g in guias if g["seccion"] == seccion]
    if not lista:
        return ""
    return (f'<div class="conv-chips guias-chips"><b>{e(RAMAS_GUIAS[seccion])}:</b> ' + " ".join(
        f'<a href="nota-{g["slug"]}.html">{e(g["titulo"].split(":")[0])}</a>' for g in lista[:2]) + f' <a class="mas-chip" href="guias.html#{seccion}">Ver más guías ({len(lista)}) →</a></div>')


def pagina_guias(guias, notas, catalogo):
    hechas = {g["slug"] for g in guias}
    grupo_cat = {"guia-" + c["slug"]: c.get("grupo") or c["seccion"] for c in catalogo}
    grupo_de = lambda g: grupo_cat.get(g["slug"]) or (g["seccion"] if g["seccion"] in ("sueldos", "impuestos") else "otras")
    bloques = ""
    for k, titulo in GRUPOS_GUIAS.items():
        lista = sorted([g for g in guias if grupo_de(g) == k], key=lambda g: g["titulo"])
        prox = [c for c in catalogo if (c.get("grupo") or c["seccion"]) == k and "guia-" + c["slug"] not in hechas]
        if not lista and not prox:
            continue
        items = "".join(f'<li><a href="nota-{g["slug"]}.html"><b>{e(g["titulo"])}</b><span>{e(g.get("encorto", "")[:140])}</span></a></li>' for g in lista)
        items += "".join(f'<li class="prox"><b>{e(c["titulo"])}</b><span>Próximamente</span></li>' for c in prox)
        bloques += f'<section class="rama-guias" id="{k}"><h2>{e(titulo)}</h2><ul class="lista-guias">{items}</ul></section>'
    otras = '<p class="ayuda">¿Buscás novedades de la profesión? <a href="profesion.html">Ver notas de Profesión →</a></p>'
    if EXPLICADO:
        otras = (f'<section class="ef-bloque-guias"><h2>{e(SECCION_FACIL)}, {e(SECCION_FACIL_SUB)}</h2><p class="ayuda">Para empleados, emprendedores y monotributistas: explicado fácil, sin palabras raras.</p><div class="chips">'
                 + "".join(f'<a href="{g["ruta"]}.html">{e(g["titulo"].split("?")[0].lstrip("¿").split(":")[0])}</a>' for g in EXPLICADO)
                 + f'<a href="{RUTA_FACIL}.html">Todas →</a></div></section>') + otras
    cuerpo = f'<div class="grilla"><section><h1 class="titsec">Guías prácticas</h1><p class="ayuda">Guías completas de sueldos, impuestos y temas contables, basadas en la norma oficial y actualizadas cuando cambia algo. Debajo de cada una, la comunidad suma sus explicaciones y casos prácticos.</p>{bloques}{otras}</section>{lateral(notas)}</div>'
    return pagina("Guías prácticas de sueldos, impuestos y contabilidad | Ramacontable", cuerpo, "guias",
                  "Guías prácticas para contadores y liquidadores: vacaciones, liquidación final, Ganancias, IVA, Monotributo, Ingresos Brutos y más.", "guias.html", migas=[("Guías", "guias.html")])


def pagina_impuesto(imp, notas, guias, catalogo):
    slug, nombre, claves, guias_slugs = imp
    por_slug = {g["slug"]: g for g in guias}
    tit_cat = {c["slug"]: c["titulo"] for c in catalogo}
    items = ""
    for s in guias_slugs:
        g = por_slug.get("guia-" + s)
        items += (f'<li><a href="nota-{g["slug"]}.html"><b>{e(g["titulo"])}</b><span>{e(g.get("encorto", "")[:140])}</span></a></li>' if g
                  else f'<li class="prox"><b>{e(tit_cat.get(s, s))}</b><span>Próximamente</span></li>')
    relacionadas_i = [n for n in notas if any(c in _N(n["titulo"] + " " + n.get("antetitulo", "") + " " + (n.get("tema") or "")) for c in claves)]
    lista = ('<div class="tarjetas">' + "".join(tarjeta(n) for n in relacionadas_i[:20]) + "</div>") if relacionadas_i else '<p class="vacio">Todavía no hay novedades de este tema.</p>'
    if not relacionadas_i and not any(por_slug.get("guia-" + s_) for s_ in guias_slugs) and not (slug == "ingresos-brutos" and JURIS):
        PAGINAS_FINAS.add(f"impuesto-{slug}")  # sin guías ni novedades todavía: no se indexa hasta que tenga contenido
    cuerpo = (f'<div class="grilla"><section><p class="miga"><a href="impuestos.html">Impuestos</a></p><h1 class="titsec">{e(nombre)}</h1>'
              + "".join(f'<div class="dato-vigente ef-aviso"><b>¿No sos contador?</b> <a href="{g["ruta"]}.html">{e(g["titulo"])} →</a></div>' for g in EXPLICADO if slug == "monotributo")
              + f'<section class="rama-guias"><h2>Guías de {e(nombre)}</h2><ul class="lista-guias">{items}</ul></section>'
              + ('<div class="conv-chips"><b>Por provincia:</b> ' + " ".join(f'<a href="{j["ruta"]}.html">{e(j["titulo_corto"])}</a>' for j in JURIS)
                 + ' <a class="mas-chip" href="provincias-y-municipios.html">Todas →</a></div>' if slug == "ingresos-brutos" and JURIS else "")
              +               f'<section class="rama-guias"><h2>Novedades de {e(nombre)}</h2>{lista}</section></section>{lateral(notas)}</div>')
    return pagina(f"{nombre}: novedades, vencimientos y guías prácticas | Ramacontable", cuerpo, "impuestos",
                  f"Todo sobre {nombre} para contadores: últimas novedades, normas y guías prácticas paso a paso.", f"impuesto-{slug}.html",
                  migas=[("Impuestos", "impuestos.html"), (nombre, f"impuesto-{slug}.html")])


def pagina_vencimientos(notas):
    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    hoy = datetime.date.today().isoformat()
    bloques = ""
    for fila in VENC:
        items = [x for x in fila.get("items") or [] if x.get("fecha", "") >= hoy[:8] + "01"]
        if not items or fila["mes"] < hoy[:7]:
            continue
        anio, mes = fila["mes"].split("-")
        filas = "".join(
            f'<tr{" class=pasado" if x["fecha"] < hoy else ""}><td>{DIAS[datetime.date.fromisoformat(x["fecha"]).weekday()].capitalize()} {int(x["fecha"][8:])}</td>'
            f'<td>{e(x["concepto"])}</td><td>{e(x.get("detalle") or "Todas las terminaciones")}</td></tr>' for x in items)
        fer = "".join(f'<li><b>{fecha_corta(x["fecha"])}</b> {e(x["nombre"])} <small>({e(x.get("tipo",""))})</small></li>' for x in fila.get("feriados") or [])
        bloques += (f'<h2>Vencimientos de {MESES[int(mes)-1]} {anio}</h2><div class="tabla"><table class="feriados"><thead><tr><th>Fecha</th><th>Obligación</th><th>Terminación de CUIT</th></tr></thead><tbody>{filas}</tbody></table></div>'
                    + (f'<p class="ayuda"><b>Feriados y días no laborables del mes:</b></p><ul class="historial">{fer}</ul>' if fer else ""))
    if not bloques:
        bloques = '<div class="vacio-caja"><b>Agenda en preparación</b>La agenda del mes se actualiza automáticamente todos los días.</div>'
    cuerpo = (f'<div class="grilla"><article class="nota calc"><p class="ante">Herramientas | ARCA</p><h1>Vencimientos impositivos y previsionales</h1>'
              f'<p class="firma">Redacción Ramacontable · Se actualiza todos los días</p>{bloques}'
              '<p class="aviso">Se publican solo las fechas confirmadas por al menos dos fuentes. Verificá siempre en la agenda oficial de ARCA según la terminación de tu CUIT.</p>'
              f'</article>{lateral(notas)}</div>')
    return pagina("Vencimientos ARCA: calendario del mes por terminación de CUIT | Ramacontable", cuerpo, "",
                  "Vencimientos impositivos y previsionales del mes por terminación de CUIT: IVA, F.931, Monotributo, Autónomos, Ganancias y más.", "herramientas.html")


def html_admin(h):
    """HTML que escribió el administrador al editar: se quitan scripts y atributos peligrosos."""
    h = re.sub(r"(?is)<(script|style|iframe|object|embed|form)\b[^>]*>.*?</\1\s*>", "", h or "")
    h = re.sub(r"(?is)</?(script|style|iframe|object|embed|form|link|meta|base)\b[^>]*>", "", h)
    h = re.sub(r"(?i)\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", h)
    return re.sub(r"(?i)javascript:", "", h)


ICONOS = {
    "Instagram": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>',
    "YouTube": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="4"/><path d="M10 9l5 3-5 3z" fill="currentColor"/></svg>',
    "TikTok": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3v11a4 4 0 1 1-4-4"/><path d="M14 3c.5 3 2.5 5 5 5"/></svg>',
}


def datos_sitio(migas=None):
    """Datos estructurados que lee Google: el sitio, la organización y la ruta de la página (migas de pan)."""
    base = sitio_url()
    grafo = [{"@type": "Organization", "@id": base + "#org", "name": "Ramacontable", "url": base,
              "logo": {"@type": "ImageObject", "url": base + "icono-512.png"}, "email": MAIL, "sameAs": list(REDES.values())},
             {"@type": "WebSite", "@id": base + "#web", "name": "Ramacontable", "url": base, "inLanguage": "es-AR",
              "publisher": {"@id": base + "#org"}}]
    if migas:
        grafo.append({"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": base + u} for i, (n, u) in enumerate([("Inicio", "")] + list(migas))]})
    return '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": grafo}, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def herramienta_ld(nombre, descripcion, ruta):
    return '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "WebApplication", "name": nombre,
        "description": descripcion, "url": sitio_url() + ruta, "applicationCategory": "FinanceApplication", "operatingSystem": "Web",
        "inLanguage": "es-AR", "offers": {"@type": "Offer", "price": "0", "priceCurrency": "ARS"}}, ensure_ascii=False) + "</script>"


def acortar_titulo(t, largo=65):
    """Títulos que Google corta: saca el paréntesis final y la última enumeración («, …»); si sigue muy largo (más de 72),
    se queda con lo de antes de los dos puntos, salvo que ahí esté el monto. Nunca deja menos de 35 caracteres."""
    if len(t) <= largo:
        return t
    t2 = re.sub(r"\s*\([^()]*\)\s*$", "", t)
    if 35 <= len(t2) < len(t):
        t = t2
    while len(t) > largo and ", " in t:
        corto = t.rsplit(", ", 1)[0]
        if len(corto) < 35:
            break
        t = corto
    if len(t) > 72 and ": " in t:
        izq, der = t.split(": ", 1)
        if len(izq) >= 35 and "$" not in der:
            t = izq
    return t


# Menú «Datos del día»: los más consultados de cada grupo y «Ver más» con lo que queda (pedido de Ramiro)
MENU_DATOS_TOP = {"sueldos": ["salario-minimo-vital-y-movil", "jubilacion-minima-y-bono", "autonomos-categorias-aportes"],
                  "impuestos": ["monotributo-categorias-vigentes"],
                  "indices": ["valor-uva-hoy", "inflacion-mensual-ipc"],
                  "dolar": ["dolar-hoy", "dolar-oficial-hoy", "dolar-cripto-hoy"],
                  "vencimientos": ["vencimiento-autonomos"],
                  "calendario": ["feriados", "feriados-{prox}"]}
MENU_DATOS_VERMAS = {"sueldos": "sueldos", "impuestos": "impuestos", "indices": "tasas e índices", "dolar": "dólar", "vencimientos": "vencimientos", "calendario": "calendario"}
MENU_CALCS = [("aguinaldo.html", "Aguinaldo"), ("liquidacion-final.html", "Liquidación final e indemnización"), ("vacaciones.html", "Vacaciones"),
              ("retencion-ganancias.html", "Retención de Ganancias"), ("sueldo-comercio.html", "Sueldo de Comercio")]
MENU_VENC = ["agenda-vencimientos", "vencimiento-931", "vencimiento-monotributo", "vencimiento-autonomos", "vencimiento-iva"]


def menu_datos():
    prox = str(datetime.date.today().year + 1)
    out = []
    for gid, nombre, items in grupos_datos():
        top = [x.replace("{prox}", prox) for x in MENU_DATOS_TOP.get(gid, [])]
        elegidos = [(sl, ti) for sl in top for s2, ti, _ in items if s2 == sl] or [(sl, ti) for sl, ti, _ in items[:2]]
        resto = len(items) - len(elegidos)
        out += [("#g", nombre)] + [(f"{sl}.html", ti) for sl, ti in elegidos]
        if resto > 0:
            out.append((f"datos-al-dia.html#{gid}", f"Ver más de {MENU_DATOS_VERMAS.get(gid, nombre.lower())} ({resto}) →"))
    return out


def menu_datos_html():
    """Doble desplegable: los grupos de datos y, al pasar por cada uno (o tocarlo en el celu), todos sus datos."""
    out = ""
    for gid, nombre, items in grupos_datos():
        out += (f'<div class="sub"><a class="sub-t" href="datos-al-dia.html#{gid}">{e(nombre)}</a><div class="sub-m">'
                + "".join(f'<a href="{sl}.html">{e(ti)}</a>' for sl, ti, _ in items) + "</div></div>")
    return out + '<a class="sep" href="datos-al-dia.html">Todos los datos del día →</a>'


_N_CALCS = None


def menu_extra(actual=""):
    """Desplegables de Calculadoras y Vencimientos (los principales y «Ver todas»)."""
    global _N_CALCS
    if _N_CALCS is None:
        try:
            _N_CALCS = open(os.path.join(RAIZ, "paginas", "calculadoras.html"), encoding="utf-8").read().count('class="tarjeta"')
        except Exception:
            _N_CALCS = 0
    venc = dict((o[0], o[1]) for o in OBLIGACIONES)
    venc["agenda-vencimientos"] = "Agenda de vencimientos por CUIT"
    calcs = MENU_CALCS + [("calculadoras.html", f"Ver todas las calculadoras ({_N_CALCS}) →" if _N_CALCS else "Ver todas las calculadoras →")]
    vencs = [(f"{v}.html", venc[v]) for v in MENU_VENC if v in venc] + [("herramientas.html", "Ver todos los vencimientos →")]
    dd = lambda href, nombre, items, k: (f'<div class="dd dd-der"><a href="{href}"{" aria-current=page" if k == actual else ""}>{nombre}</a><div class="dd-m">'
                                          + "".join(f'<a href="{u}"{" class=sep" if t.endswith("→") else ""}>{e(t)}</a>' for u, t in items) + "</div></div>")
    return dd("calculadoras.html", "Calculadoras", calcs, "calculadoras") + dd("herramientas.html", "Vencimientos", vencs, "herramientas")


def pagina(titulo, cuerpo, actual="", descripcion="", ruta="", extra_head="", migas=None, imagen="compartir.png"):
    sub = {
        "sueldos": [("sueldos.html", "Novedades de sueldos"), ("convenios.html", "Escalas por convenio"), ("guias.html#sueldos", "Guías de sueldos"),
                    ("sueldo-comercio.html", "Calculadora de sueldo de Comercio"), ("datos-al-dia.html#sueldos", "Datos del día de sueldos"), ("vencimiento-931.html", "Vencimientos del F.931"), ("comparador-escalas.html", "Aumentos vs. inflación")],
        "impuestos": [("impuestos.html", "Novedades de impuestos")] + [(f"impuesto-{s}.html", n) for s, n, _, _ in IMPUESTOS] + [("provincias-y-municipios.html", "Provincias y municipios"), ("guias.html#impuestos", "Guías de impuestos"), ("datos-al-dia.html#impuestos", "Datos del día de impuestos")],
        "guias": ([(RUTA_FACIL + ".html", f"{SECCION_FACIL} ({SECCION_FACIL_SUB})")] if EXPLICADO else []) + [(f"guias.html#{k}", v) for k, v in GRUPOS_GUIAS.items()] + [("guias.html", "Todas las guías"), ("glosario.html", "Glosario")],
        "datos-al-dia": menu_datos(),
    }
    # Google corta los títulos largos y las descripciones de más de ~160 caracteres
    if len(titulo) > 62 and titulo.endswith(" | Ramacontable"):
        titulo = titulo[:-len(" | Ramacontable")]
    titulo = acortar_titulo(titulo)
    if descripcion and len(descripcion) > 160:
        corte = max(descripcion[:160].rfind(". "), descripcion[:160].rfind("; "))
        descripcion = descripcion[:corte + 1] if corte >= 90 else descripcion[:157].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if ruta and ruta[:-5] in PAGINAS_FINAS and "noindex" not in extra_head:
        extra_head += NOI
    menu = "".join(
        f'<div class="dd{" dd-datos" if k == "datos-al-dia" else ""}"><a href="{k}.html"{" aria-current=page" if k == actual else ""}>{v}</a>'
        f'<div class="dd-m">' + (menu_datos_html() if k == "datos-al-dia" else "".join((f'<span class="dd-g">{e(t)}</span>' if u == "#g" else f'<a href="{u}"{" class=sep" if ("guias.html" in u or "datos-al-dia.html#" in u) and k in ("sueldos", "impuestos") else " class=mas" if t.endswith("→") else ""}>{e(t)}</a>') for u, t in sub.get(k, []))) + '</div></div>'
        for k, v in list(MENU.items()))
    redes = "".join(
        f'<a href="{u}" target="_blank" rel="noopener" aria-label="{n}">{ICONOS[n]}</a>'
        for n, u in REDES.items())
    anio = datetime.date.today().year
    return f"""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)}</title>
<meta name="description" content="{e(descripcion or 'Novedades contables, impositivas y laborales explicadas claro, y una comunidad que muestra cómo se aplican.')}">
<link rel="canonical" href="{sitio_url()}{ruta}">
<meta property="og:site_name" content="Ramacontable"><meta property="og:locale" content="es_AR">
<meta property="og:title" content="{e(titulo)}"><meta property="og:description" content="{e(descripcion or 'Novedades de la profesión contable')}">
<meta property="og:url" content="{sitio_url()}{ruta}"><meta property="og:image" content="{sitio_url()}{imagen}">
<meta name="twitter:card" content="summary_large_image">
{extra_head}
{datos_sitio(migas)}
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=optional"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=optional" media="print" onload="this.media='all'"><noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=optional"></noscript>
<link rel="stylesheet" href="estilos.css?v={VERSION}">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="icon" href="/icono-96.png" type="image/png" sizes="96x96"><link rel="icon" href="/icono-192.png" type="image/png" sizes="192x192"><link rel="icon" href="/logo.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/icono-180.png"><link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#13271F">{"" if "noindex" in extra_head else '<meta name="robots" content="max-image-preview:large, max-snippet:-1">'}
</head><body>
<header class="cab"><div class="wrap fila">
<a class="logo" href="index.html">{LOGO_SVG}<span>ramacontable</span></a>
<nav class="menu">{menu}{menu_extra(actual)}<a class="chico2" href="buscar.html" aria-label="Buscar en Ramacontable">🔍 Buscar</a></nav>
<div id="sesion" class="sesion"><button class="btn" data-ingresar>Ingresar</button></div>
</div></header>
<main class="wrap">{cuerpo}</main>
<footer class="pie"><div class="wrap">
<a class="logo" href="index.html">{LOGO_SVG}<span>ramacontable</span></a>
<p>Novedades de la profesión contable explicadas claro.</p>
<p class="secs">{" · ".join(f'<a href="{k}.html">{v}</a>' for k, v in SECCIONES.items())} · <a href="guias.html">Guías</a>{f' · <a href="{RUTA_FACIL}.html">{SECCION_FACIL}</a>' if EXPLICADO else ""} · <a href="calculadoras.html">Calculadoras</a> · <a href="datos-al-dia.html">Datos del día</a></p>
<div class="redes">{redes}</div>
<p><a href="mailto:{MAIL}">{MAIL}</a></p>
<p class="legal">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. · <a href="como-trabajamos.html">Quiénes somos</a> · <a href="terminos.html">Términos y privacidad</a> · © {anio} Ramacontable</p>
</div></footer>
<div id="modal" class="modal" hidden></div>
<script>(function(){{var chico=function(){{return window.matchMedia('(max-width:760px)').matches||window.matchMedia('(hover:none)').matches}};
document.querySelectorAll('.cab .menu .dd > a').forEach(function(a){{a.addEventListener('click',function(ev){{if(!chico())return;var dd=a.parentNode,ab=dd.classList.contains('abierto');
document.querySelectorAll('.cab .menu .dd.abierto').forEach(function(x){{x.classList.remove('abierto')}});if(!ab){{ev.preventDefault();dd.classList.add('abierto');
var m=dd.querySelector('.dd-m');m.style.top=document.querySelector('.cab').getBoundingClientRect().bottom+'px'}}}})}});
document.querySelectorAll('.cab .menu .sub-t').forEach(function(a){{a.addEventListener('click',function(ev){{if(!chico())return;var sb=a.parentNode,ab=sb.classList.contains('abierto');
document.querySelectorAll('.cab .menu .sub.abierto').forEach(function(x){{x.classList.remove('abierto')}});if(!ab){{ev.preventDefault();sb.classList.add('abierto')}}}})}});
document.addEventListener('click',function(ev){{if(!ev.target.closest('.cab .menu .dd'))document.querySelectorAll('.cab .menu .dd.abierto').forEach(function(x){{x.classList.remove('abierto')}})}});}})();</script>
<script defer src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js"></script>
<script defer src="vendor/purify.min.js"></script>
<script defer src="config.js?v={VERSION}"></script>
<script defer src="editor.js?v={VERSION}"></script>
<script defer src="app.js?v={VERSION}"></script>
</body></html>"""


ICONOS_SVG = {
    "recibo": '<rect x="10" y="6" width="34" height="48" rx="3"/><path d="M17 18h14M17 26h20M17 34h12M17 44h20"/><circle cx="46" cy="14" r="9" fill="currentColor"/><path d="M46 9v10M49 11.5c-1-1.2-5-1.5-5 .8 0 2.6 6 1.4 6 4.2 0 2.3-4 2.2-5.8.8" stroke="var(--pf)" stroke-width="1.6"/>',
    "calendario": '<rect x="6" y="10" width="48" height="44" rx="4"/><path d="M6 22h48M18 4v12M42 4v12"/><path d="M14 32h6M27 32h6M40 32h6M14 42h6M27 42h6" stroke-width="3"/><rect x="39" y="39" width="8" height="6" fill="currentColor"/>',
    "grafico": '<path d="M6 6v48h48"/><path d="M14 46V34M24 46V26M34 46V32M44 46V16" stroke-width="5"/><path d="M12 28l12-10 10 6 14-14"/>',
    "documento": '<path d="M10 4h24l12 12v38H10z"/><path d="M34 4v12h12M17 26h20M17 34h20M17 42h12"/><circle cx="44" cy="46" r="9"/><path d="M40 46l3 3 6-6"/>',
}


def clase_portada(n):
    return "guia" if n.get("tipo") == "guia" else (n.get("seccion") if n.get("seccion") in ("sueldos", "impuestos") else "profesion")


def portada_html(n, tam="chica"):
    """Portada liviana hecha con HTML y un ícono vectorial: no agrega descargas a la página."""
    import portadas
    icono = ICONOS_SVG[portadas.tema_icono(n)]
    ante = n.get("antetitulo") or ("Guía práctica" if n.get("tipo") == "guia" else "")
    dato = (n.get("dato") or "").strip()
    clave = (n.get("clave") or "").strip()
    titulo = portadas._norm(n.get("titulo", ""))
    nuevo = lambda t: t and portadas._norm(t) not in titulo  # que no repita lo que ya dice el título
    if not clave:  # notas viejas sin frase clave: primera oración del "En corto", acortada
        frase = re.split(r"(?<=[.;:])\s", (n.get("encorto") or "").strip())[0].rstrip(".;:")
        if 25 <= len(frase) and portadas._norm(frase[:35]) not in titulo:
            clave = frase if len(frase) <= 90 else frase[:87].rsplit(" ", 1)[0] + "…"
    if nuevo(clave):
        principal = f'<b class="p-clave">{e(clave)}</b>'
    elif nuevo(dato):
        principal = f'<b class="p-dato">{e(dato)}</b>'
    else:
        # sin dato nuevo: sección y tema chiquitos, sin repetir el título en grande
        sec = "Guía práctica" if n.get("tipo") == "guia" else SECCIONES.get(n.get("seccion"), "")
        tema = (ante.split("|")[0] or "").strip()
        # el tema va grande (y la sección chiquita arriba); si no hay tema, la sección misma va grande
        grande_txt = tema or sec
        principal = (f'<span class="p-sec">{e(sec)}</span>' if tema and portadas._norm(tema) != portadas._norm(sec) else "") + f'<b class="p-tema">{e(grande_txt)}</b>'
    return (f'<div class="portada p-{clase_portada(n)} p-{tam}" aria-hidden="true"><div class="p-tx">{principal}</div>'
            f'<svg viewBox="0 0 60 60" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">{icono}</svg></div>')


def tarjeta(n, grande=False):
    clase = "tarjeta grande" if grande else "tarjeta"
    pastilla = ""
    return f"""<a class="{clase}" href="nota-{n['slug']}.html">{portada_html(n, "grande" if grande else "chica")}<div class="tx">
<p class="ante">{e(n['antetitulo'])}</p><h2>{e(n['titulo'])}</h2>
{f"<p class='resumen'>{e(n['encorto'])}</p>" if grande else ""}
<p class="meta">{pastilla}{fecha_larga(n['fecha'])} · <span data-contador="{n['slug']}"></span></p></div></a>"""


def lateral(notas):
    nicho = [c for j in JURIS if not j.get("portada", True) for c in j.get("venc_claves") or [] if c != "convenio multilateral"]
    prox = [x for x in proximos_vencimientos() if not any(re.search(r"\b" + re.escape(_N(c)) + r"\b", _N(x.get("concepto", ""))) for c in nicho)][:5]
    caja_venc = ('<section class="caja"><h2 class="caja-t">Vencimientos que se vienen</h2><ul class="venc">' + "".join(
        f'<li><span>{e(x["concepto"])}{(" · " + e(x["detalle"])) if x.get("detalle") else ""}</span><b>{fecha_corta(x["fecha"])}</b></li>' for x in prox)
        + '</ul><a class="mas" href="herramientas.html">Ver todos</a></section>') if prox else \
        '<section class="caja"><h2 class="caja-t">Vencimientos</h2><p class="ayuda">Agenda del mes</p><a class="mas" href="herramientas.html">Ver vencimientos</a></section>'
    return _lateral(notas, caja_venc)


# Prueba de CTR desde el 25/11/2026 (Search Console: posición 5-9 y casi 0% de clics). Grupo A: título y descripción que
# prometen lo que Google no muestra en la búsqueda (tabla, evolución, cómo se calcula) en vez de solo el número.
# Grupo de control: el resto de los datos (Monotributo, jubilación, IIBB Santa Fe...). Comparar CTR a las 2 semanas.
SEO_PRUEBA = {  # la página del dato va sin mes (la búsqueda con mes la toma la página del mes, que se indexa desde el 25/11)
    "tope-aportes-base-maxima": ("Tope de aportes y contribuciones (MOPRE): base máxima y mínima hoy",
                                 "Base imponible máxima y mínima vigente para aportes y contribuciones: desde cuándo rige, la norma, la evolución mes a mes y qué meses ya se conocen."),
    "salario-minimo-vital-y-movil": ("Salario mínimo vital y móvil hoy: por mes, por hora y cronograma",
                                     "Cuánto es el salario mínimo vital y móvil vigente, el valor por hora y el cronograma mes a mes que fijó la resolución, con la evolución de los últimos aumentos."),
    "ffep-fondo-enfermedades-profesionales": ("FFEP hoy: importe por trabajador, qué es y cómo vino cambiando",
                                              "Cuánto es el FFEP (Fondo Fiduciario de Enfermedades Profesionales) vigente: importe por trabajador, desde qué período se aplica, la norma y su evolución."),
}


def _titulo_seo(*opciones, largo=65):
    """De varias formas de titular la página (de la más completa a la más corta), la primera que entra sin que Google la corte."""
    ops = [o.replace("  ", " ").strip() for o in opciones if o]
    return next((o for o in ops if len(o) <= largo), min(ops, key=len))


def _corto(v, largo=34):
    """Valor para la barra lateral: sin paréntesis y cortado en una palabra entera (nunca a la mitad)."""
    v = str(v or "").split(" (")[0].strip()
    if len(v) <= largo:
        return v
    for sep in (" y ", " · ", " + ", ", "):
        if sep in v and len(v.split(sep)[0]) <= largo:
            return v.split(sep)[0].strip()
    corte = v[:largo].rsplit(" ", 1)[0].rstrip(" $:·,")
    return corte if re.search(r"\d", corte) else v  # nunca dejar el dato sin el número


def _lateral(notas, caja_venc):
    datos = "".join(
        f'<li><a href="{t["slug"]}.html">{e(t["titulo"])}</a><b>{e(_corto(ajustar_tramo((RESP.get(t["slug"]) or {}).get("datos") or {}).get("valor")))}</b></li>'
        for t in TEMAS_RESP[:6])
    return f"""<aside class="lateral">
<section class="caja"><h2 class="caja-t">Datos del día</h2><ul class="datos-lat">{datos}</ul><a class="mas" href="datos-al-dia.html">Ver todos</a></section>
<a class="caja caja-calc" href="aguinaldo.html"><b>Calculadora de aguinaldo</b><span>Diciembre 2026 · paso a paso, con descuentos y neto</span></a>
<a class="caja caja-calc" href="sueldo-comercio.html"><b>Calculadora de sueldo de Comercio</b><span>Con escala vigente, antigüedad, presentismo y neto</span></a>
{caja_venc}
<section class="caja" id="destacados" hidden><h2 class="caja-t">Destacados de la comunidad</h2><ol id="ranking"></ol></section>
</aside>"""


def bloque(b):
    if "h" in b:
        return f"<h2>{e(b['h'])}</h2>"
    if "p" in b:
        return f"<p>{e(b['p'])}</p>"
    if "tabla" in b:
        filas = b["tabla"]
        cab = "".join(f"<th>{e(c)}</th>" for c in filas[0])
        resto = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in f) + "</tr>" for f in filas[1:])
        return f'<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{resto}</tbody></table></div>'
    if "lista" in b:
        return "<ul>" + "".join(f"<li>{e(x)}</li>" for x in b["lista"]) + "</ul>"
    if "html" in b:
        return html_admin(b["html"])
    return ""


def preguntas_html(n):
    qs = n.get("preguntas") or []
    if not qs:
        return ""
    items = "".join(f"<details><summary>{e(q['p'])}</summary><p>{e(q['r'])}</p></details>" for q in qs)
    return f'<section class="faq"><h2>Preguntas frecuentes</h2>{items}</section>'


def relacionadas(n, notas):
    otras = [x for x in notas if x["slug"] != n["slug"] and x["seccion"] == n["seccion"] and es_guia(x) == es_guia(n)][:4]
    if not otras:
        return ""
    return '<section class="relacionadas"><h2>' + (e(RAMAS_GUIAS.get(n["seccion"], "Otras guías")) if es_guia(n) else 'Más sobre ' + e(SECCIONES[n["seccion"]])) + "</h2><ul>" + "".join(
        f'<li><a href="nota-{x["slug"]}.html">{e(x["titulo"])}</a></li>' for x in otras) + "</ul></section>"


def sitemaps(notas, convenios=()):
    base = sitio_url()
    hoy = datetime.date.today().isoformat()
    # lastmod solo donde la página cambia de verdad todos los días (datos, dólar, índices, portadas);
    # las calculadoras y páginas fijas van sin fecha, para que Google no aprenda a ignorar nuestras fechas
    diarias = list(SECCIONES) + ["datos-al-dia", "dolar-hoy", "herramientas"] + [t["slug"] for t in TEMAS_RESP] + [b[0] for b in BCRA_RESP] + \
        [x[0] for x in DOLARES] + [o[0] for o in OBLIGACIONES] + urls_mes() + QUE_CAMBIA_URLS
    fijas = ["aguinaldo", "convenios", "guias", "calculadoras", "feriados", "sueldo-comercio", "sueldo-casas-particulares", "actualizacion", "dias-habiles",
             "plazo-fijo", "prestamos", "vacaciones", "liquidacion-final", "horas-extras", "iva", "conversor-dolar", "monotributo-categoria", "intereses-arca",
             "actualizacion-alquiler", "embargo-sueldo", "cuando-cambia-cada-dato", "glosario", "comparador-escalas", "agenda-vencimientos",
             "retencion-ganancias", "como-trabajamos", "monotributo-o-responsable-inscripto", "feriado-trabajado", "indices-facpce"] + prox_semestral_urls() + [g["ruta"] for g in EXPLICADO] + ([RUTA_FACIL] if EXPLICADO else []) + JURIS_URLS + PARITARIAS_URLS + FERIADOS_URLS + [f"impuesto-{i[0]}" for i in IMPUESTOS]
    urls = [f"<url><loc>{base}</loc><lastmod>{hoy}</lastmod></url>"] + [
        f"<url><loc>{base}{k}.html</loc><lastmod>{hoy}</lastmod></url>" for k in diarias if k not in PAGINAS_FINAS] + [
        f"<url><loc>{base}{k}.html</loc></url>" for k in fijas if k not in PAGINAS_FINAS] + [
        f"<url><loc>{base}escala-{c['slug']}.html</loc><lastmod>{str(c.get('actualizado') or hoy)[:10]}</lastmod></url>" for c in convenios if f"escala-{c['slug']}" not in PAGINAS_FINAS] + [
        f"<url><loc>{base}nota-{n['slug']}.html</loc><lastmod>{hoy if (es_guia(n) and 'aguinaldo' in n['slug']) else str(n.get('actualizado') or n['fecha'])[:10]}</lastmod></url>" for n in notas]
    mapa = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    limite = datetime.date.today() - datetime.timedelta(days=2)
    recientes = [n for n in notas if str(n["fecha"])[:10] >= limite.isoformat() and not es_guia(n)]
    noticias = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' + "".join(
        f"<url><loc>{base}nota-{n['slug']}.html</loc><news:news><news:publication><news:name>Ramacontable</news:name>"
        f"<news:language>es</news:language></news:publication><news:publication_date>{str(n['fecha'])[:10]}</news:publication_date>"
        f"<news:title>{e(n['titulo'])}</news:title></news:news></url>" for n in recientes) + "</urlset>")
    bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot",
            "Perplexity-User", "Google-Extended", "Bingbot", "Applebot-Extended", "CCBot", "meta-externalagent", "DuckAssistBot"]
    robots = "".join(f"User-agent: {b}\nAllow: /\nDisallow: /admin.html\n\n" for b in bots)
    robots += f"User-agent: *\nAllow: /\nDisallow: /admin.html\n\nSitemap: {base}sitemap.xml\nSitemap: {base}sitemap-noticias.xml\n"
    return mapa, noticias, robots


def llms_txt(notas, convenios):
    """Resumen del sitio para asistentes de IA (formato llms.txt)."""
    base = sitio_url()
    l = ["# Ramacontable", "",
         "> Portal argentino para contadores y liquidadores de sueldos: novedades de ARCA y laborales, escalas salariales "
         "por convenio, vencimientos, guías y calculadoras gratuitas. Cada nota cita la fuente oficial y la fecha.", "",
         "## Secciones", f"- [Sueldos]({base}sueldos.html): novedades laborales y de liquidación de sueldos",
         f"- [Impuestos]({base}impuestos.html): novedades de ARCA y rentas", f"- [Guías]({base}guias.html): guías actualizadas por tema",
         f"- [Vencimientos]({base}herramientas.html): próximos vencimientos impositivos y previsionales",
         f"- [Feriados]({base}feriados.html): feriados del año y cómo se pagan",
         f"- [Datos del día]({base}datos-al-dia.html): datos vigentes revisados todos los días", "",
         "## Datos al día (revisados a diario contra fuentes oficiales)"]
    l += [f"- [{t['titulo']}]({base}{t['slug']}.html): {(((RESP.get(t['slug']) or {}).get('datos') or {}).get('respuesta') or t['pregunta'])[:200]}" for t in TEMAS_RESP]
    l += [f"- [{b[2]}]({base}{b[0]}.html): serie oficial del BCRA" for b in BCRA_RESP]
    l += [f"- [Dólar hoy]({base}dolar-hoy.html): oficial, mayorista, MEP, CCL, tarjeta, cripto y blue (informativo), cada hora"]
    l += [f"- [Vencimientos de {o[1]} por terminación de CUIT]({base}{o[0]}.html)" for o in OBLIGACIONES]
    l += ["", "## Provincias y municipios", f"- [Impuestos provinciales y municipales]({base}provincias-y-municipios.html): Ingresos Brutos y tasas por jurisdicción"]
    l += [f"- [{j['titulo']}]({base}{j['ruta']}.html)" for j in JURIS]
    l += [f"- [{t['titulo']}]({base}{t['ruta']}.html): {t['descripcion']}" for j in JURIS for t in (j.get("tablas") or []) + (j.get("paginas") or [])]
    l += ["", "## Escalas salariales por convenio"]
    l += [f"- [{c.get('nombre', c['slug'])}]({base}escala-{c['slug']}.html)" for c in convenios]
    l += ["", "## Calculadoras"] + [f"- [{t}]({base}{a}.html)" for a, t in [
        ("sueldo-comercio", "Sueldo de Comercio"), ("sueldo-casas-particulares", "Casas particulares"), ("aguinaldo", "Aguinaldo"),
        ("liquidacion-final", "Liquidación final e indemnización"), ("vacaciones", "Vacaciones"), ("horas-extras", "Horas extras"),
        ("feriado-trabajado", "Feriado trabajado"), ("indices-facpce", "Índices FACPCE para ajuste por inflación (RT 6)"), ("actualizacion", "Actualización por CER, UVA, dólar, inflación y tasas"), ("dias-habiles", "Días hábiles"),
        ("plazo-fijo", "Plazo fijo"), ("prestamos", "Préstamos"), ("iva", "IVA"), ("conversor-dolar", "Conversor de dólar"),
        ("monotributo-categoria", "Categoría del Monotributo"), ("intereses-arca", "Intereses resarcitorios de ARCA"),
        ("actualizacion-alquiler", "Actualización de alquiler (ICL / IPC)"), ("embargo-sueldo", "Embargo de sueldo (Decreto 484/87)"),
        ("retencion-ganancias", "Retención de Ganancias sobre el sueldo"), ("agenda-vencimientos", "Agenda de vencimientos por CUIT"),
        ("comparador-escalas", "Aumentos por convenio vs. inflación"), ("glosario", "Glosario contable, impositivo y laboral")]]
    l += [f"- [Planilla de vacaciones para varios empleados (Excel)]({base}planillas/planilla-vacaciones.xlsx): días por antigüedad, art. 153, valor del día y total"]
    l += [f"- [Planilla de liquidación final e indemnización (Excel)]({base}planillas/planilla-liquidacion-final.xlsx): días trabajados, SAC, vacaciones no gozadas, art. 245, preaviso e integración"]
    l += [f"- [Planilla de aguinaldo para varios empleados (Excel)]({base}planillas/planilla-aguinaldo-varios-empleados.xlsx): mejor remuneración del semestre, proporcional por días, tope del SAC, descuentos y neto"]
    l += ["", "## Últimas notas"] + [f"- [{n['titulo']}]({base}nota-{n['slug']}.html): {(n.get('encorto') or '')[:200]}"
                                     for n in notas[:40]]
    return "\n".join(l) + "\n"


def urls_indexnow(notas, convenios, minutos=90):
    """Páginas nuevas o cambiadas en la última hora y media, para avisar a Bing/IndexNow."""
    base = sitio_url()
    lim = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutos)).isoformat()[:16]
    def nuevo(v):
        v = str(v or "")
        return len(v) > 10 and v.replace(" ", "T")[:16] >= lim
    u = [f"{base}nota-{n['slug']}.html" for n in notas if nuevo(n.get("actualizado")) or nuevo(n.get("fecha"))]
    u += [f"{base}escala-{c['slug']}.html" for c in convenios if nuevo(c.get("actualizado"))]
    u += [f"{base}{sl}.html" for sl, r in RESP.items() if nuevo(r.get("cambiado"))]
    return ([base] if u else []) + u


def bloque_aportes(n, aportes):
    """Guías: opiniones + explicaciones por separado. Novedades: un solo bloque de comentarios, con explicaciones opcionales."""
    if es_guia(n):
        return GUIA_APORTES.replace("@PASOS@", pasos_estaticos(aportes or []))
    return f'''<section class="bloque-op bloque-com" id="opiniones"><span id="aplica"></span>
<h2 class="tit-bloque">Comentarios <span data-n="total">0</span></h2>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="Dejá tu comentario o explicación sobre «{e(n.get("titulo") or "este tema")}»" required></textarea>
<button class="btn">Publicar</button></form>
<button type="button" class="link-expl" data-nuevo-paso>¿Querés subir una explicación con tablas, imágenes o PDF? Hacelo acá</button>
<div id="lista-pasos" class="lista lista-expl">{pasos_estaticos(aportes or [])}</div>
<div id="lista-opiniones" class="lista"></div>
<button type="button" class="btn sec ancho" id="ver-mas-op" hidden>Ver más comentarios</button>
<span hidden data-n="pasos">0</span><span hidden data-n="opiniones">0</span>
</section>'''


GUIA_APORTES = """<section class="bloque-op" id="opiniones">
<h2 class="tit-bloque">Opiniones <span data-n="opiniones">0</span></h2>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="¿Algo para sumar o corregir en esta guía?" required></textarea><button class="btn">Publicar opinión</button></form>
<div id="lista-opiniones" class="lista"></div>
<button type="button" class="btn sec ancho" id="ver-mas-op" hidden>Ver más opiniones</button>
</section>
<section class="bloque-aplica" id="aplica">
<h2 class="tit-bloque">¿Cómo se aplica? <span data-n="pasos">0</span></h2>
<p class="ayuda">Explicá cómo se aplica esta guía: un caso práctico, una liquidación de ejemplo o una aclaración de la norma. Las más votadas quedan arriba.</p>
<div id="lista-pasos" class="lista">@PASOS@</div>
<button class="btn ancho" data-nuevo-paso>Subir una explicación</button>
</section>
"""


# ---------- Datos al día (páginas respuesta) ----------
RESP = {}       # slug -> fila de Supabase (datos verificados por la fábrica)
TEMAS_RESP = []  # respuestas/temas.json
BCRA_RESP = [   # páginas que se arman solas con la serie oficial del BCRA
    ("valor-uva-hoy", "uva", "Valor de la UVA hoy", "¿Cuánto vale la UVA hoy?", "UVA", "sueldos"),
    ("cer-hoy", "cer", "Valor del CER hoy", "¿Cuánto vale el CER hoy?", "CER", "impuestos"),
    ("inflacion-mensual-ipc", "ipc", "Inflación mensual (IPC)", "¿Cuánto fue la última inflación mensual?", "inflación", "impuestos"),
    ("icl-alquileres-hoy", "icl", "Índice ICL para alquileres hoy", "¿Cuánto vale el ICL hoy?", "ICL", "impuestos"),
    ("tasa-badlar-hoy", "badlar", "Tasa BADLAR hoy", "¿Cuál es la tasa BADLAR hoy?", "BADLAR", "impuestos"),
    ("tasa-tamar-hoy", "tamar", "Tasa TAMAR hoy", "¿Cuál es la tasa TAMAR hoy?", "TAMAR", "impuestos"),
    ("tasa-plazo-fijo-hoy", "plazo_fijo", "Tasa de plazo fijo hoy", "¿Cuánto paga un plazo fijo hoy?", "tasa de plazo fijo", "impuestos"),
]
DOLARES = [  # cotizaciones de mercado (DolarAPI); historial de ArgentinaDatos
    ("dolar-oficial-hoy", "oficial", "Dólar oficial hoy (Banco Nación)", "dólar oficial"),
    ("dolar-mayorista-hoy", "mayorista", "Dólar mayorista hoy", "dólar mayorista"),
    ("dolar-mep-hoy", "bolsa", "Dólar MEP hoy", "dólar MEP"),
    ("dolar-ccl-hoy", "contadoconliqui", "Dólar contado con liquidación (CCL) hoy", "dólar CCL"),
    ("dolar-tarjeta-hoy", "tarjeta", "Dólar tarjeta hoy", "dólar tarjeta"),
    ("dolar-cripto-hoy", "cripto", "Dólar cripto hoy", "dólar cripto"),
    ("dolar-blue-hoy", "blue", "Dólar blue hoy", "dólar blue"),
]
DOLAR = {}


def cargar_respuestas():
    global RESP, TEMAS_RESP
    try:
        TEMAS_RESP = json.load(open(os.path.join(RAIZ, "respuestas", "temas.json"), encoding="utf-8"))
    except Exception:
        TEMAS_RESP = []
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if url and key:
        try:
            req = urllib.request.Request(url + "/rest/v1/respuestas?select=*", headers={"apikey": key, "Authorization": "Bearer " + key})
            RESP = {r["slug"]: r for r in json.load(urllib.request.urlopen(req, timeout=30))}
        except Exception as ex:
            print("Aviso: no se pudieron leer los datos al día:", ex)
    # datos iniciales verificados a mano: se muestran hasta que la fábrica cargue el suyo en Supabase
    for archivo in glob.glob(os.path.join(RAIZ, "respuestas", "inicial", "*.json")) + glob.glob(os.path.join(RAIZ, "respuestas", "prueba-*.json")):
        r = json.load(open(archivo, encoding="utf-8"))
        RESP.setdefault(r["slug"], r)


def _fecha_hora(iso):
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(datetime.timezone(datetime.timedelta(hours=-3)))
        return f"{d.day}/{d.month}/{d.year} a las {d.hour:02d}:{d.minute:02d}"
    except Exception:
        return fecha_larga(str(iso)[:10])


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _num(x):
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ultimo_serie(clave):
    try:
        sr = json.load(open(os.path.join(SALIDA, "datos", f"serie-{clave}.json"), encoding="utf-8"))
        return sr["f"][-1], sr["v"][-1]
    except Exception:
        return None, None


def _ipc_fechas():
    try:
        return json.load(open(os.path.join(RAIZ, "respuestas", "ipc.json"), encoding="utf-8")).get("fechas", [])
    except Exception:
        return []


def ajustar_tramo(d):
    """Si el dato trae los tramos mes a mes ya fijados (salario mínimo), se toma solo el del mes actual."""
    tr = ((d.get("estructurado") or {}).get("tramos") or [])
    mes = datetime.date.today().strftime("%Y-%m")
    vig = [x for x in tr if str(x.get("desde", "")) <= mes and x.get("mensual")]
    if not vig:
        return d
    x = max(vig, key=lambda z: z["desde"])
    d = dict(d, monto=x["mensual"], mes_vigente=mes,
             valor=f"$ {_num(x['mensual'])} por mes" + (f" ($ {_num(x['hora'])} la hora)" if x.get("hora") else ""))
    sig = [z for z in tr if str(z.get("desde", "")) > mes]
    if sig:
        z = min(sig, key=lambda q: q["desde"])
        d["proximo"] = f"$ {_num(z['mensual'])} desde {MESES[int(z['desde'][5:7]) - 1]} {z['desde'][:4]}"
    return d


def bloque_dato_hoy(t, d):
    """Lo que cambia de verdad todos los días: equivalencias con el dólar y la UVA de hoy, días que faltan y cálculo anticipado."""
    hoy = datetime.date.today()
    filas = []
    monto = d.get("monto")
    dol = ((DOLAR.get("actual") or {}).get("oficial") or {}).get("venta")
    if isinstance(monto, (int, float)) and monto > 0:
        if dol:
            filas.append(f"Equivale a <b>US$ {_num(monto / dol)}</b> al dólar oficial de hoy (Banco Nación, $ {_num(dol)}).")
        fu, uva = _ultimo_serie("uva")
        if uva:
            filas.append(f"Equivale a <b>{_num(monto / uva)} UVA</b> (UVA del {fecha_corta(fu)}: $ {_num(uva)}).")
    c = t.get("ciclo") or {}
    if c.get("tipo") == "movilidad":
        prox = [x for x in _ipc_fechas() if x >= hoy.isoformat()]
        if prox:
            dias = (datetime.date.fromisoformat(prox[0]) - hoy).days
            filas.append(f"Próximo dato de inflación del INDEC: <b>{fecha_corta(prox[0])}</b> ({'hoy' if dias == 0 else f'faltan {dias} días'}). ANSES confirma los nuevos montos en los días siguientes.")
        fi, ipc = _ultimo_serie("ipc")
        mv = d.get("mes_vigente")
        if ipc is not None and fi and mv and isinstance(monto, (int, float)):
            y, m = int(mv[:4]), int(mv[5:7])
            ant = (y, m - 1) if m > 1 else (y - 1, 12)
            if (int(fi[:4]), int(fi[5:7])) == ant:
                sig = (y, m + 1) if m < 12 else (y + 1, 1)
                filas.append(f"<b>Cálculo anticipado para {MESES[sig[1] - 1]} {sig[0]}: $ {_num(monto * (1 + ipc / 100))}</b> "
                             f"(+{_num(ipc)}%, la inflación de {MESES[ant[1] - 1]}), según la fórmula de movilidad mensual del Decreto 274/2024. "
                             "Es un cálculo propio: se confirma con la resolución de ANSES.")
    if t["slug"].startswith("monotributo") or "simplificado" in t["slug"]:
        v = [x for x in proximos_vencimientos() if "monotrib" in x.get("concepto", "").lower()][:2]
        for x in v:
            dias = (datetime.date.fromisoformat(x["fecha"][:10]) - hoy).days
            filas.append(f"{e(x['concepto'])}: <b>{fecha_corta(x['fecha'])}</b> ({'hoy' if dias == 0 else f'faltan {dias} días'}).")
    if not filas:
        return ""
    return (f'<section class="dato-hoy"><h2>El dato hoy, {hoy.day}/{hoy.month}/{hoy.year}</h2><ul>'
            + "".join(f"<li>{x}</li>" for x in filas) + "</ul></section>")


def _proximo_semestral(meses_cambio):
    """(año, mes) del próximo cambio semestral y los 6 meses de inflación que lo definen (el semestre calendario anterior)."""
    hoy = datetime.date.today()
    a, b = meses_cambio  # (2, 8) Monotributo · (1, 7) Ganancias
    if hoy.month < a:
        y, m = hoy.year, a
    elif hoy.month < b:
        y, m = hoy.year, b
    else:
        y, m = hoy.year + 1, a
    sem = [(y - 1, k) for k in range(7, 13)] if m == a else [(y, k) for k in range(1, 7)]
    return (y, m), sem


def _ipc_meses():
    """{(año, mes): % mensual} del IPC (serie del BCRA ya bajada en datos/serie-ipc.json)."""
    try:
        sr = json.load(open(os.path.join(SALIDA, "datos", "serie-ipc.json"), encoding="utf-8"))
        return {(int(f[:4]), int(f[5:7])): float(v) for f, v in zip(sr["f"], sr["v"])}
    except Exception:
        return {}


PROX_SEMESTRAL = {  # páginas del próximo cambio semestral (pedido de Ramiro, 26/11: adelantarse a la búsqueda)
    "monotributo": {"meses": (2, 8), "dato": "monotributo-categorias-vigentes", "ruta": "monotributo-{mes}-{anio}",
                    "titulo": "Monotributo {mes} {anio}: cuánto aumentan las cuotas y los topes",
                    "regla": "Los montos del Monotributo (cuotas y topes de facturación de cada categoría) se actualizan dos veces por año, desde el 1 de febrero y el 1 de agosto, con la inflación (IPC del INDEC) acumulada del semestre anterior.",
                    "antes": "En agosto de 2026 la suba fue del 16,85%: la inflación acumulada del primer semestre de 2026, la misma que se usó para actualizar Ganancias en julio.",
                    "link": ("monotributo-categorias-vigentes.html", "Categorías y cuotas vigentes del Monotributo")},
    "ganancias": {"meses": (1, 7), "dato": "ganancias-deducciones-sueldos", "ruta": "ganancias-{mes}-{anio}",
                  "titulo": "Ganancias {mes} {anio}: cuánto suben las deducciones y la escala",
                  "regla": "Las deducciones personales y los tramos de la escala de Ganancias para empleados y jubilados se actualizan en enero y en julio con la inflación (IPC del INDEC) del semestre anterior.",
                  "antes": "En julio de 2026 la actualización fue del 16,85%, la inflación acumulada del primer semestre de 2026.",
                  "link": ("ganancias-deducciones-sueldos.html", "Deducciones y escala de Ganancias vigentes")},
}


def pagina_proximo_semestral(clave, notas):
    cfg = PROX_SEMESTRAL[clave]
    (y, m), sem = _proximo_semestral(cfg["meses"])
    mes_txt = MESES[m - 1]
    ruta = cfg["ruta"].format(mes=mes_txt, anio=y)
    ipc = _ipc_meses()
    conocidos = [(k, ipc[k]) for k in sem if k in ipc]
    nom = lambda k: f"{MESES[k[1] - 1]} {k[0]}"
    acum = 1.0
    for _, v in conocidos:
        acum *= 1 + v / 100
    partes = [f"<p>{e(cfg['regla'])}</p>", f"<p>Para {mes_txt} de {y} cuenta la inflación de <b>{nom(sem[0])} a {nom(sem[-1])}</b>.</p>"]
    filas, estim = "", ""
    if conocidos:
        filas = "".join(f"<tr><td>{nom(k).capitalize()}</td><td>{_num(v)}%</td></tr>" for k, v in conocidos)
        faltan = [nom(k) for k in sem if k not in ipc]
        pct = _num((acum - 1) * 100)
        partes.append(f"<p>Con la inflación ya publicada ({nom(conocidos[0][0])} a {nom(conocidos[-1][0])}), el acumulado va <b>{pct}%</b>."
                      + (f" Faltan {', '.join(faltan)}: el porcentaje final se conoce cuando el INDEC publique {faltan[-1]}." if faltan
                         else " Ya está toda la inflación del semestre: ese es el porcentaje de la actualización.") + "</p>")
        d = ajustar_tramo((RESP.get(cfg["dato"]) or {}).get("datos") or {})
        cats = sorted([c for c in ((d.get("estructurado") or {}).get("categorias") or []) if c.get("ingresos_max")], key=lambda c: c["ingresos_max"])
        if clave == "monotributo" and cats:
            a_, k_ = cats[0], cats[-1]
            rows = [(f"Cuota categoría {a_['categoria']}", a_["cuota_servicios"]), (f"Tope anual categoría {a_['categoria']}", a_["ingresos_max"]),
                    (f"Cuota categoría {k_['categoria']} (servicios)", k_["cuota_servicios"]), (f"Tope anual categoría {k_['categoria']}", k_["ingresos_max"])]
            estim = ('<h2>Estimación con la inflación publicada hasta hoy</h2><div class="tabla"><table><thead><tr><th></th><th>Hoy</th>'
                     f'<th>Estimado {mes_txt} {y}</th></tr></thead><tbody>'
                     + "".join(f"<tr><td>{e(n)}</td><td>$ {_num(v)}</td><td>$ {_num(v * acum)}</td></tr>" for n, v in rows)
                     + f'</tbody></table></div><p class="nota-chica">Estimación propia: valores de hoy × {pct}% de inflación acumulada'
                     + (" (todavía faltan meses del semestre)" if faltan else "") + ". Los montos oficiales los publica ARCA.</p>")
    partes.append(f"<p>{e(cfg['antes'])}</p>")
    tabla_ipc = (f'<h2>Inflación del semestre</h2><div class="tabla"><table><thead><tr><th>Mes</th><th>IPC mensual</th></tr></thead><tbody>{filas}</tbody></table></div>' if filas else "")
    titulo = cfg["titulo"].format(mes=mes_txt, anio=y)
    qs = [{"p": f"¿Cuándo cambia {'el Monotributo' if clave == 'monotributo' else 'Ganancias'} en {mes_txt} {y}?",
           "r": f"Desde el 1 de {mes_txt} de {y}, con la inflación de {nom(sem[0])} a {nom(sem[-1])}."}]
    if conocidos:
        qs.append({"p": f"¿Cuánto va a aumentar {'el Monotributo' if clave == 'monotributo' else 'Ganancias'} en {mes_txt} {y}?",
                   "r": f"Con la inflación publicada hasta {nom(conocidos[-1][0])}, el acumulado va {_num((acum - 1) * 100)}%. El porcentaje final sale con la inflación de {nom(sem[-1])}."})
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a> / <a href="{cfg['link'][0]}">{e(cfg['link'][1])}</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
{''.join(partes)}
{tabla_ipc}{estim}
<p><a class="btn" href="{cfg['link'][0]}">{e(cfg['link'][1])} →</a></p>
{preguntas_html({"preguntas": qs})}
<p class="aviso">Información de carácter general. Las estimaciones son propias y se reemplazan por los valores oficiales cuando ARCA los publica.</p>
</div>{lateral(notas)}</div>"""
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False) + "</script>"
    desc = (f"Cuánto suben {'las cuotas y topes del Monotributo' if clave == 'monotributo' else 'las deducciones y la escala de Ganancias'} en {mes_txt} {y}: "
            f"inflación de {nom(sem[0])} a {nom(sem[-1])}, acumulado hasta hoy y estimación.")
    return ruta, pagina(titulo, cuerpo, "datos-al-dia", desc[:160], ruta + ".html", ld,
                        [("Datos del día", "datos-al-dia.html"), (titulo.split(":")[0], ruta + ".html")])


def prox_semestral_urls():
    return [PROX_SEMESTRAL[k]["ruta"].format(mes=MESES[_proximo_semestral(PROX_SEMESTRAL[k]["meses"])[0][1] - 1],
                                             anio=_proximo_semestral(PROX_SEMESTRAL[k]["meses"])[0][0]) for k in PROX_SEMESTRAL]


def mes_links(t):
    pm = next((p for p in PAGINAS_MES if p[1] == t["slug"]), None)
    if not pm:
        return ""
    return ('<section class="relacionadas"><h2>Por mes</h2><ul>' + "".join(
        f'<li><a href="{pm[0]}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html">{e(pm[2].format(mes=MESES[int(m[5:]) - 1] + " " + m[:4]))}</a></li>' for m in _meses_paginas()) + "</ul></section>")


def pagina_respuesta(t, r, notas, aportes=None, extra=""):
    d = ajustar_tramo((r or {}).get("datos") or {})
    hoy = datetime.date.today()
    hoy_blq = bloque_dato_hoy(t, d) if d.get("valor") else ""
    mes = f"{MESES[hoy.month - 1]} {hoy.year}"
    titulo_h = f"{t['titulo']} ({mes})" if (" hoy" in t["titulo"] or t.get("seccion") == "provincias") else f"{t['titulo']} hoy ({mes})"
    claves = [c.lower() for c in t.get("claves", [])]
    rel = [n for n in notas if any(c in (n["titulo"] + " " + n.get("encorto", "")).lower() for c in claves)][:5]
    if d.get("valor"):
        caja = (f'<div class="resp-caja"><span class="resp-p">{e(t["pregunta"])}</span><b class="resp-v">{e(d["valor"])}</b>'
                f'<p>{e(d.get("respuesta", ""))}</p>'
                + (f'<p class="resp-meta">Rige desde: <b>{e(d["vigencia"])}</b></p>' if d.get("vigencia") else "")
                + (f'<p class="resp-meta">Próximo cambio: <b>{e(d["proximo"])}</b></p>' if d.get("proximo") else "")
                + (f'<p class="resp-meta">Norma: {e(d["norma"])}</p>' if d.get("norma") else "") + "</div>")
        revisado = (f'<p class="resp-rev">✔ <b>Vigente hoy, {hoy.day}/{hoy.month}/{hoy.year}.</b> Última verificación con las fuentes: {_fecha_hora(r.get("revisado"))} ('
                    + ", ".join(e(f["nombre"]) for f in (r.get("fuentes") or [])) + ")."
                    + (f" Cuándo cambia: {e(t['cuando'])}." if t.get("cuando") else "") + "</p>")
    else:
        caja = f'<div class="resp-caja"><span class="resp-p">{e(t["pregunta"])}</span><p>Estamos verificando el dato vigente con las fuentes oficiales. Se publica apenas lo confirmen al menos dos fuentes.</p></div>'
        revisado = ""
    cuerpo = "".join(f"<p>{e(x)}</p>" for x in d.get("explicacion") or [])
    if d.get("tabla"):
        cuerpo += bloque({"tabla": d["tabla"]})
    hist = r.get("historial") if r else []
    if hist and len(hist) > 1:
        cuerpo += "<h2>Cómo fue cambiando</h2><div class=\"tabla\"><table><thead><tr><th>Desde</th><th>Valor</th><th>Norma</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{fecha_corta(h['fecha'])}</td><td>{e(h['valor'])}</td><td>{e(h.get('norma') or '')}</td></tr>" for h in hist) + "</tbody></table></div>"
    # «guia» en respuestas/temas.json: explicación fija verificada (qué es, quién entra, cómo se paga), además del dato que cambia
    cuerpo += "".join(bloque(x) for x in t.get("guia") or [])
    if t["slug"] == "ganancias-deducciones-sueldos":
        cuerpo += bloque_ganancias_anual()
    faq = preguntas_html({"preguntas": (d.get("preguntas") or []) + (t.get("preguntas_fijas") or [])})
    fuentes_html = ("<p class=\"fuente\"><b>Fuentes:</b> " + " · ".join(
        f'<a href="{e(f["url"])}" rel="nofollow noopener" target="_blank">{e(f["nombre"])}</a>' for f in (r.get("fuentes") or [])) + "</p>") if r else ""
    rel = rel[:3]
    rel_html = ('<section class="relacionadas novedades-dato"><h2>Últimas novedades sobre el tema</h2><ul>' + "".join(
        f'<li><a href="nota-{x["slug"]}.html">{e(x["titulo"])}</a></li>' for x in rel) + "</ul></section>") if rel else ""
    jur = next((j for j in JURIS if j["slug"] == t.get("jurisdiccion")), None)
    otros = "".join(f'<li><a href="{x["slug"]}.html">{e(x["titulo"])}</a></li>' for x in TEMAS_RESP
                    if x["slug"] != t["slug"] and (x.get("seccion") != "provincias" or x.get("jurisdiccion") == t.get("jurisdiccion")))
    if jur:
        otros = f'<li><a href="{jur["ruta"]}.html">Todo sobre {e(jur["nombre"])}: datos, vencimientos y novedades</a></li><li><a href="provincias-y-municipios.html">Otras provincias y municipios</a></li>' + otros
    miga = (f'<a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{jur["ruta"]}.html">{e(jur["nombre"])}</a>'
            if t.get("seccion") == "provincias" and jur else '<a href="datos-al-dia.html">Datos del día</a>')
    migas_r = ([("Provincias y municipios", "provincias-y-municipios.html"), (jur["titulo_corto"], jur["ruta"] + ".html")]
               if t.get("seccion") == "provincias" and jur else [("Datos del día", "datos-al-dia.html")]) + [(t["titulo"], t["slug"] + ".html")]
    falsa_nota = {"slug": t["slug"], "titulo": t["titulo"].lower()}
    contenido = f"""<div class="grilla"><article class="nota respuesta" data-nota="dato-{t['slug']}">
<div class="nota-contenido">
<p class="miga">{miga}</p>
<h1>{e(titulo_h)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat() if hoy_blq else str((r or {}).get('cambiado') or hoy.isoformat())[:10])}</p>
{caja}{revisado}{hoy_blq}{rel_html}{cuerpo}{extra}{faq}{fuentes_html}
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación.</p>
</div>
{mes_links(t)}{"".join(f'<p class="dato-vigente">📅 <b>Próximo cambio:</b> <a href="{r}.html">{e(PROX_SEMESTRAL[k]["titulo"].format(mes=r.split("-")[-2], anio=r.split("-")[-1]))}</a></p>' for k, r in zip(PROX_SEMESTRAL, prox_semestral_urls()) if PROX_SEMESTRAL[k]["dato"] == t["slug"])}
<section class="relacionadas"><h2>Otros datos del día</h2><ul>{otros}</ul></section>
{bloque_aportes(falsa_nota, aportes)}
</article>{lateral(notas)}</div>"""
    url = sitio_url() + t["slug"] + ".html"
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": titulo_h, "inLanguage": "es-AR",
           "description": d.get("respuesta") or t["pregunta"], "mainEntityOfPage": url,
           "datePublished": str((r or {}).get("cambiado") or hoy.isoformat())[:10], "dateModified": hoy.isoformat() if hoy_blq else str((r or {}).get("cambiado") or hoy.isoformat())[:10],
           "author": {"@type": "Organization", "name": "Redacción Ramacontable", "url": sitio_url()},
           "publisher": {"@type": "Organization", "name": "Ramacontable", "logo": {"@type": "ImageObject", "url": sitio_url() + "icono-512.png"}}}]
    qs = ([{"p": t["pregunta"], "r": d["respuesta"]}] if d.get("respuesta") else []) + list(d.get("preguntas") or [])
    if qs:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]})
    head = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in ld)
    desc = (d.get("respuesta") or t["pregunta"])[:300]
    val_t = d.get("valor") or "dato vigente"
    nom_t = t.get("titulo_corto") or t["titulo"].split(":")[0]
    if t["slug"] in SEO_PRUEBA and d.get("valor"):
        tp, dp = SEO_PRUEBA[t["slug"]]
        return pagina(tp.format(mes=mes), contenido, "datos-al-dia", dp.format(mes=mes), t["slug"] + ".html", head, migas_r)
    return pagina(_titulo_seo(f"{titulo_h}: {val_t}", f"{t['titulo']} ({mes}): {_corto(val_t, 40)}", f"{nom_t} {mes}: {_corto(val_t, 40)}", f"{nom_t}: {_corto(val_t, 40)}", f"{nom_t} ({mes})"), contenido, "impuestos" if t.get("seccion") == "provincias" else "datos-al-dia",
                  desc, t["slug"] + ".html", head, migas_r)


# Texto propio de las páginas de tasas (qué es, para qué sirve). Datos: BCRA (noticia TAMAR, nov. 2024) y La Nación (07/11/2024).
TEXTO_TASAS = {
    "badlar": {
        "que": ["La BADLAR es la tasa promedio que pagan los bancos por los plazos fijos en pesos de $ 1 millón o más, a 30 a 35 días. "
                "La página muestra la serie de bancos privados que publica el Banco Central todos los días hábiles.",
                "Es una de las tasas de referencia más usadas del mercado: sirve para comparar lo que pagan los bancos por los depósitos grandes "
                "y como referencia en préstamos, bonos y otros contratos que pactan una tasa variable."],
        "preguntas": [{"p": "¿Qué es la tasa BADLAR?", "r": "Es la tasa promedio que pagan los bancos por plazos fijos en pesos de $ 1 millón o más, de 30 a 35 días. La publica el BCRA todos los días hábiles."},
                      {"p": "¿Cuál es la diferencia entre la BADLAR y la TAMAR?", "r": "Las dos miden lo que pagan los bancos por depósitos grandes a 30-35 días, pero la BADLAR toma plazos fijos desde $ 1 millón (monto que no se actualiza) y la TAMAR desde un monto mucho más alto que el BCRA actualiza todos los años por inflación."}]},
    "tamar": {
        "que": ["La TAMAR (tasa mayorista de Argentina) es la tasa promedio que pagan los bancos por los plazos fijos en pesos de montos muy grandes, a 30 a 35 días. "
                "El BCRA la publica todos los días desde diciembre de 2024, con datos desde octubre de 2024. La página muestra la serie de bancos privados.",
                "Al principio tomó los depósitos de $ 1.000 millones o más, y ese monto mínimo se actualiza una vez por año por la inflación. "
                "Así sigue midiendo los depósitos realmente grandes aunque haya inflación, algo que no pasa con la BADLAR (su monto de $ 1 millón no cambia)."],
        "preguntas": [{"p": "¿Qué significa TAMAR?", "r": "Tasa Mayorista de Argentina: el promedio de lo que pagan los bancos por plazos fijos en pesos de montos muy grandes, a 30 a 35 días. La publica el BCRA."},
                      {"p": "¿Cuál es la diferencia entre la TAMAR y la BADLAR?", "r": "La TAMAR toma depósitos mucho más grandes (empezó en $ 1.000 millones) y su monto mínimo se actualiza todos los años por inflación; la BADLAR toma depósitos desde $ 1 millón, monto que no cambia."}]},
    "plazo_fijo": {
        "que": ["Es la tasa promedio que pagan los bancos por los plazos fijos en pesos a 30 días, según la serie oficial del Banco Central. "
                "Cada banco fija la suya: algunos pagan más y otros menos que el promedio, y suele cambiar entre clientes y canales (sucursal o home banking).",
                "La tasa se expresa como nominal anual (TNA). Para saber cuánto ganás en 30 días hay que dividirla por 365 y multiplicarla por 30; "
                "si renovás todos los meses los intereses, lo que ganás en el año es la tasa efectiva anual (TEA), que es un poco más alta."],
        "preguntas": [{"p": "¿Cómo calculo cuánto me da un plazo fijo?", "r": "Interés = monto × TNA ÷ 100 × días ÷ 365. Por ejemplo, $ 1.000.000 a 30 días al 30% TNA rinde $ 24.657,53. También lo podés hacer con la calculadora de plazo fijo."},
                      {"p": "¿Qué diferencia hay entre TNA y TEA?", "r": "La TNA es la tasa nominal anual que informa el banco. La TEA supone que renovás el plazo fijo con los intereses durante todo el año, por eso es un poco más alta."}]},
}


def bloque_tasa(clave, f, v, num):
    """Párrafos que cambian solos con la serie: comparación con hace un mes y un año, máximo y mínimo, rendimiento a 30 días e inflación."""
    import bisect
    out = []
    fl = lambda d: f"{d[8:10]}/{d[5:7]}/{d[:4]}"
    fecha, ult = f[-1], v[-1]
    def valor_en(dias):
        objetivo = (datetime.date.fromisoformat(fecha) - datetime.timedelta(days=dias)).isoformat()
        i = bisect.bisect_right(f, objetivo) - 1
        return (f[i], v[i]) if i >= 0 and f[i] >= (datetime.date.fromisoformat(objetivo) - datetime.timedelta(days=7)).isoformat() else None
    for dias, txt in ((30, "hace un mes"), (365, "hace un año")):
        x = valor_en(dias)
        if x:
            dif = ult - x[1]
            out.append(f"{txt.capitalize()} ({fl(x[0])}) estaba en {num(x[1])}%: " + ("sin cambios." if abs(dif) < 0.005 else f"{'subió' if dif > 0 else 'bajó'} {num(abs(dif))} puntos."))
    desde = (datetime.date.fromisoformat(fecha) - datetime.timedelta(days=365)).isoformat()
    anio = [(a, b) for a, b in zip(f, v) if a >= desde]
    if len(anio) > 20:
        mx, mn = max(anio, key=lambda t: t[1]), min(anio, key=lambda t: t[1])
        out.append(f"En los últimos 12 meses, el máximo fue {num(mx[1])}% ({fl(mx[0])}) y el mínimo {num(mn[1])}% ({fl(mn[0])}).")
    mensual = ult * 30 / 365
    tea = ((1 + ult / 100 * 30 / 365) ** (365 / 30) - 1) * 100
    out.append(f"A esta tasa, $ 1.000.000 a 30 días generan $ {num(10000 * mensual)} de interés ({num(mensual)}% en el mes). "
               f"Renovando todos los meses con los intereses, equivale a una tasa efectiva anual (TEA) de {num(tea)}%.")
    try:
        ipc = json.load(open(os.path.join(SALIDA, "datos", "serie-ipc.json"), encoding="utf-8"))
        mes, inf = ipc["f"][-1], ipc["v"][-1]
        out.append(f"Para comparar: la última inflación mensual publicada fue {num(inf)}% ({MESES[int(mes[5:7]) - 1]} {mes[:4]}). "
                   + ("Una tasa mensual por encima de la inflación le gana a la suba de precios; por debajo, pierde contra ella." ))
    except Exception:
        pass
    return out


def pagina_bcra(slug, clave, titulo, pregunta, corto, seccion, notas):
    try:
        sr = json.load(open(os.path.join(SALIDA, "datos", f"serie-{clave}.json"), encoding="utf-8"))
    except Exception:
        return None
    f, v = sr["f"], sr["v"]
    ult, fecha = v[-1], f[-1]
    num = lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if clave == "ipc":
        valor = f"{num(ult)}% ({MESES[int(fecha[5:7]) - 1]} {fecha[:4]})"
        filas = [[f"{MESES[int(a[5:7]) - 1]} {a[:4]}", num(b) + "%"] for a, b in list(zip(f, v))[-12:][::-1]]
        resp = f"La última inflación mensual publicada fue de {num(ult)}%, correspondiente a {MESES[int(fecha[5:7]) - 1]} de {fecha[:4]}, según la serie oficial del BCRA (dato INDEC)."
        cab = ["Mes", "Inflación mensual"]
    elif sr.get("tipo") == "tna" or clave in ("badlar", "tamar", "plazo_fijo"):
        valor = f"{num(ult)}% TNA"
        filas = [[fecha_corta(a), num(b) + "%"] for a, b in list(zip(f, v))[-15:][::-1]]
        resp = f"La tasa {corto} al {fecha_corta(fecha)} es {num(ult)}% nominal anual, según la serie oficial del Banco Central (BCRA)."
        cab = ["Fecha", "TNA"]
    else:
        valor = ("$ " if clave.startswith("dolar") else "") + num(ult)
        filas = [[fecha_corta(a), num(b)] for a, b in list(zip(f, v))[-15:][::-1]]
        resp = f"El valor de {corto} al {fecha_corta(fecha)} es {valor}, según la serie oficial del Banco Central (BCRA)."
        cab = ["Fecha", "Valor"]
    t = {"slug": slug, "titulo": titulo, "pregunta": pregunta, "seccion": seccion, "claves": [corto]}
    extra = TEXTO_TASAS.get(clave) or {}
    explicacion = list(extra.get("que") or []) + (bloque_tasa(clave, f, v, num) if clave in TEXTO_TASAS else []) + [
        f"Dato tomado automáticamente de la API oficial de estadísticas del BCRA. Se actualiza solo cada hora."]
    if clave != "ipc":
        explicacion.append("Para actualizar un monto por " + ("esta tasa" if clave in TEXTO_TASAS else "este índice") + " entre dos fechas, usá la calculadora de actualización.")
    r = {"datos": {"valor": valor, "respuesta": resp, "tabla": [cab] + filas, "explicacion": explicacion, "preguntas": extra.get("preguntas") or []},
         "fuentes": [{"nombre": "BCRA (API de estadísticas)", "url": "https://www.bcra.gob.ar/PublicacionesEstadisticas/Principales_variables.asp"}],
         "revisado": datetime.datetime.now(datetime.timezone.utc).isoformat(), "cambiado": fecha}
    boton = ('<p><a class="btn" href="plazo-fijo.html">Calcular un plazo fijo</a> <a class="btn" href="actualizacion.html">Actualizar un monto por tasa</a></p>' if clave in TEXTO_TASAS
             else '<p><a class="btn" href="actualizacion.html">Ir a la calculadora de actualización</a></p>' if clave != "ipc" else "")
    html = pagina_respuesta(t, r, notas, None, boton)
    return html.replace("La fábrica lo rechequea todos los días.", "Se actualiza solo cada hora.")


def bajar_dolares(destino):
    """Cotizaciones del día (DolarAPI) y últimos 30 días (ArgentinaDatos). Si no responden, no se arman esas páginas."""
    global DOLAR
    import ssl
    def leer(url):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ramacontable-build"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context()))
        except ssl.SSLError:
            import certifi
            return json.load(urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context(cafile=certifi.where())))
    try:
        actual = {d["casa"]: d for d in leer("https://dolarapi.com/v1/dolares")}
    except Exception as ex:
        print("Aviso: no pude leer las cotizaciones del dólar:", ex)
        viejo = respaldo_publicado("dolares.json")
        if viejo and viejo.get("actual"):
            print("Aviso: uso las cotizaciones del dólar ya publicadas")
            DOLAR = viejo
            os.makedirs(destino, exist_ok=True)
            json.dump(DOLAR, open(os.path.join(destino, "dolares.json"), "w", encoding="utf-8"), ensure_ascii=False)
            for clave in ("dolar_mep", "dolar_ccl", "dolar_blue", "dolar_cripto"):
                sr = respaldo_publicado(f"serie-{clave}.json")
                if sr:
                    json.dump(sr, open(os.path.join(destino, f"serie-{clave}.json"), "w", encoding="utf-8"), separators=(",", ":"))
        return
    hist = {}
    for _, casa, *_ in DOLARES:
        try:
            serie = leer(f"https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}")
            hist[casa] = [[x["fecha"], x.get("compra"), x.get("venta")] for x in serie[-30:]]
            clave = {"bolsa": "dolar_mep", "contadoconliqui": "dolar_ccl", "blue": "dolar_blue", "cripto": "dolar_cripto"}.get(casa)
            if clave:
                pts = {x["fecha"][:10]: x["venta"] for x in serie if x.get("venta")}
                fs = sorted(pts)
                nombre = {"dolar_mep": "Dólar MEP", "dolar_ccl": "Dólar contado con liquidación", "dolar_blue": "Dólar blue (informativo)", "dolar_cripto": "Dólar cripto"}[clave]
                json.dump({"nombre": nombre, "tipo": "indice", "f": fs, "v": [pts[x] for x in fs]},
                          open(os.path.join(destino, f"serie-{clave}.json"), "w", encoding="utf-8"), separators=(",", ":"))
        except Exception as ex:
            print(f"Aviso: sin historial del dólar {casa}:", ex)
    DOLAR = {"actual": actual, "hist": hist}
    os.makedirs(destino, exist_ok=True)
    json.dump(DOLAR, open(os.path.join(destino, "dolares.json"), "w", encoding="utf-8"), ensure_ascii=False)


def pagina_dolar(slug, casa, titulo, corto, notas):
    d = (DOLAR.get("actual") or {}).get(casa)
    if not d or not d.get("venta"):
        return None
    num = lambda x: "-" if x is None else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    fecha = str(d.get("fechaActualizacion") or "")
    informal = casa == "blue"
    valor = f"$ {num(d['venta'])} venta"
    resp = (f"El {corto} cotiza a $ {num(d.get('compra'))} para la compra y $ {num(d['venta'])} para la venta"
            f" (actualizado el {_fecha_hora(fecha)}).")
    expl = ["Las cotizaciones de mercado se toman de DolarAPI, que reúne los precios publicados por bancos, la bolsa y las plataformas, y se actualizan solas cada hora en esta página."]
    if informal:
        resp += " Es una cotización informativa del mercado informal: no es un tipo de cambio oficial."
        expl.insert(0, "El dólar blue es la cotización del mercado informal. La publicamos solo como dato informativo, porque es una referencia muy consultada; para operaciones y registraciones contables se usa el tipo de cambio oficial.")
    if casa == "tarjeta":
        expl.insert(0, "El dólar tarjeta es el oficial más las percepciones que se cobran en los consumos en moneda extranjera con tarjeta.")
    tabla = [["Cotización", "Compra", "Venta"]] + [[x.get("nombre", k) + (" (informativa)" if k == "blue" else ""), num(x.get("compra")), num(x.get("venta"))]
                                                    for k, x in (DOLAR.get("actual") or {}).items()]
    h = (DOLAR.get("hist") or {}).get(casa) or []
    filas_h = "".join(f"<tr><td>{fecha_corta(a)}</td><td>{num(c)}</td><td>{num(v)}</td></tr>" for a, c, v in h[::-1])
    extra = (f'<h2>Últimos 30 días</h2><div class="tabla"><table><thead><tr><th>Fecha</th><th>Compra</th><th>Venta</th></tr></thead><tbody>{filas_h}</tbody></table></div>' if filas_h else "")
    extra += '<h2>Todas las cotizaciones de hoy</h2>' + bloque({"tabla": tabla}) + '<p><a href="dolar-hoy.html">Ver todas las cotizaciones del dólar</a></p>'
    t = {"slug": slug, "titulo": titulo, "pregunta": f"¿A cuánto está el {corto} hoy?", "seccion": "impuestos", "claves": [corto]}
    r = {"datos": {"valor": valor, "respuesta": resp, "explicacion": expl},
         "fuentes": [{"nombre": "DolarAPI", "url": "https://dolarapi.com"}, {"nombre": "ArgentinaDatos (historial)", "url": "https://argentinadatos.com"}],
         "revisado": fecha or datetime.datetime.now(datetime.timezone.utc).isoformat(), "cambiado": fecha[:10] or datetime.date.today().isoformat()}
    return pagina_respuesta(t, r, notas, None, extra).replace("<b>Vigente hoy,", "<b>Cotización consultada hoy,")


def pagina_dolar_hub(notas):
    act = DOLAR.get("actual") or {}
    if not act:
        return None
    num = lambda x: "-" if x is None else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    links = {casa: slug for slug, casa, *_ in DOLARES}
    filas = "".join(f'<tr><td><a href="{links.get(k, "dolar-hoy")}.html">{e(x.get("nombre", k))}</a>{" <small>(informativa, mercado informal)</small>" if k == "blue" else ""}</td>'
                    f'<td>{num(x.get("compra"))}</td><td>{num(x.get("venta"))}</td><td>{_fecha_hora(x.get("fechaActualizacion"))}</td></tr>' for k, x in act.items())
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>Dólar hoy: todas las cotizaciones</h1><p class="ayuda">Oficial, mayorista, MEP, contado con liquidación, tarjeta, cripto y blue (cotización informativa del mercado informal). Se actualiza sola cada hora. Fuente: DolarAPI.</p>
<div class="tabla"><table><thead><tr><th>Cotización</th><th>Compra</th><th>Venta</th><th>Actualizado</th></tr></thead><tbody>{filas}</tbody></table></div></div>{lateral(notas)}</div>"""
    return pagina("Dólar hoy: oficial, MEP, CCL, tarjeta, cripto y blue | Ramacontable", cuerpo, "datos-al-dia",
                  "Cotización del dólar hoy en Argentina: oficial Banco Nación, mayorista, MEP, CCL, tarjeta, cripto y blue informativo. Actualizado cada hora.",
                  "dolar-hoy.html", migas=[("Datos del día", "datos-al-dia.html"), ("Dólar hoy", "dolar-hoy.html")])


def grupos_datos():
    """[(id, nombre, [(slug, titulo, valor)])] para el menú, la página general y la barra lateral."""
    val = lambda sl: (ajustar_tramo((RESP.get(sl) or {}).get("datos") or {}).get("valor") or "")
    g = [("sueldos", "Sueldos", [(t["slug"], t["titulo"], val(t["slug"])) for t in TEMAS_RESP if t.get("seccion") == "sueldos"]),
         ("impuestos", "Impuestos", [(t["slug"], t["titulo"], val(t["slug"])) for t in TEMAS_RESP if t.get("seccion") == "impuestos"]),
         ("indices", "Índices y tasas", [(b[0], b[2], "") for b in BCRA_RESP]),
         ("dolar", "Dólar y cripto", [("dolar-hoy", "Dólar hoy: todas las cotizaciones", "")] + [(x[0], x[2], "") for x in DOLARES]),
         ("vencimientos", "Vencimientos del mes por CUIT", [(o[0], o[1], "") for o in OBLIGACIONES]),
         ("calendario", "Calendario", [(f"que-cambia-en-{MESES[int(m[5:]) - 1]}-{m[:4]}", f"Qué cambia en {MESES[int(m[5:]) - 1]} {m[:4]}", "") for m in meses_que_cambia()[-2:]]
          + [("cuando-cambia-cada-dato", "Cuándo cambia cada dato", ""), ("feriados", "Feriados " + str(datetime.date.today().year), "")]
          + [(u, "Feriados " + u[-4:], "") for u in FERIADOS_URLS if u[-4:] != str(datetime.date.today().year)])]
    return g


def ganancias_anual():
    """respuestas/ganancias-anual.json: tabla ANUAL de ARCA (liquidación anual y final, declaración jurada de personas humanas)."""
    try:
        return json.load(open(os.path.join(RAIZ, "respuestas", "ganancias-anual.json"), encoding="utf-8"))
    except Exception:
        return None


def bloque_ganancias_anual():
    g = ganancias_anual()
    if not g:
        return ""
    pesos = lambda x: "$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    filas = [["Concepto", f"Importe anual {g['periodo']}"], ["Ganancia no imponible", pesos(g["ganancia_no_imponible"])],
             ["Cónyuge o conviviente", pesos(g["conyuge"])], ["Hijo", pesos(g["hijo"])], ["Hijo incapacitado para el trabajo", pesos(g["hijo_incapacitado"])],
             ["Deducción especial: trabajo en relación de dependencia y jubilados", pesos(g["especial_dependencia"])],
             ["Deducción especial: trabajo por cuenta propia (autónomos)", pesos(g["especial_cuenta_propia"])],
             ["Deducción especial: nuevos profesionales y emprendedores", pesos(g["especial_nuevos_profesionales"])]]
    esc_ = [["Ganancia neta imponible anual", "Pagarán", "Más el", "Sobre el excedente de"]] + [
        [f"De {pesos(t['desde'])} a {pesos(t['hasta'])}" if t["hasta"] else f"Más de {pesos(t['desde'])}", pesos(t["fijo"]), f"{t['pct']}%", pesos(t["desde"])] for t in g["escala"]]
    fuentes = " · ".join(f'<a href="{e(f["url"])}" rel="nofollow noopener" target="_blank">{e(f["nombre"])}</a>' for f in g.get("fuentes") or [])
    return (f'<h2 id="anual">Tabla anual {g["periodo"]}: liquidación anual y declaración jurada</h2>'
            f'<p>Arriba están los valores de la tabla de retención mensual (julio a diciembre, acumulados a diciembre), que usa el empleador para calcular lo que retiene cada mes. '
            f'Para la liquidación anual y final y para la declaración jurada anual de personas humanas (autónomos, alquileres, inversiones), ARCA publica una tabla anual con valores más altos:</p>'
            + bloque({"tabla": filas}) + "<p>Escala del artículo 94 para la liquidación anual y final:</p>" + bloque({"tabla": esc_})
            + f'<p class="fuente"><b>Tabla anual publicada en {e(g.get("publicada", ""))}:</b> {fuentes}</p>')


def datos_para_calculadoras():
    """sitio/datos/datos-del-dia.json: lo que usan las calculadoras (monto, tablas y fecha de verificación)."""
    out = {}
    for t in TEMAS_RESP:
        r = RESP.get(t["slug"]) or {}
        d = ajustar_tramo(r.get("datos") or {})
        if d.get("valor"):
            out[t["slug"]] = {"valor": d.get("valor"), "monto": d.get("monto"), "estructurado": d.get("estructurado"),
                              "mes_vigente": d.get("mes_vigente"), "norma": d.get("norma"), "revisado": str(r.get("revisado") or "")[:10]}
    g = ganancias_anual()
    if g:
        out["ganancias-anual"] = {"estructurado": {k: v for k, v in g.items() if not k.startswith("_")}, "norma": "Tabla anual de ARCA " + g["periodo"]}
    return out


def proximo_cambio(t):
    hoy = datetime.date.today()
    c = t.get("ciclo") or {}
    if c.get("tipo") == "movilidad":
        prox = [x for x in _ipc_fechas() if x >= hoy.isoformat()]
        return f"INDEC: {fecha_corta(prox[0])}; ANSES, días después" if prox else "Mediados de cada mes"
    for v in c.get("ventanas") or []:
        ini = v.split("/")[0]
        d = hoy.replace(month=int(ini[:2]), day=int(ini[3:]))
        if d < hoy:
            continue
        return f"Desde {MESES[d.month - 1]} {d.year}"
    if c.get("ventanas"):
        ini = c["ventanas"][0].split("/")[0]
        return f"Desde {MESES[int(ini[:2]) - 1]} {hoy.year + 1}"
    if c.get("diario_desde"):
        x = c["diario_desde"]
        return f"Desde {MESES[int(x[5:7]) - 1]} {x[:4]}"
    return "Sin fecha fija"


def bloque_monotributo_calendario():
    """Montos y recategorización del Monotributo juntos (los videos mandan acá con #monotributo).
    Fechas: valores desde el 1/2 y el 1/8 (tabla oficial de ARCA); recategorización hasta el 5/2 y el 5/8 (RG 4309, art. 20, según RG 5546/2024)."""
    hoy = datetime.date.today()
    recat = next(d for d in (datetime.date(hoy.year, 2, 5), datetime.date(hoy.year, 8, 5), datetime.date(hoy.year + 1, 2, 5)) if d >= hoy)
    montos = next(d for d in (datetime.date(hoy.year, 2, 1), datetime.date(hoy.year, 8, 1), datetime.date(hoy.year + 1, 2, 1)) if d > hoy)
    semestre = "julio a diciembre" if recat.month == 2 else "enero a junio"
    d = ajustar_tramo((RESP.get("monotributo-categorias-vigentes") or {}).get("datos") or {})
    tabla = d.get("tabla") or []
    vig = d.get("norma") or ""
    t_html = ""
    if len(tabla) > 1:
        t_html = (f'<h3>Valores de hoy</h3><p class="ayuda">{e(vig)}.</p><div class="tabla mono-tabla"><table><thead><tr>'
                  + "".join(f"<th>{e(c)}</th>" for c in tabla[0]) + "</tr></thead><tbody>"
                  + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in f) + "</tr>" for f in tabla[1:]) + "</tbody></table></div>"
                  + '<p><a class="btn" href="monotributo-categorias-vigentes.html">Ver categorías, topes y cuotas completas →</a> '
                    '<a href="monotributo-categoria.html">¿Qué categoría me toca? Calculadora</a></p>')
    return f"""<section id="monotributo" class="resp-caja mono-cal"><h2>Monotributo: montos y recategorización</h2>
<p>Los montos se actualizan <b>dos veces por año</b> y la recategorización también. Van juntos:</p>
<div class="mono-sem"><div><b>1.er semestre</b><p>💲 Montos nuevos desde el <b>1 de febrero</b></p><p>📋 Recategorización hasta el <b>5 de febrero</b> (por lo facturado de julio a diciembre)</p></div>
<div><b>2.º semestre</b><p>💲 Montos nuevos desde el <b>1 de agosto</b></p><p>📋 Recategorización hasta el <b>5 de agosto</b> (por lo facturado de enero a junio)</p></div></div>
<p><b>Próxima recategorización:</b> hasta el {recat.day} de {MESES[recat.month - 1]} de {recat.year} (por {semestre}). <b>Próximos montos:</b> desde el 1 de {MESES[montos.month - 1]} de {montos.year}.</p>
<p>ARCA suele habilitar el trámite a mediados de enero y de julio, cuando publica los montos nuevos. Se hace en la web de ARCA o en la app ARCA Móvil, mirando lo facturado en los últimos 12 meses. Es obligatoria salvo que sigas en la misma categoría o tengas menos de 6 meses de actividad. La categoría nueva se paga desde febrero o agosto.</p>
{t_html}
<p class="ayuda">Fuentes: tabla oficial de categorías de ARCA y RG 4309 (art. 20, texto según RG 5546/2024).</p>
{"".join(f'<p>¿No sos contador? <a href="{g["ruta"]}.html">{e(g["titulo"])} →</a></p>' for g in EXPLICADO)}</section>"""


HISTORIAL_SHORTS = "https://raw.githubusercontent.com/VRamiroVentura/shorts-fabrica/main/data/historial.json"


def videos_capitulos():
    """{tema_id: id de YouTube} con los capítulos que la fábrica de shorts ya publicó. Si no se puede leer, {} (la página sale sin videos)."""
    import ssl
    try:
        req = urllib.request.Request(HISTORIAL_SHORTS, headers={"User-Agent": "ramacontable-build"})
        try:
            hist = json.load(urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()))
        except ssl.SSLError:
            import certifi
            hist = json.load(urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context(cafile=certifi.where())))
    except Exception as ex:
        print("Aviso: no pude leer el historial de la fábrica de shorts (las guías salen sin videos):", ex)
        return {}
    out = {}
    for h in hist if isinstance(hist, list) else []:
        yt = ((h or {}).get("resultados") or {}).get("youtube") or {}
        if h.get("tema_id") and yt.get("ok") and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", str(yt.get("id") or "")):
            out[h["tema_id"]] = yt["id"]
    return out


def _valores_mono():
    """Topes y cuotas de hoy del Monotributo, tomados del dato vigente del portal (se actualiza solo)."""
    d = ajustar_tramo((RESP.get("monotributo-categorias-vigentes") or {}).get("datos") or {})
    cats = ((d.get("estructurado") or {}).get("categorias")) or []
    if not cats:
        return {}, ""
    pesos = lambda x: "$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    a, k = cats[0], cats[-1]
    v = {"tope_A": ("Tope anual de la categoría A (la más baja)", pesos(a["ingresos_max"])),
         "tope_K": (f"Tope anual de la categoría {k['categoria']} (la más alta)", pesos(k["ingresos_max"])),
         "cuota_A": ("Cuota mensual de la categoría A", pesos(a["cuota_servicios"])),
         "cuota_K_servicios": (f"Cuota mensual de la categoría {k['categoria']} (servicios)", pesos(k["cuota_servicios"])),
         "cuota_K_bienes": (f"Cuota mensual de la categoría {k['categoria']} (venta de productos)", pesos(k["cuota_bienes"]))}
    return v, d.get("norma") or ""


def pagina_explicado_facil(g, notas, videos):
    """Guía para gente común (no contadores) armada con datos verificados de las series de videos; los montos salen del dato vigente."""
    vals, vig = _valores_mono()
    hoy = datetime.date.today()
    recat = next(d for d in (datetime.date(hoy.year, 2, 5), datetime.date(hoy.year, 8, 5), datetime.date(hoy.year + 1, 2, 5)) if d >= hoy)
    indice, cuerpo, grupo_act, calc_js = "", "", None, set()
    for i, sec in enumerate(g["secciones"], 1):
        if sec.get("grupo") and sec["grupo"] != grupo_act:
            grupo_act = sec["grupo"]
            indice += f'<li class="ef-grupo">{e(grupo_act)}</li>'
            cuerpo += f'<h2 class="ef-titgrupo">{e(grupo_act)}</h2>'
        indice += f'<li><a href="#{sec["id"]}">{e(sec["titulo"])}</a></li>'
        vid = next((videos[t] for t in sec.get("tema_ids") or [] if t in videos), None)
        video = (f'<div class="ef-video"><iframe src="https://www.youtube.com/embed/{vid}" title="{e(sec["titulo"])}" loading="lazy" '
                 'allow="accelerometer; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe></div>') if vid else ""
        txt = "".join(f"<p>{e(t)}</p>" for t in sec.get("texto") or [])
        if sec.get("tabla"):
            txt += tabla_html(sec["tabla"])
        if sec.get("calculadora"):
            h_calc, js = calculadora_embebida(sec["calculadora"])
            txt += h_calc
            calc_js |= set(js)
        if sec.get("datos"):
            txt += caja_datos(sec["datos"])
        clave = "".join(f"<li>{e(c)}</li>" for c in sec.get("clave") or [])
        caja = ""
        filas = [vals[k] for k in sec.get("valores") or [] if k in vals]
        if filas:
            caja = ('<div class="ef-valores"><b>Valores de hoy</b><ul>' + "".join(f"<li>{e(a)}: <b>{e(b)}</b></li>" for a, b in filas)
                    + f'</ul><small>{e(vig)}. Se actualizan solos cuando ARCA publica los nuevos.</small></div>')
        if sec.get("recategorizacion"):
            caja += f'<div class="ef-valores"><b>Próximo vencimiento:</b> hasta el {recat.day} de {MESES[recat.month - 1]} de {recat.year}.</div>'
        disc = ""
        if sec.get("discute"):
            dd = sec["discute"]
            disc = (f'<section class="ef-discute" id="lo-que-se-discute"><h3>{e(dd["titulo"])}</h3><div class="ef-posturas">'
                    + "".join(f"<div><b>{e(a)}</b><p>{e(b)}</p></div>" for a, b in dd["posturas"])
                    + '</div><p><b>Qué revisar en tu cuenta:</b></p><ul class="ef-check">' + "".join(f"<li>{e(x)}</li>" for x in dd["revisar"]) + "</ul></section>")
        dest = sec.get("destino")
        boton = f'<p><a class="btn" href="{e(dest[0])}">{e(dest[1])} →</a></p>' if dest and dest[0] != "#lo-que-se-discute" else ""
        cuerpo += (f'<section class="ef-sec" id="{sec["id"]}"><h2>{e(sec["titulo"])}</h2>{video}{txt}'
                   + (f'<div class="ef-clave"><b>Lo clave</b><ul>{clave}</ul></div>' if clave else "") + f"{caja}{disc}{boton}</section>")
    qs = [{"p": p_, "r": r_} for p_, r_ in g.get("preguntas") or []]
    contenido = f"""<div class="grilla"><article class="nota explicado" data-nota="{e(g["ruta"])}"><div class="nota-contenido">
<p class="miga"><a href="guias.html">Guías</a> / <a href="{RUTA_FACIL}.html">{e(SECCION_FACIL)}</a></p>
<p class="ante">{e(SECCION_FACIL)} · {e(SECCION_FACIL_SUB)}</p>
<h1>{e(g["titulo"])}</h1>
<p class="encorto ef-para"><b>¿Para quién es?</b> {e(g["para_quien"])}</p>
{f'<p class="ef-pro"><a href="{e(g["profesional"][0])}">{e(g["profesional"][1])} →</a></p>' if g.get("profesional") else ""}
<nav class="ef-indice"><b>En esta guía</b><ol>{indice}</ol></nav>
{cuerpo}
{preguntas_html({"preguntas": qs})}
{caja_contacto(g.get("contacto") or g["titulo"])}
<p class="aviso">Información general para orientarte. Cada caso puede tener particularidades: ante la duda, consultá con un contador.</p>
</div>{bloque_aportes({"slug": g["ruta"], "titulo": g["titulo"]}, None)}</article>{lateral(notas)}</div>"""
    url = sitio_url() + g["ruta"] + ".html"
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": g["titulo"][:110], "description": g["descripcion"], "inLanguage": "es-AR",
           "mainEntityOfPage": url, "dateModified": hoy.isoformat(),
           "author": {"@type": "Organization", "name": "Redacción Ramacontable", "url": sitio_url()},
           "publisher": {"@type": "Organization", "name": "Ramacontable", "logo": {"@type": "ImageObject", "url": sitio_url() + "icono-512.png"}}},
          {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
              {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}]
    ld += [{"@context": "https://schema.org", "@type": "VideoObject", "name": sec["titulo"], "description": " ".join(sec.get("texto") or [])[:300],
            "thumbnailUrl": f"https://i.ytimg.com/vi/{videos[t]}/hqdefault.jpg", "embedUrl": f"https://www.youtube.com/embed/{videos[t]}",
            "uploadDate": hoy.isoformat()} for sec in g["secciones"] for t in (sec.get("tema_ids") or [])[:1] if t in videos]
    head = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in ld)
    contenido += "".join(f'<script src="{x}"></script>' for x in sorted(calc_js))
    return pagina(f'{g["seo_titulo"]} | Ramacontable', contenido, "guias", g["descripcion"], g["ruta"] + ".html", head,
                  [("Guías", "guias.html"), (SECCION_FACIL, RUTA_FACIL + ".html"), (g["titulo"][:60], g["ruta"] + ".html")])


def calculadora_embebida(nombre):
    """El formulario de una calculadora del portal (paginas/<nombre>.html) dentro de otra página, con sus mismos scripts.
    Devuelve (html, [scripts])."""
    try:
        t = open(os.path.join(RAIZ, "paginas", nombre + ".html"), encoding="utf-8").read()
    except OSError:
        return f'<p><a class="btn" href="{nombre}.html">Abrir la calculadora →</a></p>', []
    m = re.search(r'(<form id="calc[^"]*".*?</form>)\s*(<section id="resultado[^"]*"[^>]*>\s*</section>)', t, re.S)
    if not m:
        return f'<p><a class="btn" href="{nombre}.html">Abrir la calculadora →</a></p>', []
    js = re.findall(r'<script src="([^"]+)"></script>', t)
    return (f'<div class="ef-calc">{m.group(1)}{m.group(2)}<p class="ayuda"><a href="{nombre}.html">Abrir la calculadora completa →</a></p></div>'), js


def caja_datos(slugs):
    """Valores de hoy de datos del portal (se actualizan solos), con link a cada página."""
    filas = []
    for sl in slugs:
        t = next((x for x in TEMAS_RESP if x["slug"] == sl), None)
        v = ajustar_tramo((RESP.get(sl) or {}).get("datos") or {}).get("valor") if t else None
        if t and v:
            filas.append(f'<li><a href="{sl}.html">{e(t.get("titulo_corto") or t["titulo"].split(":")[0])}</a>: <b>{e(_corto(v, 60))}</b></li>')
    return ('<div class="ef-valores"><b>Valores de hoy</b><ul>' + "".join(filas) + '</ul><small>Se actualizan solos cuando salen los nuevos.</small></div>') if filas else ""


def caja_contacto(tema):
    """Botón para que la gente escriba su consulta (abre un mail con el asunto puesto)."""
    asunto = urllib.parse.quote(f"Consulta: {tema}")
    return (f'<section class="ef-contacto"><h2>¿Te quedó una duda?</h2><p>Escribinos tu consulta y te orientamos. '
            f'Contanos tu caso con el mayor detalle posible (sin datos personales sensibles como claves o números de cuenta).</p>'
            f'<p><a class="btn" href="mailto:{MAIL}?subject={asunto}">✉️ Escribinos tu consulta</a></p></section>')


SECCION_FACIL = "Guías fáciles"
SECCION_FACIL_SUB = "para no profesionales"
RUTA_FACIL = "guias-faciles"


def pagina_guias_para_todos(notas):
    """Portada de la sección de guías para no contadores."""
    items = "".join(f'<a class="ult sec-sueldos" href="{g["ruta"]}.html"><b>{e(g["titulo"])}</b><span class="ult-res">{e(g.get("tarjeta") or g["descripcion"])}</span></a>'
                    for g in EXPLICADO)
    cuerpo = (f'<div class="grilla"><section><p class="miga"><a href="guias.html">Guías</a></p><h1 class="titsec">{e(SECCION_FACIL)}, {e(SECCION_FACIL_SUB)}</h1>'
              '<p class="ayuda">Explicado fácil, sin palabras raras: para empleados, emprendedores, monotributistas y cualquiera que quiera entender '
              'sus vacaciones, su aguinaldo, sus impuestos o su recibo de sueldo. Cada guía tiene ejemplos, los valores de hoy y un botón para escribirnos.</p>'
              f'<div class="ult-g">{items}</div>'
              '<p class="ayuda" style="margin-top:1.2em">¿Sos contador o liquidás sueldos? <a href="guias.html">Ver las guías profesionales →</a></p>'
              f'</section>{lateral(notas)}</div>')
    return pagina(f"{SECCION_FACIL} para no profesionales: sueldo, impuestos y trámites | Ramacontable", cuerpo, "guias",
                  "Guías explicadas fácil para empleados, emprendedores y monotributistas: vacaciones, aguinaldo, monotributo, Ganancias y más, con ejemplos y calculadoras.",
                  RUTA_FACIL + ".html", migas=[("Guías", "guias.html"), (SECCION_FACIL, RUTA_FACIL + ".html")])


def con_anio(x, salto=None):
    """Reemplaza {anio} y {anio_ant} en textos de guías permanentes. Con salto «MM-DD», desde esa fecha ya muestra el año que viene
    (ej. Ganancias en el sueldo pasa a 2027 en diciembre). Así la dirección queda fija y el título se actualiza solo."""
    hoy = datetime.date.today()
    anio = hoy.year + (1 if salto and hoy.strftime("%m-%d") >= salto else 0)
    if isinstance(x, str):
        return x.replace("{anio}", str(anio)).replace("{anio_ant}", str(anio - 1))
    if isinstance(x, list):
        return [con_anio(v, salto) for v in x]
    if isinstance(x, dict):
        return {k: con_anio(v, salto) for k, v in x.items()}
    return x


_DATO_RE = re.compile(r"\{dato:([a-z0-9-]+):([a-z_]+)(?:\|([^}]*))?\}")


def _valor_dato(campo, v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if campo.startswith("alicuota"):
            return (f"{v:g}".replace(".", ",")) + "%"
        return "$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(v)


def con_datos(g):
    """{dato:slug:campo|respaldo} en guías fáciles: muestra el valor que la fábrica mantiene al día en «Datos del día»
    (respuestas, campo estructurado). Si al dato le falta alguno de los campos que usa la guía, se usan TODOS los respaldos
    de ese dato, para no mezclar valores de años distintos."""
    texto = json.dumps({k: v for k, v in g.items() if not k.startswith("_")}, ensure_ascii=False)
    pedidos = {}
    for sl, campo, _ in _DATO_RE.findall(texto):
        pedidos.setdefault(sl, set()).add(campo)
    usar = {}
    for sl, campos in pedidos.items():
        est = (((RESP.get(sl) or {}).get("datos") or {}).get("estructurado")) or {}
        usar[sl] = est if all(est.get(c) not in (None, "") for c in campos) else {}
        if not usar[sl]:
            print(f"Aviso: al dato {sl} le falta algún campo de {sorted(campos)}: la guía usa los valores de respaldo.")
    def rep(m):
        sl, campo, resp = m.group(1), m.group(2), m.group(3) or ""
        v = usar.get(sl, {}).get(campo)
        return _valor_dato(campo, v) if v not in (None, "") else resp
    def rec(x):
        if isinstance(x, str):
            return _DATO_RE.sub(rep, x)
        if isinstance(x, list):
            return [rec(v) for v in x]
        if isinstance(x, dict):
            return {k: (v if k.startswith("_") else rec(v)) for k, v in x.items()}
        return x
    return rec(g)


def cargar_explicado():
    out = []
    for ruta in sorted(glob.glob(os.path.join(RAIZ, "explicado", "*.json"))):
        try:
            g = json.load(open(ruta, encoding="utf-8"))
            out.append(con_datos(con_anio(g, g.get("salto_anio"))))
        except Exception as ex:
            print("Aviso: no pude leer", ruta, ex)
    out.sort(key=lambda g: (g.get("orden", 99), g["ruta"]))
    return out


EXPLICADO = []


def pagina_calendario_datos(notas):
    filas = "".join(f'<tr><td><a href="{t["slug"]}.html">{e(t["titulo"])}</a></td><td>{e(t.get("cuando", ""))}</td><td>{e(proximo_cambio(t))}</td></tr>' for t in TEMAS_RESP)
    filas += ('<tr><td><a href="dolar-hoy.html">Dólar (oficial, MEP, CCL, tarjeta)</a></td><td>Días hábiles de 10 a 17</td><td>Se actualiza cada hora</td></tr>'
              '<tr><td><a href="dolar-cripto-hoy.html">Dólar cripto</a></td><td>Todos los días, las 24 horas</td><td>Se actualiza cada hora</td></tr>'
              '<tr><td><a href="valor-uva-hoy.html">UVA, CER, ICL y tasas</a></td><td>El BCRA los publica todos los días</td><td>Todos los días</td></tr>')
    ipc = "".join(f"<li>{fecha_corta(x)}</li>" for x in _ipc_fechas() if x >= datetime.date.today().isoformat())
    qs = [{"p": "¿Cuándo aumentan las jubilaciones?", "r": "Todos los meses, por la inflación de dos meses antes (Decreto 274/2024). El INDEC publica la inflación a mitad de mes y ANSES confirma los nuevos haberes en los días siguientes."},
          {"p": "¿Cuándo se actualiza el Monotributo?", "r": "Dos veces por año: los montos nuevos rigen desde el 1 de febrero y el 1 de agosto. ARCA los publica a mediados de enero y de julio."},
          {"p": "¿Cuándo es la recategorización del Monotributo?", "r": "Dos veces por año: hasta el 5 de febrero (por lo facturado de julio a diciembre) y hasta el 5 de agosto (por lo facturado de enero a junio). Es obligatoria salvo que se siga en la misma categoría o se tengan menos de 6 meses de actividad."},
          {"p": "¿Cuándo cambian las deducciones de Ganancias?", "r": "Dos veces por año: hay tablas para enero a junio y para julio a diciembre."}]
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>Cuándo cambia cada dato: calendario de actualizaciones</h1>
<p class="ayuda">Cuándo se actualizan la jubilación, la AUH, el Monotributo, Ganancias, el salario mínimo y los demás datos que usamos todos los días.</p>
{bloque_monotributo_calendario()}
<h2>Todos los datos</h2>
<div class="tabla"><table><thead><tr><th>Dato</th><th>Cuándo cambia</th><th>Próximo cambio</th></tr></thead><tbody>{filas}</tbody></table></div>
{('<h2>Próximas publicaciones de la inflación (INDEC)</h2><ul>' + ipc + '</ul>') if ipc else ''}
{preguntas_html({"preguntas": qs})}
<p class="aviso">Las fechas de ANSES y Ganancias son estimadas según cómo se publicaron en los últimos años. Las del Monotributo salen de la normativa de ARCA y las del INDEC, de su calendario oficial.</p>
</div>{lateral(notas)}</div>"""
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False) + "</script>"
    return pagina("Cuándo cambia cada dato: recategorización, jubilaciones y AUH | Ramacontable", cuerpo, "datos-al-dia",
                  "Montos del Monotributo desde el 1/2 y el 1/8, recategorización hasta el 5/2 y el 5/8, y cuándo cambian jubilaciones, AUH, Ganancias y salario mínimo.",
                  "cuando-cambia-cada-dato.html", ld, [("Datos del día", "datos-al-dia.html"), ("Cuándo cambia cada dato", "cuando-cambia-cada-dato.html")])


def pagina_glosario(notas):
    try:
        terms = json.load(open(os.path.join(RAIZ, "glosario", "terminos.json"), encoding="utf-8"))
    except Exception:
        return None
    terms.sort(key=lambda x: unicodedata.normalize("NFD", x[1].lower()))
    letras, items = [], []
    for slug, nombre, defi, link in terms:
        l = unicodedata.normalize("NFD", nombre[0].upper())[0]
        if l not in letras:
            letras.append(l); items.append(f'<h2 id="letra-{l}">{l}</h2>')
        items.append(f'<div class="termino" id="{slug}"><h3>{e(nombre)}</h3><p>{e(defi)}</p>'
                     + (f'<p><a href="{link}">Ver más →</a></p>' if link else "") + "</div>")
    indice = " ".join(f'<a href="#letra-{l}">{l}</a>' for l in letras)
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><h1>Glosario contable, impositivo y laboral</h1>
<p class="ayuda">Los términos que más se usan al liquidar sueldos e impuestos en Argentina, explicados en una línea y con el enlace a su dato o calculadora.</p>
<p class="indice-letras">{indice}</p>{''.join(items)}</div>{lateral(notas)}</div>"""
    ld = {"@context": "https://schema.org", "@type": "DefinedTermSet", "name": "Glosario contable, impositivo y laboral", "url": sitio_url() + "glosario.html",
          "hasDefinedTerm": [{"@type": "DefinedTerm", "name": n, "description": d, "url": f"{sitio_url()}glosario.html#{sl}"} for sl, n, d, _ in terms]}
    head = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    return pagina("Glosario contable e impositivo: SAC, SMVM, base imponible, Monotributo y más | Ramacontable", cuerpo, "",
                  "Glosario de términos contables, impositivos y laborales de Argentina: aguinaldo, base imponible, SIPA, F.931, Monotributo, ICL, UVA y más.",
                  "glosario.html", head, [("Glosario", "glosario.html")])


def pagina_comparador(convenios, notas):
    fi, _ = _ultimo_serie("ipc")
    ipc12 = None
    try:
        sr = json.load(open(os.path.join(SALIDA, "datos", "serie-ipc.json"), encoding="utf-8"))
        c = 1.0
        for v in sr["v"][-12:]:
            c *= 1 + v / 100
        ipc12 = (c - 1) * 100 if len(sr["v"]) >= 12 else None
    except Exception:
        pass
    hace = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    filas = []
    for cv in sorted(convenios, key=lambda x: x["nombre"]):
        h = [x for x in (cv.get("historial") or []) if str(x.get("fecha", "")) >= hace and isinstance(x.get("aumento_pct"), (int, float))]
        if h:
            acum = 1.0
            for x in sorted(h, key=lambda z: z["fecha"]):
                acum *= 1 + x["aumento_pct"] / 100
            acum = (acum - 1) * 100
            dif = f"{acum - ipc12:+.1f} p.p.".replace(".", ",") if ipc12 is not None else "-"
            filas.append((acum, f'<tr><td><a href="escala-{cv["slug"]}.html">{e(cv["nombre"])}</a></td><td>{len(h)}</td><td><b>{_num(acum)}%</b></td><td>{dif}</td><td>{e(h[-1].get("periodo", ""))}</td></tr>'))
        else:
            filas.append((-999, f'<tr><td><a href="escala-{cv["slug"]}.html">{e(cv["nombre"])}</a></td><td>-</td><td colspan="3">Juntando datos: se completa con cada acuerdo nuevo</td></tr>'))
    filas.sort(key=lambda x: -x[0])
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="convenios.html">Escalas por convenio</a></p>
<h1>Comparador de aumentos por convenio vs. inflación</h1>
<p class="ayuda">Cuánto aumentaron los básicos de cada convenio en los últimos 12 meses, acuerdo por acuerdo, comparado con la inflación del mismo período{f' ({_num(ipc12)}% según el INDEC, hasta {MESES[int(fi[5:7]) - 1]} {fi[:4]})' if ipc12 is not None and fi else ''}.</p>
<div class="tabla"><table><thead><tr><th>Convenio</th><th>Acuerdos</th><th>Aumento 12 meses</th><th>Contra la inflación</th><th>Último acuerdo</th></tr></thead><tbody>{''.join(f for _, f in filas)}</tbody></table></div>
<p class="aviso">El aumento acumulado sale de los porcentajes de cada acuerdo publicado; no incluye sumas no remunerativas ni adicionales. El comparador se completa a medida que la fábrica registra cada acuerdo nuevo.</p>
</div>{lateral(notas)}</div>"""
    return pagina("Aumentos por convenio vs. inflación: comparador de paritarias | Ramacontable", cuerpo, "sueldos",
                  "Compará cuánto aumentó cada convenio colectivo en los últimos 12 meses contra la inflación: Comercio, UOCRA, UOM, Sanidad y más.",
                  "comparador-escalas.html", migas=[("Escalas por convenio", "convenios.html"), ("Comparador", "comparador-escalas.html")])


OBLIGACIONES = [  # páginas fijas de vencimientos por terminación de CUIT (salen de la agenda confirmada)
    ("vencimiento-931", "F.931: aportes y contribuciones de empleadores", ["931", "empleador"], "sueldos"),
    ("vencimiento-casas-particulares", "Casas particulares (F.102)", ["casas particulares", "f.102", "102"], "sueldos"),
    ("vencimiento-autonomos", "Autónomos", ["autónomo", "autonomo"], "sueldos"),
    ("vencimiento-monotributo", "Monotributo", ["monotribut"], "impuestos"),
    ("vencimiento-iva", "IVA", ["iva"], "impuestos"),
    ("vencimiento-iibb-arba", "Ingresos Brutos ARBA", ["arba", "ingresos brutos"], "impuestos"),
]


def _terminaciones(detalle):
    t = str(detalle or "").lower()
    if "cuit" not in t:
        return None
    m = t.split("cuit", 1)[1]
    ds = []
    def rango(x):
        ds.extend(range(int(x.group(1)), int(x.group(2)) + 1)); return " "
    m = re.sub(r"(\d)\s*(?:a|al|-|–)\s*(\d)", rango, m)
    ds += [int(c) for c in re.findall(r"\d", m)]
    return sorted(set(ds)) or None


def pagina_obligacion(slug, nombre, claves, seccion, notas):
    hoy = datetime.date.today()
    items = [x for x in proximos_vencimientos() if any(c in (x.get("concepto", "")).lower() for c in claves)]
    provincial = lambda c: bool(re.search(r"\b(iibb|ingresos brutos|convenio multilateral|sifere)\b", _N(c)))
    items = [x for x in items if ("arba" in _N(x.get("concepto", ""))) if slug == "vencimiento-iibb-arba"] if slug == "vencimiento-iibb-arba" \
        else [x for x in items if not provincial(x.get("concepto", ""))]
    if slug == "vencimiento-iva":
        items = [x for x in items if "iva" in re.findall(r"[a-záéíóú]+", x.get("concepto", "").lower())]
    meses = {}
    for x in items:
        meses.setdefault(x["fecha"][:7], []).append(x)
    bloques = ""
    for mes in sorted(meses)[:2]:
        filas = []
        for x in sorted(meses[mes], key=lambda z: z["fecha"]):
            t = _terminaciones(x.get("detalle"))
            dias = (datetime.date.fromisoformat(x["fecha"][:10]) - hoy).days
            falta = "hoy" if dias == 0 else (f"faltan {dias} días" if dias > 0 else "")
            filas.append(f'<tr><td>{"Terminación " + ", ".join(map(str, t)) if t else "Todos"}</td><td>{e(x.get("concepto", ""))}{(" · " + e(x["detalle"])) if x.get("detalle") and not t else ""}</td>'
                         f'<td><b>{fecha_corta(x["fecha"])}</b></td><td>{falta}</td></tr>')
        bloques += (f'<h2>{MESES[int(mes[5:7]) - 1].capitalize()} {mes[:4]}</h2><div class="tabla"><table><thead><tr><th>CUIT</th><th>Obligación</th><th>Vence</th><th></th></tr></thead>'
                    f'<tbody>{"".join(filas)}</tbody></table></div>')
    if not bloques:
        bloques = '<div class="resp-caja"><p>Las fechas de este mes están en verificación: se publican cuando las confirman al menos dos fuentes.</p></div>'
    mes_txt = f"{MESES[hoy.month - 1]} {hoy.year}"
    ant = MESES[hoy.month - 2] if hoy.month > 1 else "diciembre"
    titulo = f"Vencimientos de {nombre}: {mes_txt}, por terminación de CUIT"
    faq = ""
    if slug == "vencimiento-931":
        # como se busca: "fecha de pago de aportes noviembre", "vencimiento 931 octubre"
        titulo = f"Fecha de pago de aportes de {mes_txt}: vencimiento del F.931 por terminación de CUIT"
        este = sorted(meses.get(hoy.strftime("%Y-%m"), []), key=lambda z: z["fecha"])
        resp = ("; ".join(f"{('CUIT ' + ', '.join(map(str, _terminaciones(x.get('detalle')) or []))) if _terminaciones(x.get('detalle')) else 'todos'}: {fecha_corta(x['fecha'])}" for x in este)
                or "las fechas están en verificación")
        faq = preguntas_html({"preguntas": [
            {"p": f"¿Cuándo se pagan los aportes en {mes_txt}?", "r": f"En {mes_txt} se pagan los aportes y contribuciones del período {ant} (F.931). Fechas por terminación de CUIT del empleador: {resp}."},
            {"p": "¿Qué período se paga cada mes?", "r": "Cada mes se presenta y paga el F.931 de las remuneraciones del mes anterior: en noviembre se pagan los aportes de octubre, en diciembre los de noviembre, y así."}]})
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat())}</p>
<p class="ayuda">Fechas confirmadas por al menos dos fuentes (o por Ignacio Online), ordenadas por terminación de CUIT. Si un vencimiento cae en día inhábil, la fecha ya figura corrida.</p>
{f'<p>En {mes_txt} vence el pago de los aportes y contribuciones del período <b>{ant}</b>.</p>' if slug == "vencimiento-931" else ""}
{bloques}{faq}
<p><a class="btn sec" href="agenda-vencimientos.html">Armar mi agenda por CUIT y bajarla al calendario →</a></p>
<p class="aviso">Información de carácter general. Verificá siempre en el calendario oficial de ARCA o del organismo.</p>
</div>{lateral(notas)}</div>"""
    tit_pag = (f"Vencimiento F.931 {mes_txt}: pago de aportes por CUIT" if slug == "vencimiento-931"
               else f"Vencimiento {re.sub(r' [(][^)]*[)]$', '', nombre)} {mes_txt} por terminación de CUIT")
    if len(tit_pag) > 62:
        tit_pag = tit_pag.replace(" por terminación de CUIT", " por CUIT")
    desc = (f"Fecha de pago de aportes y contribuciones de {mes_txt} (período {ant}): vencimientos del F.931 según la terminación de CUIT del empleador."
            if slug == "vencimiento-931" else f"Fechas de vencimiento de {nombre} de {mes_txt} según la terminación de CUIT, confirmadas con varias fuentes.")
    return pagina(f"{tit_pag} | Ramacontable", cuerpo, "datos-al-dia", desc,
                  slug + ".html", migas=[("Datos del día", "datos-al-dia.html"), (f"Vencimientos {nombre}", slug + ".html")])


def bloque_aguinaldo(n, notas):
    """Guías del aguinaldo: cuenta regresiva, tope del SAC y novedades del tema (cambian de verdad cada día)."""
    if not (es_guia(n) and "aguinaldo" in n.get("slug", "")):
        return ""
    hoy = datetime.date.today()
    vto = datetime.date(hoy.year, 6, 30) if hoy.month <= 6 else datetime.date(hoy.year, 12, 18)
    dias = (vto - hoy).days
    cuota = "primera" if vto.month == 6 else "segunda"
    if dias > 0:
        cuenta = f"Faltan <b>{dias} días</b> para el vencimiento de la {cuota} cuota del aguinaldo ({fecha_corta(vto.isoformat())})."
    elif dias == 0:
        cuenta = f"<b>Hoy vence</b> la {cuota} cuota del aguinaldo."
    else:
        cuenta = f"La {cuota} cuota del aguinaldo venció el {fecha_corta(vto.isoformat())}: si no se pagó, el trabajador puede intimar el pago."
    r = RESP.get("tope-aportes-base-maxima") or {}
    d = r.get("datos") or {}
    bm = (d.get("estructurado") or {}).get("base_maxima")
    mv = d.get("mes_vigente") or ""
    tope = ""
    if bm:
        mes_txt = f"{MESES[int(mv[5:7]) - 1]} {mv[:4]}" if mv else "vigente"
        tope = (f"<li>Tope de aportes para el aguinaldo (50% de la base máxima de {mes_txt}): <b>$ {_num(bm / 2)}</b>."
                + ("" if mv[5:7] == f"{vto.month:02d}" else f" La base de {MESES[vto.month - 1]} se publica en los próximos días y se actualiza acá sola.") + "</li>")
    nov = [x for x in notas if x["slug"] != n["slug"] and "aguinaldo" in (x["titulo"] + " " + x.get("encorto", "")).lower()][:5]
    lis = "".join(f'<li><a href="nota-{x["slug"]}.html">{e(x["titulo"])}</a> <small>{fecha_corta(str(x["fecha"])[:10])}</small></li>' for x in nov)
    nombre_mes = "junio" if vto.month == 6 else "diciembre"
    dia_sem = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][vto.weekday()]
    return (f'<section class="dato-hoy"><h2>Aguinaldo de {nombre_mes} {vto.year}: se paga hasta el {dia_sem} {vto.day} de {nombre_mes}</h2>'
            f'<p class="nota-chica">Actualizado el {hoy.day}/{hoy.month}/{hoy.year}</p><ul><li>{cuenta}</li>{tope}</ul>'
            + '<p><a class="btn" href="planillas/planilla-aguinaldo-varios-empleados.xlsx" download>Descargar planilla de aguinaldo para varios empleados (Excel)</a></p>'
            + (f"<h3>Novedades del aguinaldo</h3><ul>{lis}</ul>" if lis else "") + "</section>")


PARITARIAS_URLS = []
PAGINAS_FINAS = set()  # páginas sin dato todavía: noindex y fuera del sitemap hasta que tengan contenido
NOI = '<meta name="robots" content="noindex,follow">'
FERIADOS_URLS = []
QUE_CAMBIA_URLS = []
MES_DESDE = "2026-11"  # primer mes con páginas propias (quedan publicadas para siempre)
PAGINAS_MES = [  # (prefijo de la URL, dato del día, título, pregunta)
    ("aumento-jubilados", "jubilacion-minima-y-bono", "Aumento de jubilados {mes}: cuánto cobra la mínima", "¿Cuánto cobra un jubilado con la mínima en {mes}?"),
    ("auh", "asignaciones-familiares-auh", "AUH {mes}: cuánto se cobra por hijo", "¿Cuánto es la AUH en {mes}?"),
    ("tope-aportes", "tope-aportes-base-maxima", "Tope de aportes {mes} (MOPRE)", "¿Cuál es el tope de aportes y contribuciones (MOPRE) de {mes}?"),
    ("salario-minimo", "salario-minimo-vital-y-movil", "Salario mínimo vital y móvil {mes}", "¿Cuánto es el salario mínimo en {mes}?"),
    ("seguro-de-desempleo", "seguro-de-desempleo-montos", "Seguro de desempleo {mes}: montos", "¿Cuánto se cobra de desempleo en {mes}?"),
    ("ffep", "ffep-fondo-enfermedades-profesionales", "FFEP {mes}: importe por trabajador", "¿Cuánto es el FFEP en {mes}?"),
    ("aportes-autonomos", "autonomos-categorias-aportes", "Aportes de autónomos {mes}: cuánto se paga por categoría", "¿Cuánto paga un autónomo en {mes}?"),
    ("puam", "jubilacion-minima-y-bono", "PUAM {mes}: cuánto se cobra con el bono", "¿Cuánto cobra la PUAM en {mes}?"),
]


def _puam(v):
    """PUAM = 80% de la jubilación mínima (Ley 27.260); el bono lo cobran igual (Decreto del bono de cada mes)."""
    if not v:
        return v
    m = _monto_txt(v)
    if not m:
        return None
    bono = re.search(r"bono\s*\$\s*([\d.]+(?:,\d+)?)", str(v))
    txt = f"$ {_num(m * 0.8)}" + (f" + bono $ {bono.group(1)}" if bono else (" + bono a confirmar" if "bono" in str(v) else ""))
    return txt + (" (cálculo anticipado)" if "anticipado" in str(v) else "")


TRANSFORMA_MES = {"puam": _puam}


def _meses_paginas():
    hoy = datetime.date.today()
    y, m = int(MES_DESDE[:4]), int(MES_DESDE[5:])
    fin = (hoy.year + (hoy.month // 12), hoy.month % 12 + 1)  # hasta el mes que viene
    out = []
    while (y, m) <= fin:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def valor_de_mes(t, mes):
    """(valor, texto, estado) del dato para un mes dado: vigente, tramo ya fijado, cálculo anticipado o historial."""
    r = RESP.get(t["slug"]) or {}
    d = r.get("datos") or {}
    tr = (d.get("estructurado") or {}).get("tramos") or []
    x = [z for z in tr if str(z.get("desde", "")) <= mes]
    if x:
        z = max(x, key=lambda q: q["desde"])
        v = f"$ {_num(z['mensual'])} por mes" + (f" ($ {_num(z['hora'])} la hora)" if z.get("hora") else "")
        return v, f"Monto fijado por {d.get('norma') or 'la resolución vigente'}.", "fijado"
    if d.get("mes_vigente") == mes or (not d.get("mes_vigente") and mes == datetime.date.today().strftime("%Y-%m")):
        return d.get("valor"), d.get("respuesta") or "", "vigente"
    mv = d.get("mes_vigente")
    if mv and mes > mv and (t.get("ciclo") or {}).get("tipo") == "movilidad" and isinstance(d.get("monto"), (int, float)):
        fi, ipc = _ultimo_serie("ipc")
        y, m = int(mv[:4]), int(mv[5:])
        ant = (y, m - 1) if m > 1 else (y - 1, 12)
        sig = f"{y + (m // 12)}-{m % 12 + 1:02d}"
        if ipc is not None and fi and (int(fi[:4]), int(fi[5:7])) == ant and mes == sig:
            pre = str(d.get("valor") or "").split("$")[0].strip()  # «Máxima», «Categoría I:», «AUH»
            return (f"{pre + ' ' if pre else ''}$ {_num(d['monto'] * (1 + ipc / 100))}" + (" + bono a confirmar" if "bono" in str(d.get("valor") or "") else "") + " (cálculo anticipado)",
                    f"Cálculo propio con la fórmula de movilidad (Decreto 274/2024): inflación de {MESES[ant[1] - 1]} {_num(ipc)}%. Se confirma con la resolución de ANSES.", "anticipado")
        return None, "El monto de este mes todavía no se publicó: se conoce unos días después del dato de inflación del INDEC.", "pendiente"
    for h in r.get("historial") or []:
        if str(h.get("fecha", ""))[:7] in (mes, ):
            return h.get("valor"), f"Valor publicado en {MESES[int(mes[5:]) - 1]} ({h.get('norma') or ''}).", "historico"
    return None, "Para este mes el dato se publica en cuanto lo confirmen las fuentes.", "pendiente"


def _monto_txt(v):
    m = re.search(r"\$\s*([\d.]+(?:,\d+)?)", str(v or ""))
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def bloque_evolucion(t):
    """Últimos valores del dato con su fecha y la variación entre los dos últimos (sale del historial verificado)."""
    r = RESP.get(t["slug"]) or {}
    hist = sorted([h for h in r.get("historial") or [] if h.get("valor") and h.get("fecha")], key=lambda h: str(h["fecha"]))[-4:]
    if not hist:
        return ""
    filas = "".join(f'<tr><td>{fecha_larga(str(h["fecha"])[:10])}</td><td>{e(h["valor"])}</td><td>{e(h.get("norma") or "")}</td></tr>' for h in hist[::-1])
    var = ""
    if len(hist) >= 2:
        a, b = _monto_txt(hist[-2]["valor"]), _monto_txt(hist[-1]["valor"])
        if a and b and a > 0:
            var = (f'<p>Con el último cambio, del {fecha_larga(str(hist[-1]["fecha"])[:10])}, el valor pasó de <b>{e(_corto(hist[-2]["valor"], 40))}</b> '
                   f'a <b>{e(_corto(hist[-1]["valor"], 40))}</b>: una variación de <b>{f"{(b / a - 1) * 100:+.2f}".replace(".", ",")}%</b>.</p>')
    cuando = f'<p><b>Cuándo cambia:</b> {e(t["cuando"])}.</p>' if t.get("cuando") else ""
    return (f'<section class="evolucion"><h2>Cómo viene este dato</h2>{var}{cuando}'
            f'<div class="tabla"><table><thead><tr><th>Desde</th><th>Valor</th><th>Norma</th></tr></thead><tbody>{filas}</tbody></table></div></section>')


def bloque_dato_mes(t, estado):
    """Lo propio de cada dato (verificado): tabla vigente, explicación y preguntas. La tabla solo si el mes es el vigente."""
    d = ajustar_tramo((RESP.get(t["slug"]) or {}).get("datos") or {})
    partes = ""
    if estado == "vigente" and d.get("tabla"):
        partes += "<h2>Detalle vigente</h2>" + tabla_html(d["tabla"])
    if d.get("explicacion"):
        partes += "<h2>Para entenderlo</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in d["explicacion"]) + "</ul>"
    qs = [q for q in d.get("preguntas") or [] if isinstance(q, dict) and q.get("p") and q.get("r")]
    if qs:
        partes += preguntas_html({"preguntas": qs})
    if d.get("norma"):
        partes += f'<p class="fuente"><b>Norma:</b> {e(d["norma"])}</p>'
    return partes


USO_DATO_MES = {  # para qué sirve cada dato (texto fijo verificado) y adónde seguir
    "tope-aportes": ('Si el sueldo bruto supera la base máxima, los aportes personales se calculan sobre esa base máxima y no sobre todo el sueldo.',
                     ("nota-guia-liquidar-sueldo-paso-a-paso.html", "Cómo liquidar un sueldo paso a paso")),
    "salario-minimo": ('Además de ser el piso de lo que se puede pagar por una jornada completa, se usa como referencia para calcular cuánto se puede embargar de un sueldo.',
                       ("embargo-sueldo.html", "Calculadora de embargo de sueldo")),
    "ffep": ('Lo paga el empleador por cada trabajador y se declara en el F.931, junto con la cuota de la ART.',
             ("vencimiento-931.html", "Vencimiento del F.931 de este mes")),
    "aumento-jubilados": ('La jubilación mínima se actualiza todos los meses por la inflación de dos meses antes (Decreto 274/2024). El bono se fija aparte, por decreto, cada mes.',
                          ("cuando-cambia-cada-dato.html", "Cuándo cambia cada dato")),
    "auh": ('La AUH y las asignaciones familiares se actualizan todos los meses con la misma movilidad que las jubilaciones.',
            ("cuando-cambia-cada-dato.html", "Cuándo cambia cada dato")),
    "seguro-de-desempleo": ('Los montos del seguro de desempleo van atados al salario mínimo vital y móvil: cuando cambia el salario mínimo, cambian también.',
                            ("salario-minimo-vital-y-movil.html", "Salario mínimo vital y móvil hoy")),
    "puam": ('La PUAM (Pensión Universal para el Adulto Mayor, Ley 27.260) es el 80% de la jubilación mínima y se actualiza con la misma movilidad mensual. Sus titulares también cobran el bono que se fija cada mes por decreto.',
             ("aumento-jubilados-" + "{mes_url}" + ".html", "Jubilación mínima de este mes")),
    "aportes-autonomos": ('Los aportes de los autónomos se actualizan todos los meses con la movilidad jubilatoria. Cada uno paga según su categoría.',
                          ("monotributo-o-responsable-inscripto.html", "Calculadora: ¿Monotributo o Responsable Inscripto?")),
}


def texto_mes(pref, t, mes, valor):
    """Texto propio de la página del mes: comparación con el mes anterior y el siguiente, para qué sirve y adónde seguir."""
    y, m = int(mes[:4]), int(mes[5:])
    ant = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    sig = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
    nom = lambda x: f"{MESES[int(x[5:]) - 1]} {x[:4]}"
    va, _, ea = valor_de_mes(t, ant)
    vs, _, es = valor_de_mes(t, sig)
    va = va if ea == "fijado" else None  # el historial guarda cuándo se cargó, no desde cuándo rige: solo se compara con montos ya fijados por norma
    partes = []
    a, b = _monto_txt(va), _monto_txt(valor)
    if valor and va and a and b:
        dif = (b / a - 1) * 100
        partes.append(f"En {nom(mes)} el valor es <b>{e(_corto(valor, 60))}</b>. En {nom(ant)} era {e(_corto(va, 60))}: "
                      + (f"sube un <b>{_num(dif)}%</b>." if dif > 0.005 else ("baja un <b>" + _num(-dif) + "%</b>." if dif < -0.005 else "no cambió.")))
    if vs and es == "fijado":
        partes.append(f"Para {nom(sig)} ya se conoce: <b>{e(_corto(vs, 60))}</b>.")
    elif valor:
        partes.append(f"El valor de {nom(sig)} todavía no se publicó: lo cargamos apenas sale.")
    if not valor:
        d_hoy = ajustar_tramo((RESP.get(t["slug"]) or {}).get("datos") or {})
        v_hoy = TRANSFORMA_MES[pref](d_hoy.get("valor")) if pref in TRANSFORMA_MES else d_hoy.get("valor")
        if v_hoy:
            partes.append(f"Todavía no se publicó el valor de {nom(mes)}. El último publicado es <b>{e(_corto(v_hoy, 60))}</b>"
                          + (f" (vigente desde {nom(d_hoy['mes_vigente'])})" if d_hoy.get("mes_vigente") else "") + ".")
        if t.get("cuando"):
            partes.append(f"<b>Cuándo se conoce:</b> {e(t['cuando'])}. Esta página se actualiza sola apenas sale el dato.")
    elif "anticipado" in str(valor):
        partes.append("Es un cálculo anticipado: aplicamos la fórmula de movilidad con la última inflación publicada por el INDEC. "
                      "Cuando sale la resolución oficial, el valor se reemplaza solo.")
    uso = USO_DATO_MES.get(pref)
    html_ = "".join(f"<p>{x}</p>" for x in partes)
    if uso:
        html_ += f"<p>{e(uso[0])}</p><p><a href=\"{uso[1][0].replace('{mes_url}', MESES[m - 1] + '-' + str(y))}\">{e(uso[1][1])} →</a></p>"
    return f"<h2>Cómo viene en {nom(mes)}</h2>{html_}" if html_ else ""


def pagina_mes(pref, slug_dato, tit, preg, mes, notas):
    t = next((x for x in TEMAS_RESP if x["slug"] == slug_dato), None)
    if not t:
        return None
    mes_txt = f"{MESES[int(mes[5:]) - 1]} {mes[:4]}"
    valor, texto, estado = valor_de_mes(t, mes)
    if pref in TRANSFORMA_MES:
        valor = TRANSFORMA_MES[pref](valor)
        texto = ("Es el 80% de la jubilación mínima del mes, más el bono. " + texto) if valor else texto
    etiqueta = {"vigente": "Vigente", "fijado": "Ya fijado", "anticipado": "Cálculo anticipado", "historico": "Valor de ese mes", "pendiente": "Todavía no publicado"}[estado]
    titulo = tit.format(mes=mes_txt)
    pregunta = preg.format(mes=mes_txt)
    otros = "".join(f'<li><a href="{pref}-{MESES[int(m2[5:]) - 1]}-{m2[:4]}.html">{MESES[int(m2[5:]) - 1].capitalize()} {m2[:4]}</a></li>' for m2 in _meses_paginas() if m2 != mes)
    caja = (f'<div class="resp-caja"><span class="resp-p">{e(pregunta)}</span><b class="resp-v">{e(valor or "Todavía no publicado")}</b>'
            f'<p><span class="nivel">{etiqueta}</span> {e(texto)}</p></div>')
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a> / <a href="{t['slug']}.html">{e(t['titulo'])}</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
{caja}
<p><a class="btn" href="{t['slug']}.html">Ver el dato vigente hoy y su historial →</a></p>
{texto_mes(pref, t, mes, valor)}
{"" if pref in TRANSFORMA_MES else bloque_dato_mes(t, estado)}
{"" if pref in TRANSFORMA_MES else bloque_evolucion(t)}
<section class="relacionadas"><h2>Otros meses</h2><ul>{otros}</ul></section>
<p class="aviso">Información de carácter general. Verificá siempre en la norma oficial.</p>
</div>{lateral(notas)}</div>"""
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": pregunta, "acceptedAnswer": {"@type": "Answer", "text": f"{valor}. {texto}" if valor else texto}}]}, ensure_ascii=False) + "</script>"
    # Se indexan el mes en curso y el que viene con valor conocido (Search Console 22/11: la de diciembre del tope, 9% de clics);
    # los meses ya pasados quedan publicados pero sin indexar
    # Se indexan el mes en curso y el que viene, aunque el que viene todavía no tenga valor (la página ya explica cuándo sale y el último
    # valor): así Google la tiene antes de que la gente la busque (26/11: tope-aportes-diciembre fue la página más vista del mes)
    hoy_m = datetime.date.today().strftime("%Y-%m")
    if mes < hoy_m or pref not in USO_DATO_MES or (not valor and not t.get("cuando")):
        PAGINAS_FINAS.add(f"{pref}-{MESES[int(mes[5:]) - 1]}-{mes[:4]}")
    v_tit = re.sub(r"^(Máxima|Mínima) ", lambda m: m.group(1).lower() + " ", valor or "")
    return pagina(f"{titulo.split(':')[0] + ': ' + v_tit if valor else titulo} | Ramacontable", cuerpo, "datos-al-dia",
                  f"{pregunta} {valor or ''} {texto}"[:300], f"{pref}-{MESES[int(mes[5:]) - 1]}-{mes[:4]}.html", ld,
                  [("Datos del día", "datos-al-dia.html"), (titulo, f"{pref}-{MESES[int(mes[5:]) - 1]}-{mes[:4]}.html")])


def urls_mes():
    return [f"{p[0]}-{MESES[int(m[5:]) - 1]}-{m[:4]}" for p in PAGINAS_MES for m in _meses_paginas()]


def pagina_paritaria(c, mes, notas):
    mes_txt = f"{MESES[int(mes[5:]) - 1]} {mes[:4]}"
    esc = c.get("escala") or {}
    periodo = esc.get("periodo") or ""
    nombre_mes = MESES[int(mes[5:]) - 1]
    ym = (int(mes[:4]), int(mes[5:]))
    cubre = bool(periodo) and _escala_ok(esc) and _ini_escala(esc) <= ym <= _fin_escala(esc)
    hist = sorted(c.get("historial") or [], key=lambda h: str(h.get("fecha", "")), reverse=True)
    if cubre:
        estado = f"La escala vigente para {mes_txt} es la de <b>{e(periodo)}</b>."
    elif periodo:
        estado = (f"Para {mes_txt} todavía no se publicó un acuerdo nuevo. La última escala cargada es la de <b>{e(periodo)}</b>; "
                  "la actualizamos en cuanto se homologue o la publiquen el gremio o las cámaras.")
    else:
        estado = f"Para {mes_txt} todavía no tenemos la escala confirmada con fuentes: se publica apenas la confirmen el gremio o dos portales."
    tabla = ""
    t = esc.get("tabla") or []
    sig = nombre_busqueda(c)
    propio = False  # la escala trae una columna propia de este mes: la página tiene datos que no están en otro lado
    if cubre and len(t) > 1:
        cab = [str(x) for x in t[0]]
        col_b = next((i for i in range(1, len(cab)) if "no rem" not in cab[i].lower() and _mes_col(cab[i]) == ym), None)
        col_nr = next((i for i in range(1, len(cab)) if "no rem" in cab[i].lower() and _mes_col(cab[i]) == ym), None)
        if col_b is not None:
            propio = True
            cols = [0, col_b] + ([col_nr] if col_nr is not None else [])
            sub = [[f[i] if len(f) > i else "" for i in cols] for f in t]
            tabla = (f"<h2>Escala {e(sig)} {mes_txt}</h2>" + bloque({"tabla": sub})
                     + f'<p class="nota-chica">Valores de la columna «{e(cab[col_b])}» de la escala {e(periodo)}. '
                     + (e(esc.get("aclaraciones", ""))[:400] + "</p>" if esc.get("aclaraciones") else "</p>"))
            ref = next((f for f in t[1:] if len(f) > col_b and (_imp(f[col_b]) or 0) > 0), None)
            if ref:
                estado += (f" Por ejemplo, la categoría <b>{e(re.sub(r'^categor[ií]a\s+', '', str(ref[0]), flags=re.I))}</b> tiene en {mes_txt} "
                           f"un valor de <b>$ {_num(_imp(ref[col_b]))}</b>.")
        else:
            tabla = bloque({"tabla": t[:13]}) + ('<p class="nota-chica">Escala completa en la página del convenio.</p>' if len(t) > 13 else "")
    def fila_h(h):
        pct = (_num(h["aumento_pct"]) + "%") if isinstance(h.get("aumento_pct"), (int, float)) else "-"
        link = f'<a href="nota-{h["nota"]}.html">ver nota</a>' if h.get("nota") else ""
        return f"<tr><td>{e(h.get('periodo') or '')}</td><td>{pct}</td><td>{link}</td></tr>"
    filas_h = "".join(fila_h(h) for h in hist[:6])
    h_html = (f'<h2>Últimos acuerdos</h2><div class="tabla"><table><thead><tr><th>Período</th><th>Aumento</th><th></th></tr></thead><tbody>{filas_h}</tbody></table></div>' if filas_h else "")
    rel = [n for n in notas if c["nombre"].split(" (")[0].lower() in n["titulo"].lower()][:4]
    rel_html = ("<h2>Novedades del convenio</h2><ul>" + "".join(f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a></li>' for n in rel) + "</ul>") if rel else ""
    titulo = (f"Escala {sig} {mes_txt} ({re.sub(r'\s*\(.*\)$', '', c.get('cct') or '')}): valores por categoría" if propio
              else f"Paritarias {c['nombre']} {mes_txt}: escala salarial y aumento")
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="convenios.html">Escalas por convenio</a> / <a href="escala-{c['slug']}.html">{e(c['nombre'])}</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · {e(c.get('cct') or '')} · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
<div class="resp-caja"><p>{estado}</p></div>
{tabla}
<p><a class="btn" href="escala-{c['slug']}.html">Ver la escala completa de {e(c['nombre'])} →</a></p>
{h_html}{rel_html}
<p class="aviso">Información de carácter general. Verificá siempre en el acuerdo homologado.</p>
</div>{lateral(notas)}</div>"""
    # Solo se indexan las del mes en curso y el que viene cuando la escala trae la columna de ese mes (datos propios: «Escala UOM enero 2027»).
    # Las demás repiten la escala del convenio y quedan sin indexar, para que la fuerza vaya a escala-<convenio>.html
    hoy_ym = (datetime.date.today().year, datetime.date.today().month)
    sig_ym = (hoy_ym[0] + hoy_ym[1] // 12, hoy_ym[1] % 12 + 1)
    if not (propio and ym in (hoy_ym, sig_ym)):
        PAGINAS_FINAS.add(f"paritarias-{c['slug']}-{nombre_mes}-{mes[:4]}")
    tit_seo = titulo if len(titulo) <= 65 else titulo.replace(": escala salarial y aumento", ": escala y aumento")
    return pagina(f"{tit_seo} | Ramacontable", cuerpo, "sueldos",
                  f"Paritarias {c['nombre']} ({c.get('cct') or ''}) {mes_txt}: escala salarial vigente, aumentos y sumas no remunerativas.",
                  f"paritarias-{c['slug']}-{nombre_mes}-{mes[:4]}.html", "", migas=[("Escalas por convenio", "convenios.html"), (titulo, f"paritarias-{c['slug']}-{nombre_mes}-{mes[:4]}.html")])


DIAS_SEM = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def pagina_feriados_anio(ruta, notas):
    d = json.load(open(ruta, encoding="utf-8"))
    anio = d["anio"]
    hoy = datetime.date.today().isoformat()
    def fila(x):
        f = datetime.date.fromisoformat(x["fecha"])
        cls = {"Inamovible": "t-ina", "Trasladable": "t-tra"}.get(x["tipo"], "t-no")
        return (f'<tr data-f="{x["fecha"]}"><td>{DIAS_SEM[f.weekday()].capitalize()} {f.day} de {MESES[f.month - 1]}</td><td>{e(x["nombre"])}</td>'
                f'<td><span class="tipo-f {cls}">{e(x["tipo"])}</span></td></tr>')
    lista = sorted(d["feriados"], key=lambda x: x["fecha"])
    prox = next((x for x in lista if x["fecha"] >= hoy), None)
    n_ina = sum(1 for x in lista if x["tipo"] == "Inamovible")
    fuentes = " · ".join(f'<a href="{e(f["url"])}" rel="nofollow noopener" target="_blank">{e(f["nombre"])}</a>' for f in d.get("fuente", []))
    qs = [{"p": f"¿Cuántos feriados hay en {anio}?", "r": f"El calendario {anio} tiene {n_ina} feriados inamovibles, {sum(1 for x in lista if x['tipo'] == 'Trasladable')} trasladables y {sum(1 for x in lista if x['tipo'] == 'No laborable')} días no laborables, sin contar los días con fines turísticos que fije el Gobierno."},
          {"p": f"¿Cuándo es Carnaval {anio}?", "r": "Carnaval " + str(anio) + ": " + " y ".join(f"{DIAS_SEM[datetime.date.fromisoformat(x['fecha']).weekday()]} {int(x['fecha'][8:])} de {MESES[int(x['fecha'][5:7]) - 1]}" for x in lista if x["nombre"] == "Carnaval") + "."},
          {"p": "¿Qué pasa con los feriados trasladables?", "r": "Según la Ley 27.399, los feriados trasladables que caen martes o miércoles pasan al lunes anterior, y los que caen jueves o viernes pasan al lunes siguiente. El Gobierno confirma los traslados y los días no laborables con fines turísticos por decreto."}]
    cuerpo = f"""<div class="grilla"><article class="nota calc">
<p class="ante">Calendario | Ley 27.399</p>
<h1>Feriados {anio} en Argentina: calendario completo</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
{f'<div class="encorto"><b>Primer feriado de {anio}</b><p>{e(prox["nombre"])}: {DIAS_SEM[datetime.date.fromisoformat(prox["fecha"]).weekday()]} {int(prox["fecha"][8:])} de {MESES[int(prox["fecha"][5:7]) - 1]}.</p></div>' if prox else ''}
<div class="tabla"><table class="feriados"><thead><tr><th>Fecha</th><th>Feriado</th><th>Tipo</th></tr></thead><tbody>{''.join(fila(x) for x in lista)}</tbody></table></div>
<p class="ayuda">Los feriados trasladables figuran en su fecha original: el Gobierno confirma por decreto a qué lunes se mueven y si habrá días no laborables con fines turísticos (puentes). Lo actualizamos apenas se publique.</p>
{preguntas_html({"preguntas": qs})}
<p class="fuente"><b>Fuente:</b> {fuentes}</p>
<p><a href="dias-habiles.html">Calculadora de días hábiles</a> · <a href="feriados.html">Feriados del año en curso</a></p>
</article>{lateral(notas)}</div>"""
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False) + "</script>"
    return anio, pagina(f"Feriados {anio} en Argentina: calendario completo, inamovibles y trasladables | Ramacontable", cuerpo, "",
                        f"Calendario de feriados {anio} en Argentina: inamovibles, trasladables, Carnaval, Semana Santa y días no laborables.",
                        f"feriados-{anio}.html", ld, [("Feriados", "feriados.html"), (f"Feriados {anio}", f"feriados-{anio}.html")])


def meses_que_cambia():
    """Mes actual y, desde el día 20, también el que viene (las páginas anteriores quedan publicadas)."""
    hoy = datetime.date.today()
    ms = [m for m in _meses_paginas() if m <= hoy.strftime("%Y-%m")]
    sig = f"{hoy.year + (hoy.month // 12)}-{hoy.month % 12 + 1:02d}"
    if hoy.day >= 20:
        ms.append(sig)
    return ms


def pagina_que_cambia(mes, notas):
    y, m = int(mes[:4]), int(mes[5:])
    mes_txt = f"{MESES[m - 1]} {y}"
    items = []
    for pref, slug_dato, tit, _ in PAGINAS_MES:
        t = next((x for x in TEMAS_RESP if x["slug"] == slug_dato), None)
        if not t:
            continue
        valor, texto, estado = valor_de_mes(t, mes)
        if valor:
            items.append(f'<li><b>{e(t["titulo"])}:</b> {e(valor)}{" (cálculo anticipado)" if estado == "anticipado" and "anticipado" not in valor else ""}. '
                         f'<a href="{pref}-{MESES[m - 1]}-{y}.html">Ver detalle</a></li>')
    if m in (6, 12):
        vto = datetime.date(y, 6, 30) if m == 6 else datetime.date(y, 12, 18)
        items.insert(0, f'<li><b>Aguinaldo:</b> vence el {DIAS_SEM[vto.weekday()]} {vto.day} de {MESES[m - 1]}. '
                        '<a href="aguinaldo.html">Calculadora de aguinaldo</a></li>')
    fer = []
    for ruta in glob.glob(os.path.join(RAIZ, "feriados", "*.json")):
        fer += [x for x in json.load(open(ruta, encoding="utf-8")).get("feriados", []) if x["fecha"].startswith(mes)]
    fer += [x for fila in VENC for x in fila.get("feriados") or [] if str(x.get("fecha", "")).startswith(mes) and not any(f["fecha"] == x["fecha"] for f in fer)]
    if mes == "2026-12" and not fer:
        fer = [{"fecha": "2026-12-08", "nombre": "Inmaculada Concepción de María"}, {"fecha": "2026-12-25", "nombre": "Navidad"}]
    fer_html = "".join(f"<li>{DIAS_SEM[datetime.date.fromisoformat(x['fecha']).weekday()].capitalize()} {int(x['fecha'][8:])}: {e(x['nombre'])}</li>" for x in sorted(fer, key=lambda z: z["fecha"]))
    venc = [x for x in proximos_vencimientos() if str(x["fecha"]).startswith(mes)]
    destac = [x for x in venc if any(k in x.get("concepto", "").lower() for k in ("931", "monotrib", "iva", "autónom", "casas particulares", "ganancias", "bienes personales"))][:12]
    venc_html = "".join(f"<li>{fecha_corta(x['fecha'])}: {e(x['concepto'])}{(' · ' + e(x['detalle'])) if x.get('detalle') else ''}</li>" for x in destac)
    nombre = MESES[m - 1]
    rel = [n for n in notas if nombre in n["titulo"].lower() and str(y) in n["titulo"]][:8]
    rel_html = "".join(f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a></li>' for n in rel)
    titulo = f"Qué cambia en {mes_txt}: aguinaldo, jubilaciones, salario mínimo, feriados y vencimientos" if m in (6, 12) else \
        f"Qué cambia en {mes_txt}: jubilaciones, AUH, salario mínimo, feriados y vencimientos"
    cuerpo = f"""<div class="grilla"><div class="nota-contenido"><p class="miga"><a href="datos-al-dia.html">Datos del día</a></p>
<h1>{e(titulo)}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(datetime.date.today().isoformat())}</p>
<p class="ayuda">Todo lo que cambia en {mes_txt} para liquidar sueldos e impuestos, en una sola página. Se actualiza sola a medida que se confirman los datos.</p>
{('<h2>Montos que cambian</h2><ul>' + ''.join(items) + '</ul>') if items else ''}
{('<h2>Feriados de ' + nombre + '</h2><ul>' + fer_html + '</ul>') if fer_html else ''}
{('<h2>Vencimientos destacados</h2><ul>' + venc_html + '</ul><p><a href="agenda-vencimientos.html">Armá tu agenda por CUIT →</a></p>') if venc_html else ''}
{('<h2>Novedades de ' + nombre + '</h2><ul>' + rel_html + '</ul>') if rel_html else ''}
<p class="aviso">Información de carácter general. Verificá siempre en las fuentes oficiales.</p>
</div>{lateral(notas)}</div>"""
    url = f"que-cambia-en-{nombre}-{y}"
    flaca = len(items) + (1 if fer_html else 0) + (1 if venc_html else 0) < 3
    if flaca:
        PAGINAS_FINAS.add(url)
    return url, pagina(f"{titulo} | Ramacontable", cuerpo, "datos-al-dia",
                       f"Qué cambia en {mes_txt}: montos de jubilaciones, AUH, salario mínimo y tope de aportes, feriados y vencimientos del mes, en una sola página.",
                       url + ".html", NOI if flaca else "", [("Datos del día", "datos-al-dia.html"), (titulo, url + ".html")])


def pagina_datos(notas):
    existe = lambda sl: os.path.exists(os.path.join(SALIDA, sl + ".html")) or any(t["slug"] == sl for t in TEMAS_RESP)
    bloques = ""
    for gid, nombre, items in grupos_datos():
        lis = "".join(f'<li><a href="{sl}.html"><b>{e(ti)}</b><span>{e(v or "Ver el dato")}</span></a></li>' for sl, ti, v in items if existe(sl))
        if lis:
            bloques += f'<h2 id="{gid}">{e(nombre)}</h2><ul class="lista-datos">{lis}</ul>'
    items = [bloques + '<p><a class="btn sec" href="cuando-cambia-cada-dato.html">Ver cuándo cambia cada dato →</a></p>']
    cuerpo = f"""<div class="grilla"><div><h1>Datos del día</h1>
<p class="ayuda">Los datos que más se consultan, en una página fija cada uno y siempre actualizados: la fábrica los rechequea todos los días contra las fuentes oficiales y solo publica lo que confirman al menos dos fuentes.</p>
{''.join(items)}</div>{lateral(notas)}</div>"""
    return pagina("Datos del día: salario mínimo, Monotributo, jubilación, dólar, UVA y más | Ramacontable", cuerpo, "datos-al-dia",
                  "Salario mínimo, jubilación mínima, AUH, Monotributo, Ganancias, UVA, CER y dólar oficial: los datos vigentes hoy, revisados todos los días.",
                  "datos-al-dia.html", migas=[("Datos del día", "datos-al-dia.html")])


# Enlaces internos automáticos: la primera mención de cada tema en una nota enlaza a su página fija
def _destinos_enlaces(convenios):
    d = []
    for t in TEMAS_RESP:
        for c in t.get("claves", []):
            d.append((c, t["slug"] + ".html"))
    for c in convenios:
        for nombre in {c.get("nombre", ""), *(c.get("alias") or [])}:
            if nombre and len(nombre) > 3:
                d.append((nombre, f"escala-{c['slug']}.html"))
    d += [("aguinaldo", "aguinaldo.html"), ("UVA", "valor-uva-hoy.html"), ("CER", "cer-hoy.html"),
          ("indemnización", "liquidacion-final.html"), ("liquidación final", "liquidacion-final.html"), ("horas extras", "horas-extras.html"), ("índices FACPCE", "indices-facpce.html"), ("índice FACPCE", "indices-facpce.html"),
          ("vacaciones", "vacaciones.html"), ("dólar blue", "dolar-blue-hoy.html"), ("dólar MEP", "dolar-mep-hoy.html"),
          ("contado con liquidación", "dolar-ccl-hoy.html"), ("dólar tarjeta", "dolar-tarjeta-hoy.html"), ("dólar oficial", "dolar-oficial-hoy.html"),
          ("ICL", "icl-alquileres-hoy.html"), ("BADLAR", "tasa-badlar-hoy.html"), ("TAMAR", "tasa-tamar-hoy.html"), ("días hábiles", "dias-habiles.html"), ("plazo fijo", "plazo-fijo.html")]
    return sorted(d, key=lambda x: -len(x[0]))


ENLACES = []


def enlazar(html_txt, propio=""):
    """Agrega como máximo 1 enlace por destino y 5 por nota, solo en texto de párrafos (nunca en títulos ni dentro de otro enlace)."""
    usados, puestos = set(), [0]
    def en_parrafo(m):
        txt = m.group(1)
        for frase, destino in ENLACES:
            if destino in usados or destino == propio or puestos[0] >= 5:
                continue
            rx = re.compile(r"(?<![\w>])(" + re.escape(e(frase)) + r")(?![\w<])", re.I)
            partes = re.split(r"(<a [^>]*>.*?</a>)", txt)
            for i, parte in enumerate(partes):
                if parte.startswith("<a "):
                    continue
                nuevo, n = rx.subn(lambda x: f'<a href="{destino}">{x.group(1)}</a>', parte, count=1)
                if n:
                    partes[i] = nuevo; usados.add(destino); puestos[0] += 1
                    break
            txt = "".join(partes)
        return "<p>" + txt + "</p>"
    return re.sub(r"<p>(.*?)</p>", en_parrafo, html_txt, flags=re.S)


def dato_de_nota(n):
    """Tema de datos del día que trata la nota (por sus palabras clave en título y resumen)."""
    txt = (n.get("titulo", "") + " " + n.get("encorto", "")).lower()
    for t in TEMAS_RESP:
        if any(c.lower() in txt for c in t.get("claves", [])):
            return t
    return None


_DUDOSA = re.compile(r"consultar|estimad|aproximad|a confirmar|s/d|sin dato", re.I)


def tabla_dudosa(b):
    return "tabla" in b and any(_DUDOSA.search(str(c)) for fila in b["tabla"] for c in fila)


def caja_dato_vigente(n):
    t = dato_de_nota(n)
    if not t:
        return ""
    r = RESP.get(t["slug"]) or {}
    d = ajustar_tramo(r.get("datos") or {})
    vieja = ""
    camb = str(r.get("cambiado") or "")[:10]
    if camb and str(n.get("actualizado") or n["fecha"])[:10] < camb:
        f = str(n["fecha"])[:10]
        vieja = f"<b>Esta nota es de {MESES[int(f[5:7]) - 1]} {f[:4]}.</b> Desde entonces los valores cambiaron. "
    return (f'<div class="dato-vigente">{vieja}Valor vigente hoy de <b>{e(t["titulo"])}</b>: '
            f'{e(d.get("valor") or "en verificación")}. <a href="{t["slug"]}.html">Ver la tabla vigente →</a></div>')


SEO_SALTO = {"guia-ganancias-cuarta-categoria": "12-01"}   # desde esa fecha el {anio} del título ya es el año que viene
SEO_NOTAS = {   # slug → (título para Google, descripción). Se eligen mirando las búsquedas reales de Search Console.
    "anses-bases-imponibles-tope-jubilatorio-noviembre-2026": (
        "Tope MOPRE noviembre 2026: base máxima $ 4.861.685,38 (ANSES)",
        "Topes de aportes y contribuciones de noviembre 2026: base imponible máxima $ 4.861.685,38 y mínima $ 149.592,45, según la Resolución 304/2026 de ANSES."),
    "guia-categorias-comercio": (
        "Categorías de Comercio (CCT 130/75): qué puesto va en cada una",
        "Maestranza, administrativos, cajeros, vendedores y auxiliares: qué tareas entran en cada categoría del convenio de Comercio y dónde ver la escala vigente."),
    # guías profesionales: títulos con lo que busca un contador o liquidador (la gente común va a «Guías fáciles»)
    "guia-sac-aguinaldo": (
        "SAC (aguinaldo): cálculo, proporcional y licencias según la LCT",
        "Cálculo del SAC (arts. 121 a 123 LCT): mejor remuneración del semestre, proporcional por días trabajados, licencias, fechas de pago y caso práctico."),
    "guia-ganancias-cuarta-categoria": (
        "Ganancias cuarta categoría {anio}: retenciones y deducciones",
        "Régimen de retención de Ganancias sobre sueldos para empleadores y liquidadores: escalas, deducciones personales y generales, SIRADIG y liquidación anual."),
    "guia-siradig": (
        "SIRADIG Trabajador: cómo cargar el formulario 572 web",
        "Paso a paso del SIRADIG Trabajador (F.572 web): cargas de familia, deducciones generales, comprobantes, plazos y envío al empleador."),
    "guia-ganancias-personas-humanas": (
        "Ganancias personas humanas: declaración jurada anual",
        "Quiénes deben presentar la declaración jurada anual de Ganancias de personas humanas, la DDJJ simplificada, deducciones y vencimientos."),
    "guia-bienes-personales": (
        "Bienes Personales: mínimo, alícuotas y declaración jurada",
        "Quiénes pagan Bienes Personales, mínimo no imponible, alícuotas y cómo se presenta la declaración jurada."),
}


GUIA_SAC = [False]   # se prende si la guía del aguinaldo está publicada


def caja_facil(n):
    """En la guía profesional, el acceso a la versión explicada fácil del mismo tema."""
    url = f"nota-{n.get('slug')}.html"
    g = next((x for x in EXPLICADO if (x.get("profesional") or [""])[0] == url or url in (x.get("profesionales_extra") or [])), None)
    return (f'<p class="ef-pro">¿Buscás la versión simple, sin palabras técnicas? <a href="{g["ruta"]}.html">{e(g["titulo"])} →</a></p>') if g else ""


def caja_guia(n, notas=()):
    """Accesos y explicaciones cortas que se suman arriba de algunas guías (datos de la Ley de Contrato de Trabajo)."""
    if n.get("slug") == "guia-sac-aguinaldo":
        return ('<div class="dato-vigente caja-guia"><b>Cálculo rápido del aguinaldo</b>'
                '<p><b>¿Qué significa SAC en el recibo?</b> Sueldo Anual Complementario: es el nombre legal del aguinaldo (art. 121 de la Ley de Contrato de Trabajo).</p>'
                '<p><b>Cuánto es:</b> el 50% de la mejor remuneración mensual devengada en el semestre. Se paga en dos cuotas: hasta el 30 de junio y hasta el 18 de diciembre.</p>'
                '<p><b>Proporcional:</b> si no trabajó el semestre completo, se cobra en proporción a los días trabajados: '
                'mejor sueldo ÷ 2 × días trabajados ÷ días del semestre (181 el primero, 182 en años bisiestos, y 184 el segundo).</p>'
                '<p><b>Ejemplo:</b> mejor sueldo $ 1.200.000 y 92 días trabajados en el segundo semestre → $ 1.200.000 ÷ 2 × 92 ÷ 184 = <b>$ 300.000</b>.</p>'
                '<p><a class="btn" href="aguinaldo.html">Calcular mi aguinaldo →</a> <a href="planillas/planilla-aguinaldo-varios-empleados.xlsx">Planilla para varios empleados (Excel)</a></p></div>')
    if n.get("slug") == "guia-categorias-comercio":
        return ('<div class="dato-vigente caja-guia"><b>Con la categoría ya definida:</b> '
                '<a href="escala-comercio.html">escala salarial de Comercio vigente</a> · '
                '<a href="sueldo-comercio.html">calculadora de sueldo de Comercio</a>'
                + (' · <a href="nota-guia-liquidar-sueldo-comercio.html">cómo liquidar un sueldo de Comercio paso a paso</a>'
                   if any(x.get("slug") == "guia-liquidar-sueldo-comercio" for x in notas) else "") + '</div>')
    return ""


def pagina_nota(n, notas, aportes=None):
    if n.get("slug") in SEO_NOTAS:
        salto = SEO_SALTO.get(n["slug"])
        n = dict(n, seo_titulo=con_anio(SEO_NOTAS[n["slug"]][0], salto), descripcion_seo=con_anio(SEO_NOTAS[n["slug"]][1], salto))
    verif = ("Elaborada con fuentes oficiales." if n.get("verificada")
             else "Pendiente de verificación con fuente oficial.")
    t_dato = dato_de_nota(n)
    extra_calc = bloque_aguinaldo(n, notas) + ('<div class="dato-vigente"><b>Calculalo:</b> <a href="aguinaldo.html">calculadora de aguinaldo</a> · '
                  '<a href="tope-aportes-base-maxima.html">tope de aportes vigente</a> · <a href="retencion-ganancias.html">retención de Ganancias</a>'
                  + ('' if n.get("slug") == "guia-sac-aguinaldo" or not GUIA_SAC[0] else ' · <a href="nota-guia-sac-aguinaldo.html">guía completa del aguinaldo</a>') + '</div>'
                  if "aguinaldo" in (n.get("titulo", "") + " " + n.get("slug", "")).lower() else "") + caja_guia(n, notas) + caja_escala(n) + caja_facil(n)
    cuerpo = extra_calc + enlazar("".join(
        (f'<p class="dato-vigente">La tabla completa y actualizada está en <a href="{t_dato["slug"]}.html">{e(t_dato["titulo"])}</a>.</p>' if t_dato
         else "") if tabla_dudosa(b) else bloque(b) for b in n["cuerpo"]), f"nota-{n['slug']}.html")
    sec = SECCIONES[n["seccion"]]
    previa = ""
    if n.get("actualiza"):
        previa = f'<p class="actualiza">Esta nota actualiza a: <a href="nota-{e(n["actualiza"])}.html">la nota anterior sobre el tema</a></p>'
    contenido = f"""<div class="grilla"><article class="nota" data-nota="{n['slug']}" data-actualizado="{e(str(n.get('actualizado') or ''))}">
<div class="nota-contenido">
{portada_html(n, "nota")}
<p class="miga">{f'<a href="guias.html">Guías</a> / <a href="guias.html#{n["seccion"]}">{RAMAS_GUIAS.get(n["seccion"], sec)}</a>' if es_guia(n) else f'<a href="{n["seccion"]}.html">{sec}</a>'}</p>
<p class="ante">{e(n['antetitulo'])}</p>
<h1>{e(n['titulo'])}</h1>
<p class="firma">Redacción Ramacontable · {('Guía actualizada al ' + fecha_larga(str(n.get('actualizado') or n['fecha'])[:10])) if es_guia(n) else fecha_larga(n['fecha'])}</p>
{previa}
{caja_dato_vigente(n)}
<div class="encorto"><b>En corto</b><p>{e(n['encorto'])}</p></div>
{cuerpo}
{preguntas_html(n)}
<p class="fuente"><b>Fuente:</b> {e(n['fuente'])}</p>
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. {verif}</p>
</div>

{relacionadas(n, notas)}
{bloque_aportes(n, aportes)}
</article>{lateral(notas)}</div>"""
    url = f"{sitio_url()}nota-{n['slug']}.html"
    ld = [{"@context": "https://schema.org", "@type": "Article" if es_guia(n) else "NewsArticle", "headline": n["titulo"][:110],
           "description": n.get("descripcion_seo") or n["encorto"], "datePublished": str(n["fecha"]),
           "dateModified": datetime.date.today().isoformat() if (es_guia(n) and "aguinaldo" in n["slug"]) else str(n.get("actualizado") or n["fecha"]), "inLanguage": "es-AR",
           "mainEntityOfPage": url, "articleSection": SECCIONES[n["seccion"]],
           "author": {"@type": "Organization", "name": "Redacción Ramacontable", "url": sitio_url()},
           "publisher": {"@type": "Organization", "name": "Ramacontable", "logo": {"@type": "ImageObject", "url": sitio_url() + "icono-512.png"}}}]
    if n.get("preguntas"):
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in n["preguntas"]]})
    head = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in ld)
    head += f'<meta property="og:type" content="article"><meta property="article:published_time" content="{e(str(n["fecha"]))}">'
    migas = ([("Guías", "guias.html"), (RAMAS_GUIAS.get(n["seccion"], "Guías"), f"guias.html#{n['seccion']}")] if es_guia(n)
             else [(SECCIONES[n["seccion"]], f"{n['seccion']}.html")]) + [(n["titulo"][:80], f"nota-{n['slug']}.html")]
    return pagina(n.get("seo_titulo") or f"{n['titulo']} | Ramacontable", contenido, n["seccion"],
                  n.get("descripcion_seo") or n["encorto"], f"nota-{n['slug']}.html", head, migas,
                  f"compartir/{n['slug']}.png" if n["slug"] in PORTADAS_OK else "compartir.png")


DESC_SECCION = {
    "sueldos": "Novedades de sueldos, escalas salariales por convenio, sumas no remunerativas, guías y calculadoras para liquidar.",
    "impuestos": "Novedades impositivas de ARCA y rentas provinciales: Ganancias, IVA, Monotributo, Bienes Personales, Ingresos Brutos y más.",
    "profesion": "Novedades para el ejercicio de la profesión contable: consejos profesionales, normas contables, sociedades y trámites.",
}


# ---------- Provincias y municipios ----------
JURIS = []      # jurisdicciones con página propia (jurisdicciones/<slug>.json)
OTRAS_J = []    # provincias que por ahora solo muestran novedades (jurisdicciones/otras.json)
JURIS_URLS = []
TABLAS_URLS = []


def cargar_jurisdicciones():
    JURIS[:], OTRAS_J[:] = [], []
    for ruta in sorted(glob.glob(os.path.join(RAIZ, "jurisdicciones", "*.json"))):
        try:
            d = json.load(open(ruta, encoding="utf-8"))
        except Exception as ex:
            print("Aviso: no pude leer", ruta, ex)
            continue
        if os.path.basename(ruta) == "otras.json":
            OTRAS_J[:] = d.get("lista") or []
        elif d.get("slug") and d.get("ruta"):
            JURIS.append(d)
    JURIS.sort(key=lambda j: j.get("orden", 99))


def _de_jurisdiccion(n, claves, solo_titulo=False):
    txt = _N(n.get("titulo", "") + ("" if solo_titulo else " " + n.get("antetitulo", "") + " " + (n.get("tema") or "") + " " + n.get("encorto", "")))
    return any(re.search(r"\b" + re.escape(_N(c)) + r"\b", txt) for c in claves)


def nota_de_nicho(n):
    """Notas de una provincia o municipio que no se muestran en la portada (siguen en su sección y en su página)."""
    return any(not j.get("portada", True) and _de_jurisdiccion(n, j.get("claves") or [], True) for j in JURIS) or \
        any(_de_jurisdiccion(n, o.get("claves") or [], True) for o in OTRAS_J)


def _venc_de(claves):
    return [x for x in proximos_vencimientos() if any(re.search(r"\b" + re.escape(_N(c)) + r"\b", _N(x.get("concepto", "") + " " + x.get("detalle", ""))) for c in claves)]


def pagina_jurisdiccion(j, notas):
    hoy = datetime.date.today()
    temas = [t for t in TEMAS_RESP if t.get("jurisdiccion") == j["slug"]]
    cajas = ""
    for t in temas:
        d = ajustar_tramo((RESP.get(t["slug"]) or {}).get("datos") or {})
        if d.get("valor"):
            cajas += (f'<div class="resp-caja"><span class="resp-p">{e(t["pregunta"])}</span><b class="resp-v">{e(d["valor"])}</b>'
                      f'<p>{e(d.get("respuesta", ""))}</p>' + (f'<p class="resp-meta">Norma: {e(d["norma"])}</p>' if d.get("norma") else "")
                      + f'<p><a class="btn sec" href="{t["slug"]}.html">Ver la tabla completa por categoría →</a></p></div>')
    fijos = "".join(bloque(b) for b in j.get("bloques") or [])
    fijos += "".join(f'<p><a class="btn" href="{t["ruta"]}.html">{e(t["titulo_corto"])}: buscá tu actividad →</a></p>' for t in j.get("tablas") or [])
    if j.get("paginas"):
        fijos += '<p>' + " · ".join(f'<a href="{pg["ruta"]}.html">{e(pg["titulo_corto"])} →</a>' for pg in j["paginas"]) + '</p>'
    venc = _venc_de(j.get("venc_claves") or [])
    venc_html = ""
    if venc:
        venc_html = ('<h2>Próximos vencimientos</h2><div class="tabla"><table><thead><tr><th>Vence</th><th>Obligación</th><th>CUIT</th></tr></thead><tbody>'
                     + "".join(f'<tr><td><b>{fecha_corta(x["fecha"])}</b></td><td>{e(x["concepto"])}</td><td>{e(x.get("detalle") or "Todas")}</td></tr>' for x in venc[:15])
                     + '</tbody></table></div><p class="ayuda">Fechas confirmadas por al menos dos fuentes o por el organismo. Si cae en día inhábil, ya figura corrida.</p>')
    rel = [n for n in notas if _de_jurisdiccion(n, j.get("claves") or [])]
    nov = ('<h2>Novedades de ' + e(j["nombre"]) + '</h2><div class="tarjetas">' + "".join(tarjeta(n) for n in rel[:12]) + "</div>") if rel else \
        f'<h2>Novedades de {e(j["nombre"])}</h2><p class="vacio">Cuando {e(j["organismo"])} publique una novedad para la profesión, aparece acá.</p>'
    of = " · ".join(f'<a href="{e(o["url"])}" rel="nofollow noopener" target="_blank">{e(o["nombre"])}</a>' for o in j.get("oficiales") or [])
    otras = "".join(f'<li><a href="{x["ruta"]}.html">{e(x["titulo_corto"])}</a></li>' for x in JURIS if x["slug"] != j["slug"])
    qs = []
    for t in temas:
        d = (RESP.get(t["slug"]) or {}).get("datos") or {}
        if d.get("respuesta"):
            qs.append({"p": t["pregunta"], "r": d["respuesta"]})
        qs += [q for q in d.get("preguntas") or [] if q.get("p") != t["pregunta"]][:1]
    cuerpo = f"""<div class="grilla"><article class="nota"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a></p>
<p class="ante">{e(j["organismo"])}</p>
<h1>{e(j["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat())}</p>
<p>{e(j.get("intro", ""))}</p>
{cajas}{fijos}{venc_html}{preguntas_html({"preguntas": qs})}
{f'<p class="fuente"><b>Sitios oficiales:</b> {of}</p>' if of else ""}
<p class="aviso">Información de carácter general. Verificá siempre en el sitio oficial del organismo. Cada profesional es responsable de su aplicación.</p>
</div>
{nov}
<section class="relacionadas"><h2>Otras provincias y municipios</h2><ul>{otras}<li><a href="provincias-y-municipios.html">Ver todas</a></li></ul></section>
</article>{lateral(notas)}</div>"""
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>") if qs else ""
    if not cajas and not fijos and not rel and not venc:
        PAGINAS_FINAS.add(j["ruta"])
        ld += NOI
    return pagina(j.get("seo_titulo") or f'{j["titulo"]} | Ramacontable', cuerpo, "impuestos", j["descripcion"], j["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html")])


def pagina_tabla_juris(j, t, notas):
    """Tabla grande de una jurisdicción (ej.: alícuotas de Seguridad e Higiene por actividad) con buscador."""
    d = json.load(open(os.path.join(RAIZ, t["archivo"]), encoding="utf-8"))
    filas = d["filas"]
    por = {f[0]: f for f in filas}
    dest = [por[c] for c in t.get("destacados") or [] if c in por]
    fila = lambda f: "<tr>" + "".join(f"<td>{'<b>' + e(x) + '</b>' if i == 2 else e(x)}</td>" for i, x in enumerate(f)) + "</tr>"
    cab = "".join(f"<th>{e(c)}</th>" for c in d["columnas"])
    if len(d["columnas"]) < 4:
        return _pagina_tabla_simple(j, t, d, filas, dest, fila, cab, notas)
    cuenta = {}
    for f in filas:
        cuenta[f[2]] = cuenta.get(f[2], 0) + 1
    gral, n_gral = max(cuenta.items(), key=lambda x: x[1])
    minimos = {}
    for f in filas:
        minimos[f[3]] = minimos.get(f[3], 0) + 1
    min_gral = max(minimos.items(), key=lambda x: x[1])[0]
    qs = [{"p": f"¿Cuál es la alícuota de Seguridad e Higiene en {j['nombre']} en 2026?",
           "r": f"Depende de la actividad. La más común es {gral} ({n_gral} de {len(filas)} actividades), con un mínimo de {min_gral} por mes. Va del 4‰ (actividades agropecuarias) al 75‰ (bancos y entidades financieras). {d['norma']}."},
          {"p": "¿Cuál es el mínimo mensual de la tasa?", "r": f"Para casi todas las actividades, {min_gral} por mes. Hay excepciones: algunas actividades tienen mínimo $ 0 (por ejemplo, servicios públicos, culturales o de organizaciones sin fines de lucro) y las salas de bingo y tragamonedas tienen mínimos más altos."},
          {"p": "¿Cómo encuentro mi actividad?", "r": "Buscala por el código de actividad que tenés en ARCA (NAES) o por una palabra de la descripción. Los códigos de 5 cifras son los mismos que en ARCA empiezan con 0."}]
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    cuerpo = f"""<div class="grilla"><article class="nota calc"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{j["ruta"]}.html">{e(j["nombre"])}</a></p>
<p class="ante">{e(j["organismo"])} | {e(d["norma"])}</p>
<h1>{e(t["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · {e(d["vigencia"])}</p>
<div class="encorto"><b>En corto</b><p>En {e(j["nombre"])}, la alícuota más común de la Tasa por Inspección de Seguridad e Higiene 2026 es <b>{e(gral)}</b> con un mínimo de <b>{e(min_gral)} por mes</b>. Cada actividad tiene su alícuota máxima y su mínimo en el Anexo de la ordenanza: buscá la tuya abajo.</p></div>
<h2>Las actividades más buscadas</h2>
<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in dest)}</tbody></table></div>
<h2>Buscá tu actividad ({len(filas)} actividades)</h2>
<p><input id="busca-tabla" type="search" placeholder="Código NAES o palabra (ej.: 692000, peluquería, restaurante)" style="width:100%;padding:.7em;font-size:1rem" autocomplete="off"></p>
<p class="ayuda" id="busca-cuenta">{len(filas)} actividades</p>
<div class="tabla"><table id="tabla-grande"><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in filas)}</tbody></table></div>
<script>(function(){{var i=document.getElementById('busca-tabla'),t=document.getElementById('tabla-grande'),c=document.getElementById('busca-cuenta');
var n=function(s){{return (s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')}};
var rows=[].slice.call(t.tBodies[0].rows);rows.forEach(function(r){{r._t=n(r.textContent)+' 0'+r.cells[0].textContent}});
i.addEventListener('input',function(){{var q=n(i.value).trim().split(/\\s+/),k=0;rows.forEach(function(r){{var ok=q.every(function(w){{return r._t.indexOf(w)>=0}});r.style.display=ok?'':'none';if(ok)k++}});c.textContent=k+' actividades'}});}})();</script>
{preguntas_html({"preguntas": qs})}
<p class="fuente"><b>Fuente:</b> <a href="{e(d["fuente"]["url"])}" rel="nofollow noopener" target="_blank">{e(d["fuente"]["nombre"])}</a>. {e(d.get("aclaracion", ""))}</p>
<p><a href="{j["ruta"]}.html">Más sobre {e(j["nombre"])}: Monotasa, novedades y vencimientos →</a></p>
<p class="aviso">Las alícuotas y mínimos del Anexo son máximos: la Municipalidad no puede cobrar más. Verificá siempre tu caso en la Municipalidad o con tu contador.</p>
</div></article>{lateral(notas)}</div>"""
    return pagina(f'{t["titulo"]} | Ramacontable', cuerpo, "impuestos", t["descripcion"], t["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html"), (t["titulo_corto"], t["ruta"] + ".html")])


def _pagina_tabla_simple(j, t, d, filas, dest, fila, cab, notas):
    qs = d.get("preguntas") or []
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>") if qs else ""
    cuerpo = f"""<div class="grilla"><article class="nota calc"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{j["ruta"]}.html">{e(j["nombre"])}</a></p>
<p class="ante">{e(j["organismo"])} | {e(d["norma"])}</p>
<h1>{e(t["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · {e(d["vigencia"])}</p>
<div class="encorto"><b>En corto</b><p>{e(d.get("encorto", ""))}</p></div>
<h2>Las actividades más buscadas</h2>
<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in dest)}</tbody></table></div>
<h2>Buscá tu actividad ({len(filas)} actividades con alícuota especial)</h2>
<p><input id="busca-tabla" type="search" placeholder="Código o palabra (ej.: 471110, seguros, autos)" style="width:100%;padding:.7em;font-size:1rem" autocomplete="off"></p>
<p class="ayuda" id="busca-cuenta">{len(filas)} actividades</p>
<div class="tabla"><table id="tabla-grande"><thead><tr>{cab}</tr></thead><tbody>{"".join(fila(f) for f in filas)}</tbody></table></div>
<script>(function(){{var i=document.getElementById('busca-tabla'),t=document.getElementById('tabla-grande'),c=document.getElementById('busca-cuenta');
var n=function(s){{return (s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')}};
var rows=[].slice.call(t.tBodies[0].rows);rows.forEach(function(r){{r._t=n(r.textContent)}});
i.addEventListener('input',function(){{var q=n(i.value).trim().split(/\\s+/),k=0;rows.forEach(function(r){{var ok=q.every(function(w){{return r._t.indexOf(w)>=0}});r.style.display=ok?'':'none';if(ok)k++}});c.textContent=k+' actividades'}});}})();</script>
{preguntas_html({"preguntas": qs})}
<p class="fuente"><b>Fuente:</b> <a href="{e(d["fuente"]["url"])}" rel="nofollow noopener" target="_blank">{e(d["fuente"]["nombre"])}</a>. {e(d.get("aclaracion", ""))}</p>
<p><a href="{j["ruta"]}.html">Más sobre {e(j["nombre"])}: alícuota general, mínimos y Monotasa →</a></p>
<p class="aviso">Información de carácter general. Verificá siempre tu caso en la Municipalidad o con tu contador.</p>
</div></article>{lateral(notas)}</div>"""
    return pagina(f'{t["titulo"]} | Ramacontable', cuerpo, "impuestos", t["descripcion"], t["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html"), (t["titulo_corto"], t["ruta"] + ".html")])


def pagina_extra_juris(j, pg, notas):
    """Página propia de un tema de la jurisdicción (ej.: licencia de conducir, patente) con sus bloques y preguntas."""
    hoy = datetime.date.today()
    qs = pg.get("preguntas") or []
    ld = ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q["p"], "acceptedAnswer": {"@type": "Answer", "text": q["r"]}} for q in qs]}, ensure_ascii=False).replace("</", "<\\/") + "</script>") if qs else ""
    of = " · ".join(f'<a href="{e(o["url"])}" rel="nofollow noopener" target="_blank">{e(o["nombre"])}</a>' for o in j.get("oficiales") or [])
    otras = "".join(f'<li><a href="{x["ruta"]}.html">{e(x["titulo_corto"])}</a></li>' for x in (j.get("paginas") or []) + (j.get("tablas") or []) if x["ruta"] != pg["ruta"])
    cuerpo = f"""<div class="grilla"><article class="nota"><div class="nota-contenido">
<p class="miga"><a href="provincias-y-municipios.html">Provincias y municipios</a> › <a href="{j["ruta"]}.html">{e(j["nombre"])}</a></p>
<p class="ante">{e(j["organismo"])}</p>
<h1>{e(pg["titulo"])}</h1>
<p class="firma">Redacción Ramacontable · Actualizado {fecha_larga(hoy.isoformat())}</p>
<div class="encorto"><b>En corto</b><p>{e(pg.get("encorto", ""))}</p></div>
{"".join(bloque(b) for b in pg.get("bloques") or [])}
{preguntas_html({"preguntas": qs})}
{f'<p class="fuente"><b>Fuente:</b> {of}</p>' if of else ""}
<p class="aviso">Información de carácter general. Verificá siempre en la Municipalidad.</p>
</div>
<section class="relacionadas"><h2>Más de {e(j["nombre"])}</h2><ul><li><a href="{j["ruta"]}.html">{e(j["titulo_corto"])}: todas las tasas</a></li>{otras}</ul></section>
</article>{lateral(notas)}</div>"""
    return pagina(f'{pg["titulo"]} | Ramacontable', cuerpo, "impuestos", pg["descripcion"], pg["ruta"] + ".html", ld,
                  [("Provincias y municipios", "provincias-y-municipios.html"), (j["titulo_corto"], j["ruta"] + ".html"), (pg["titulo_corto"], pg["ruta"] + ".html")])


def pagina_buscar(notas, guias, convenios):
    """Buscador del portal: índice liviano (título, descripción y dirección) que se filtra en el navegador."""
    idx = []
    add = lambda t, u, d="", k="": idx.append({"t": t, "u": u, "d": (d or "")[:160], "k": k})
    for n in notas + guias:
        add(n["titulo"], f"nota-{n['slug']}.html", n.get("encorto"), "Guía" if es_guia(n) else "Nota")
    for t in TEMAS_RESP:
        d = ajustar_tramo((RESP.get(t["slug"]) or {}).get("datos") or {})
        add(t["titulo"], t["slug"] + ".html", d.get("respuesta") or t["pregunta"], "Dato")
    for c in convenios:
        add("Escala salarial " + c.get("nombre", c["slug"]), f"escala-{c['slug']}.html", c.get("descripcion"), "Escala")
    for j in JURIS:
        add(j["titulo"], j["ruta"] + ".html", j["descripcion"], "Provincias")
        for x in (j.get("tablas") or []) + (j.get("paginas") or []):
            add(x["titulo"], x["ruta"] + ".html", x["descripcion"], "Provincias")
    for o in OBLIGACIONES:
        add("Vencimientos de " + o[1], o[0] + ".html", "Fechas por terminación de CUIT", "Vencimientos")
    for b in BCRA_RESP:
        add(b[2], b[0] + ".html", b[3], "Dato")
    add("Dólar hoy: oficial, MEP, CCL, tarjeta, cripto y blue", "dolar-hoy.html", "Todas las cotizaciones del día", "Dato")
    for g in EXPLICADO:
        add(g["titulo"], g["ruta"] + ".html", g["descripcion"], "Guía")
    for a, t in [("aguinaldo", "Calculadora de aguinaldo (SAC)"), ("sueldo-comercio", "Calculadora de sueldo de Comercio"), ("sueldo-casas-particulares", "Calculadora de sueldo de casas particulares"),
                 ("liquidacion-final", "Calculadora de liquidación final e indemnización"), ("vacaciones", "Calculadora de vacaciones"), ("horas-extras", "Calculadora de horas extras"),
                 ("feriado-trabajado", "Calculadora de feriado trabajado"), ("indices-facpce", "Índices FACPCE para ajuste por inflación (RT 6)"), ("retencion-ganancias", "Calculadora de retención de Ganancias"), ("monotributo-categoria", "Calculadora de categoría del Monotributo"), ("embargo-sueldo", "Calculadora de embargo de sueldo"),
                 ("intereses-arca", "Calculadora de intereses de ARCA"), ("actualizacion-alquiler", "Calculadora de actualización de alquiler"), ("actualizacion", "Actualización de montos por inflación, CER, UVA y dólar"),
                 ("conversor-dolar", "Conversor de dólar"), ("iva", "Calculadora de IVA"), ("dias-habiles", "Calculadora de días hábiles"), ("plazo-fijo", "Simulador de plazo fijo"), ("prestamos", "Calculadora de préstamos"),
                 ("agenda-vencimientos", "Agenda de vencimientos por CUIT"), ("feriados", "Feriados del año"), ("herramientas", "Vencimientos del mes"), ("glosario", "Glosario contable"),
                 ("comparador-escalas", "Aumentos por convenio vs. inflación"), ("planillas/planilla-aguinaldo-varios-empleados.xlsx", "Planilla Excel de aguinaldo para varios empleados"),
                 ("planillas/planilla-liquidacion-final.xlsx", "Planilla Excel de liquidación final"), ("planillas/planilla-vacaciones.xlsx", "Planilla Excel de vacaciones")]:
        add(t, a if a.endswith(".xlsx") else a + ".html", "", "Planilla" if a.endswith(".xlsx") else "Calculadora")
    with open(os.path.join(SALIDA, "datos", "buscar.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    cuerpo = """<div class="grilla"><section><h1 class="titsec">Buscar en Ramacontable</h1>
<p><input id="q" type="search" placeholder="Ej.: aguinaldo, monotributo, UOCRA, tope de aportes, Córdoba" style="width:100%;padding:.8em;font-size:1.05rem" autocomplete="off" autofocus></p>
<p class="ayuda" id="q-cuenta">Escribí qué estás buscando: notas, guías, datos del día, escalas, calculadoras y planillas.</p>
<ul class="lista-guias" id="q-res"></ul>
<script>(function(){var q=document.getElementById('q'),r=document.getElementById('q-res'),c=document.getElementById('q-cuenta'),D=null;
var n=function(s){return (s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'')};
var esc=function(s){return String(s||'').replace(/[&<>"]/g,function(m){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]})};
function ver(){var t=n(q.value).trim();if(!D||t.length<2){r.innerHTML='';c.textContent=t.length?'Escribí al menos 2 letras.':'Escribí qué estás buscando: notas, guías, datos del día, escalas, calculadoras y planillas.';return}
var p=t.split(/\\s+/),res=[];D.forEach(function(x){var ti=x._t,to=x._a;if(!p.every(function(w){return to.indexOf(w)>=0}))return;var s=0;p.forEach(function(w){if(ti.indexOf(w)>=0)s+=3});if(x.k!=='Nota')s+=1;res.push([s,x])});
res.sort(function(a,b){return b[0]-a[0]});c.textContent=res.length?res.length+(res.length===1?' resultado':' resultados'):'No encontramos nada con esas palabras. Probá con menos palabras.';
r.innerHTML=res.slice(0,40).map(function(y){var x=y[1];return '<li><a href="'+esc(x.u)+'"><b>'+esc(x.t)+'</b><span>'+esc(x.k)+(x.d?' · '+esc(x.d):'')+'</span></a></li>'}).join('')}
fetch('datos/buscar.json').then(function(x){return x.json()}).then(function(d){D=d;D.forEach(function(x){x._t=n(x.t);x._a=n(x.t+' '+x.d+' '+x.k)});var u=new URLSearchParams(location.search).get('q');if(u){q.value=u}ver()});
q.addEventListener('input',ver)})();</script>
</section></div>"""
    return pagina("Buscar en Ramacontable", cuerpo, "", "Buscá notas, guías, datos del día, escalas salariales, calculadoras y planillas de Ramacontable.", "buscar.html", NOI)


def pagina_provincias(notas):
    tarj = ""
    for j in JURIS:
        datos = [t for t in TEMAS_RESP if t.get("jurisdiccion") == j["slug"] and ((RESP.get(t["slug"]) or {}).get("datos") or {}).get("valor")]
        li = "".join(f'<li><a href="{t["slug"]}.html"><b>{e(t["titulo"])}</b><span>{e(ajustar_tramo(RESP[t["slug"]]["datos"])["valor"])}</span></a></li>' for t in datos)
        tarj += (f'<section class="rama-guias"><h2><a href="{j["ruta"]}.html">{e(j["titulo_corto"])}</a></h2>'
                 f'<p class="ayuda">{e(j["descripcion"])}</p>' + (f'<ul class="lista-guias">{li}</ul>' if li else "")
                 + f'<p><a class="mas" href="{j["ruta"]}.html">Ver todo de {e(j["nombre"])} →</a></p></section>')
    otras = ""
    for o in OTRAS_J:
        rel = [n for n in notas if _de_jurisdiccion(n, o.get("claves") or [])][:3]
        if rel:
            otras += f'<h3>{e(o["nombre"])} <small>({e(o["organismo"])})</small></h3><ul>' + "".join(f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a></li>' for n in rel) + "</ul>"
    otras_html = ('<section class="rama-guias"><h2>Novedades de otras provincias</h2>' + otras + "</section>") if otras else \
        ('<section class="rama-guias"><h2>Otras provincias</h2><p class="ayuda">También seguimos las novedades de '
         + ", ".join(e(o["nombre"]) for o in OTRAS_J) + ". Cuando publiquen algo para la profesión, aparece acá.</p></section>")
    cuerpo = f"""<div class="grilla"><section><p class="miga"><a href="impuestos.html">Impuestos</a></p>
<h1 class="titsec">Impuestos provinciales y municipales</h1>
<p>Ingresos Brutos, regímenes simplificados, tasas municipales y vencimientos de cada provincia y municipio, con la norma y la fuente oficial de cada dato.</p>
{tarj}{otras_html}</section>{lateral(notas)}</div>"""
    return pagina("Impuestos provinciales y municipales: Ingresos Brutos y tasas por provincia | Ramacontable", cuerpo, "impuestos",
                  "Ingresos Brutos y regímenes simplificados de Buenos Aires, Córdoba y Santa Fe, tasas municipales como la Monotasa de La Plata, vencimientos y novedades por provincia.",
                  "provincias-y-municipios.html", migas=[("Impuestos", "impuestos.html"), ("Provincias y municipios", "provincias-y-municipios.html")])


_MES_NUM = {m: i + 1 for i, m in enumerate(MESES)}


def nota_vencida(n):
    """True si todas las fechas con mes que menciona la nota (título y dato clave) ya pasaron: se saca de la portada, sigue en su sección."""
    hoy = datetime.date.today()
    txt = _N(f"{n.get('titulo', '')} {n.get('clave', '')}")
    fechas = []
    for m in re.finditer(r"\b(" + "|".join(MESES) + r")\b(?:\s+(?:de\s+)?(\d{4}))?", txt):
        anio = int(m.group(2)) if m.group(2) else hoy.year
        fechas.append((anio, _MES_NUM[m.group(1)]))
    return bool(fechas) and all(f < (hoy.year, hoy.month) for f in fechas)


def es_tecnica(n):
    """Notas muy específicas que no van arriba en la portada (siguen en su sección y en la lista de abajo)."""
    return n["slug"].startswith("boletin-oficial-sumario")


def portada_inicio(notas, guias, convenios):
    """Portada: fecha de actualización, lo último, vencimientos, qué cambió, accesos, novedades por sección y las últimas 24 horas."""
    hoy = datetime.date.today()
    ahora_ar = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
    vigentes = [n for n in notas if not nota_vencida(n)]
    frescura = (f'<p class="fresco"><span class="punto"></span>Actualizado el {ahora_ar.day} de {MESES[ahora_ar.month - 1]} de {ahora_ar.year}, '
                f'a las {ahora_ar:%H:%M}</p>')
    item = lambda n: (f'<li><a href="nota-{n["slug"]}.html"><span class="ante">{e(n["antetitulo"].split("|")[0].strip())}</span>'
                      f'<b>{e(n["titulo"])}</b><small>{fecha_corta(str(n["fecha"]))}</small></a></li>')
    arriba = [n for n in vigentes if not es_tecnica(n)][:6]
    usados = {n["slug"] for n in arriba}
    ICO = {"sueldos": "💼", "impuestos": "🧾", "profesion": "📌"}
    def card(n):
        f = str(n["fecha"])[:10]
        dias = (hoy - datetime.date.fromisoformat(f)).days
        cuando = "Hoy" if dias == 0 else ("Ayer" if dias == 1 else fecha_corta(f))
        nuevo = '<span class="nuevo">Nuevo</span>' if dias <= 1 else ""
        return (f'<a class="ult sec-{n["seccion"]}" href="nota-{n["slug"]}.html"><span class="ult-top"><span class="ult-sec">{ICO.get(n["seccion"], "📌")} '
                f'{e(SECCIONES.get(n["seccion"], ""))}</span>{nuevo}<span class="ult-f">{cuando}</span></span>'
                f'<b>{e(n["titulo"])}</b><span class="ult-res">{e(n.get("clave") or n.get("encorto") or "")}</span></a>')
    bloque_ultimo = (f'<section class="ini-ultimo"><h2>Lo último</h2><div class="ult-g">{"".join(card(n) for n in arriba)}</div></section>') if arriba else ""

    prox = [x for x in proximos_vencimientos() if x["fecha"] <= (hoy + datetime.timedelta(days=7)).isoformat()][:5] or proximos_vencimientos(5)
    venc = ('<section class="ini-caja"><h2>📅 Vence esta semana</h2><ul class="venc">' + "".join(
        f'<li><span>{e(x["concepto"])}{(" · " + e(x["detalle"])) if x.get("detalle") else ""}</span><b>{fecha_corta(x["fecha"])}</b></li>' for x in prox)
        + '</ul><a class="mas" href="herramientas.html">Agenda completa por CUIT →</a></section>') if prox else ""

    # datos que más se buscan, en este orden: siempre la jubilación y los dos más importantes que tengan valor
    prioridad = ["jubilacion-minima-y-bono", "salario-minimo-vital-y-movil", "monotributo-categorias-vigentes", "tope-aportes-base-maxima",
                 "asignaciones-familiares-auh"]
    temas = {t["slug"]: t for t in TEMAS_RESP}
    elegidos = [sl for sl in prioridad if sl in temas and ajustar_tramo((RESP.get(sl) or {}).get("datos") or {}).get("valor")][:3]
    def fila_dato(sl):
        r = RESP.get(sl) or {}
        t = temas[sl]
        d = ajustar_tramo(r.get("datos") or {})
        mv, c = str(d.get("mes_vigente") or ""), str(r.get("cambiado") or "")[:10]
        # «cambiado» puede ser la fecha en que la fábrica reescribió el dato: si hay mes vigente, se muestra ese
        cuando = f"{MESES[int(mv[5:7]) - 1].capitalize()} {mv[:4]}" if re.fullmatch(r"\d{4}-\d{2}", mv) else (("desde " + fecha_corta(c)) if c else "")
        return (f'<li><span><a href="{sl}.html">{e(t.get("titulo_corto") or t["titulo"].split(":")[0].split("(")[0].strip())}</a>'
                f'<small>{e(_corto(d.get("valor") or "", 44))}</small></span>'
                f'<b>{cuando}</b></li>')
    cambio = ('<section class="ini-caja"><h2>🔔 Datos clave de hoy</h2><ul class="venc">' + "".join(fila_dato(sl) for sl in elegidos)
              + '</ul><a class="mas" href="datos-al-dia.html">Todos los datos del día →</a></section>') if elegidos else ""

    hechas = {g["slug"] for g in guias}
    top_guias = [(s_, t_) for s_, t_ in [("guia-sac-aguinaldo", "Aguinaldo"), ("guia-categorias-comercio", "Categorías de Comercio"),
                                         ("guia-sumas-no-remunerativas", "Sumas no remunerativas"), ("guia-vacaciones", "Vacaciones"),
                                         ("guia-liquidacion-final", "Liquidación final")] if s_ in hechas]
    conv = sorted(convenios, key=lambda c: PRINCIPALES.index(c["slug"]) if c["slug"] in PRINCIPALES else 99)
    conv = [c for c in conv if c["slug"] in PRINCIPALES] + [c for c in conv if c["slug"] == "gastronomicos"]
    chips = lambda xs: "".join(f'<a href="{u}">{e(t)}</a>' for u, t in xs)
    recursos = f"""<section class="ini-recursos"><h2>Lo más consultado</h2>
<div class="ini-rec"><b>📊 Escalas</b><div class="chips">{chips([(f"escala-{c['slug']}.html", c["nombre"]) for c in conv[:6]] + [("convenios.html", f"Todas ({len(convenios)}) →")])}</div></div>
<div class="ini-rec"><b>📚 Guías</b><div class="chips">{chips([(f"nota-{s_}.html", t_) for s_, t_ in top_guias] + ([(RUTA_FACIL + ".html", "🙋 " + SECCION_FACIL)] if EXPLICADO else []) + [("guias.html", "Todas →")])}</div></div>
<div class="ini-rec"><b>🧮 Calculadoras</b><div class="chips">{chips([("aguinaldo.html", "Aguinaldo"), ("liquidacion-final.html", "Liquidación final"), ("vacaciones.html", "Vacaciones"), ("intereses-arca.html", "Intereses de ARCA"), ("monotributo-categoria.html", "Categoría de Monotributo"), ("calculadoras.html", "Todas →")])}</div></div>
<div class="ini-rec"><b>📅 Calendario</b><div class="chips">{chips([("feriados.html", "Feriados " + str(hoy.year))] + [(u + ".html", "Feriados " + u[-4:]) for u in FERIADOS_URLS if u[-4:] != str(hoy.year)] + [("herramientas.html", "Vencimientos"), ("cuando-cambia-cada-dato.html", "Cuándo cambia cada dato")])}</div></div>
<div class="ini-rec"><b>📍 Provincias</b><div class="chips">{chips([(j["ruta"] + ".html", j["titulo_corto"]) for j in JURIS][:6] + [("provincias-y-municipios.html", "Todas →")])}</div></div>
</section>"""

    resto = [n for n in vigentes if n["slug"] not in usados]
    cols = ""
    for k, nombre in SECCIONES.items():
        xs = [n for n in resto if n["seccion"] == k and not es_tecnica(n)][:2]
        if xs:
            usados |= {n["slug"] for n in xs}
            cols += (f'<div class="ini-sec"><h3><a href="{k}.html">{e(nombre)}</a></h3><ul>'
                     + "".join(f'<li><a href="nota-{n["slug"]}.html">{e(n["titulo"])}</a><small>{fecha_corta(str(n["fecha"]))}</small></li>' for n in xs)
                     + f'</ul><a class="mas" href="{k}.html">Más de {e(nombre)} →</a></div>')
    por_sec = f'<section class="ini-secciones"><h2>Por sección</h2><div class="ini-sec-g">{cols}</div></section>' if cols else ""

    # últimas 24 horas (si no hubo nada, lo del último día con novedades) y el resto plegado en «Ver más»
    quedan = [n for n in vigentes if n["slug"] not in usados]
    ayer = (hoy - datetime.timedelta(days=1)).isoformat()
    recientes = [n for n in quedan if str(n["fecha"])[:10] >= ayer]
    tit24 = "Últimas 24 horas"
    if not recientes and quedan:
        ult = str(quedan[0]["fecha"])[:10]
        recientes, tit24 = [n for n in quedan if str(n["fecha"])[:10] == ult], f"Novedades del {fecha_corta(ult)}"
    mas = [n for n in quedan if n not in recientes][:25]
    todas = ""
    if recientes or mas:
        todas = (f'<section class="ini-mas"><h2>{tit24}</h2><ul class="ini-lista">{"".join(item(n) for n in recientes)}</ul>'
                 + (f'<details class="ini-vermas"><summary>Ver más novedades ({len(mas)})</summary><ul class="ini-lista">{"".join(item(n) for n in mas)}</ul>'
                    f'<p class="mas"><a href="sueldos.html">Sueldos</a> · <a href="impuestos.html">Impuestos</a> · <a href="profesion.html">Profesión</a></p></details>' if mas else "")
                 + "</section>")

    cuerpo = (f'<div class="grilla"><section><h1 class="oculto">Ramacontable, la comunidad contable: novedades impositivas y laborales, guías y calculadoras</h1>'
              f'{frescura}{bloque_ultimo}<div class="ini-dos">{venc}{cambio}</div>{recursos}{por_sec}{todas}</section>'
              f'{_lateral(notas, "") if venc else lateral(notas)}</div>')
    ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "CollectionPage", "name": "Ramacontable",
        "url": sitio_url(), "dateModified": ahora_ar.strftime("%Y-%m-%dT%H:%M:00-03:00"), "inLanguage": "es-AR",
        "mainEntity": {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": f"{sitio_url()}nota-{n['slug']}.html"}
                                                                 for i, n in enumerate(arriba)]}}, ensure_ascii=False) + "</script>"
    return pagina("Ramacontable | Comunidad contable", cuerpo, "", "Novedades contables, impositivas y laborales explicadas claro, escalas salariales, guías, calculadoras y vencimientos.", "", ld)


def franja_empeza():
    """Accesos de la portada para quien no es contador: lo más usado, en una fila."""
    hoy = datetime.date.today()
    vto = datetime.date(hoy.year, 12, 18) if hoy.month >= 7 else datetime.date(hoy.year, 6, 30)
    items = [(g["ruta"] + ".html", "📘", "Monotributo explicado fácil", "Qué pagás, qué factura hacer y cuándo recategorizarte") for g in EXPLICADO]
    items += [("aguinaldo.html", "🧮", "Calculadora de aguinaldo", f"Se paga hasta el {vto.day}/{vto.month}"),
              ("monotributo-categoria.html", "🏷️", "¿Qué categoría me toca?", "Monotributo según lo que facturás"),
              ("herramientas.html", "📅", "Vencimientos del mes", "Por terminación de CUIT")]
    return ('<section class="empeza"><h2>Empezá por acá</h2><div class="empeza-g">'
            + "".join(f'<a href="{u}"><span>{i}</span><b>{e(t)}</b><small>{e(d)}</small></a>' for u, i, t, d in items) + "</div></section>")


def portada(notas, titulo_pag="Ramacontable | Comunidad contable", actual="", encabezado="", extra=""):
    if not notas:
        lista = '<p class="vacio">Todavía no hay notas en esta sección.</p>'
        if actual:
            PAGINAS_FINAS.add(actual)
    else:
        lista = tarjeta(notas[0], grande=True) + '<div class="tarjetas">' + "".join(tarjeta(n) for n in notas[1:]) + "</div>"
    cab = f'<h1 class="titsec">{e(encabezado)}</h1>' if encabezado else '<h1 class="oculto">Ramacontable, la comunidad contable: novedades impositivas y laborales, guías y calculadoras</h1>'
    desc = DESC_SECCION.get(actual, "Novedades contables, impositivas y laborales explicadas claro, escalas salariales, guías, calculadoras y vencimientos.")
    return pagina(titulo_pag, f'<div class="grilla"><section>{cab}{extra}{lista}</section>{lateral(notas)}</div>', actual, desc,
                  f"{actual}.html" if actual else "", migas=[(encabezado, f"{actual}.html")] if actual else None)


def _plano(x):
    """Texto corrido de cualquier estructura de la nota (cuerpo, listas, tablas)."""
    if isinstance(x, str):
        return texto_plano(x)
    if isinstance(x, list):
        return " ".join(t for t in (_plano(y) for y in x) if t)
    if isinstance(x, dict):
        return " ".join(t for t in (_plano(v) for v in x.values()) if t)
    return ""


def para_shorts(notas, dias=14, tope=25):
    """datos/para-shorts.json: notas publicadas de los últimos días + próximos vencimientos, para la fábrica de
    videos (shorts-fabrica). Solo entran notas publicadas: las que están en revisión nunca llegan acá."""
    desde = (datetime.date.today() - datetime.timedelta(days=dias)).isoformat()
    base = sitio_url()
    lista = []
    for n in notas:
        if str(n.get("fecha", ""))[:10] < desde or n.get("motivo_revision"):
            continue
        cuerpo = n.get("cuerpo")
        if isinstance(cuerpo, str):
            try:
                cuerpo = json.loads(cuerpo)
            except Exception:
                pass
        preguntas = n.get("preguntas")
        if isinstance(preguntas, str):
            try:
                preguntas = json.loads(preguntas)
            except Exception:
                preguntas = []
        lista.append({
            "slug": n["slug"], "url": f"{base}nota-{n['slug']}.html", "fecha": str(n.get("fecha", ""))[:10],
            "tipo": n.get("tipo", ""), "seccion": n.get("seccion", ""), "antetitulo": n.get("antetitulo", ""),
            "titulo": n.get("titulo", ""), "encorto": n.get("encorto", ""), "clave": n.get("clave", ""),
            "dato": n.get("dato", ""), "fuente": n.get("fuente", ""), "texto": _plano(cuerpo)[:6000],
            "preguntas": [q for q in (preguntas or []) if isinstance(q, dict)][:5],
        })
        if len(lista) >= tope:
            break
    return {"actualizado": datetime.datetime.now().isoformat(timespec="minutes"), "sitio": base,
            "notas": lista, "vencimientos": proximos_vencimientos(40)}


def main():
    if os.path.exists(SALIDA):
        shutil.rmtree(SALIDA)
    shutil.copytree(os.path.join(RAIZ, "web"), SALIDA)
    global VENC
    VENC = cargar_vencimientos()
    cargar_respuestas()
    cargar_jurisdicciones()
    EXPLICADO[:] = cargar_explicado()
    # años con calendario de feriados propio (feriados/AAAA.json): se cargan antes de armar menú y portada
    FERIADOS_URLS[:] = sorted(f"feriados-{os.path.basename(r)[:4]}" for r in glob.glob(os.path.join(RAIZ, "feriados", "*.json")))
    notas = cargar_notas()
    with open(os.path.join(SALIDA, "config.js"), "w", encoding="utf-8") as f:
        f.write("window.RC_CONFIG=" + json.dumps({
            "url": os.environ.get("SUPABASE_URL", "").strip().rstrip("/"),
            "key": os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip(),
            "build": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }) + ";")
    escribir = lambda nombre, txt: open(os.path.join(SALIDA, nombre), "w", encoding="utf-8").write(txt)
    convenios = cargar_convenios()
    CONV_IDX.clear()
    CONV_IDX.update({c["slug"]: c for c in convenios})
    ENLACES[:] = _destinos_enlaces(convenios)
    todas = notas
    guias = [n for n in todas if es_guia(n)]
    GUIA_SAC[0] = any(n.get("slug") == "guia-sac-aguinaldo" for n in guias)
    notas = [n for n in todas if not es_guia(n)]
    try:
        catalogo = json.load(open(os.path.join(RAIZ, "guias", "catalogo.json"), encoding="utf-8"))
    except Exception:
        catalogo = []
    escribir("index.html", portada_inicio([n for n in notas if not nota_de_nicho(n)], guias, convenios))
    escribir("guias.html", pagina_guias(guias, notas, catalogo))
    for imp in IMPUESTOS:
        escribir(f"impuesto-{imp[0]}.html", pagina_impuesto(imp, notas, guias, catalogo))
    for k, v in SECCIONES.items():
        extra = ""
        if k == "sueldos":
            extra = ('<div class="conv-chips"><b>Escalas por convenio:</b> ' + " ".join(
                f'<a href="escala-{c["slug"]}.html">{e(c["nombre"])}</a>' for c in sorted(convenios, key=lambda c: PRINCIPALES.index(c["slug"]) if c["slug"] in PRINCIPALES else 99)[:5])
                + f' <a class="mas-chip" href="convenios.html">Más convenios ({len(convenios)}) →</a></div>')
        if k == "impuestos":
            extra = ('<div class="conv-chips"><b>Por impuesto:</b> ' + " ".join(
                f'<a href="impuesto-{s}.html">{e(n)}</a>' for s, n, _, _ in IMPUESTOS) + "</div>")
        if k in RAMAS_GUIAS:
            extra += tira_guias(guias, k)
        escribir(f"{k}.html", portada([n for n in notas if n["seccion"] == k], f"{TITULO_SECCION.get(k, v)} | Ramacontable", k, v, extra))
    aportes = cargar_aportes()
    import portadas
    if portadas.disponible():
        portadas.bajar_fuentes()
        for n in todas:
            try:
                portadas.generar(n, os.path.join(SALIDA, "compartir", f"{n['slug']}.png"))
                PORTADAS_OK.add(n["slug"])
            except Exception as ex:
                print("Aviso: no pude armar la portada de", n["slug"], ex)
    else:
        print("Aviso: falta Pillow; las notas se comparten con la imagen general")
    for n in todas:
        escribir(f"nota-{n['slug']}.html", pagina_nota(n, guias if es_guia(n) else notas, aportes.get(n['slug'])))
    escribir("herramientas.html", pagina_vencimientos(notas))
    with open(os.path.join(RAIZ, "paginas", "terminos.html"), encoding="utf-8") as f:
        escribir("terminos.html", pagina("Términos y condiciones y política de privacidad | Ramacontable", f.read(), "",
                 "Términos de uso, política de privacidad y tratamiento de datos de Ramacontable, la comunidad contable con novedades, guías y calculadoras.", "terminos.html"))
    with open(os.path.join(RAIZ, "paginas", "como-trabajamos.html"), encoding="utf-8") as f:
        escribir("como-trabajamos.html", pagina("Quiénes somos y cómo trabajamos | Ramacontable", f.read(), "",
                 "Ramacontable es una comunidad de contadores públicos que colaboran para estar al día con las novedades, y ayudar a colegas, estudiantes y emprendedores.",
                 "como-trabajamos.html"))
    with open(os.path.join(RAIZ, "paginas", "aguinaldo.html"), encoding="utf-8") as f:
        escribir("aguinaldo.html", pagina("Calculadora de aguinaldo diciembre 2026 (SAC) paso a paso | Ramacontable", f.read(), "",
                 "Calculá el aguinaldo de diciembre 2026: mensualizados y jornalizados, proporcional por días, descuentos y neto, con el cálculo paso a paso.",
                 "aguinaldo.html", herramienta_ld("Calculadora de aguinaldo (SAC)", "Calculá el aguinaldo con el cálculo paso a paso, descuentos y neto.", "aguinaldo.html"),
                 [("Calculadoras", "calculadoras.html"), ("Aguinaldo", "aguinaldo.html")]))
    with open(os.path.join(RAIZ, "paginas", "nota-dinamica.html"), encoding="utf-8") as f:
        escribir("nota.html", pagina("Nota | Ramacontable", f.read(), "", "", "nota.html", NOI))
    with open(os.path.join(RAIZ, "paginas", "admin.html"), encoding="utf-8") as f:
        escribir("admin.html", pagina("Administración | Ramacontable", f.read(), "", "", "admin.html", NOI))
    escribir("convenios.html", pagina_convenios(convenios, notas))
    if os.environ.get("RC_SIN_SERIES") != "1":
        bajar_series(os.path.join(SALIDA, "datos"))
    escribir_feriados(os.path.join(SALIDA, "datos"))
    if os.environ.get("RC_SIN_SERIES") != "1":
        bajar_dolares(os.path.join(SALIDA, "datos"))
    for t in TEMAS_RESP:
        escribir(t["slug"] + ".html", pagina_respuesta(t, RESP.get(t["slug"]), notas, aportes.get("dato-" + t["slug"])))
    for x in DOLARES:
        h = pagina_dolar(*x, notas)
        if h:
            escribir(x[0] + ".html", h)
    h = pagina_dolar_hub(notas)
    if h:
        escribir("dolar-hoy.html", h)
    for b in BCRA_RESP:
        h = pagina_bcra(*b, notas)
        if h:
            escribir(b[0] + ".html", h)
    for o in OBLIGACIONES:
        escribir(o[0] + ".html", pagina_obligacion(*o, notas))
    for pm in PAGINAS_MES:
        for m in _meses_paginas():
            h = pagina_mes(*pm, m, notas)
            if h:
                escribir(f"{pm[0]}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html", h)
    for c in convenios:
        for m in _meses_paginas():
            escribir(f"paritarias-{c['slug']}-{MESES[int(m[5:]) - 1]}-{m[:4]}.html", pagina_paritaria(c, m, notas))
    for ruta in glob.glob(os.path.join(RAIZ, "feriados", "*.json")):
        anio, h = pagina_feriados_anio(ruta, notas)
        escribir(f"feriados-{anio}.html", h)
        if f"feriados-{anio}" not in FERIADOS_URLS:
            FERIADOS_URLS.append(f"feriados-{anio}")
    for m in meses_que_cambia():
        url, h = pagina_que_cambia(m, notas)
        escribir(url + ".html", h)
        QUE_CAMBIA_URLS.append(url)
    escribir("cuando-cambia-cada-dato.html", pagina_calendario_datos(notas))
    if EXPLICADO:
        vids = videos_capitulos()
        for g in EXPLICADO:
            escribir(g["ruta"] + ".html", pagina_explicado_facil(g, notas, vids))
        escribir(RUTA_FACIL + ".html", pagina_guias_para_todos(notas))
    for j in JURIS:
        escribir(j["ruta"] + ".html", pagina_jurisdiccion(j, notas))
        for pg in j.get("paginas") or []:
            escribir(pg["ruta"] + ".html", pagina_extra_juris(j, pg, notas))
            TABLAS_URLS.append(pg["ruta"])
        for t in j.get("tablas") or []:
            try:
                escribir(t["ruta"] + ".html", pagina_tabla_juris(j, t, notas))
                TABLAS_URLS.append(t["ruta"])
            except Exception as ex:
                print("Aviso: no pude armar la tabla", t.get("ruta"), ex)
    escribir("provincias-y-municipios.html", pagina_provincias(notas))
    JURIS_URLS[:] = ["provincias-y-municipios"] + [j["ruta"] for j in JURIS] + TABLAS_URLS
    g = pagina_glosario(notas)
    if g:
        escribir("glosario.html", g)
    escribir("comparador-escalas.html", pagina_comparador(convenios, notas))
    escribir("buscar.html", pagina_buscar(notas, guias, convenios))
    escribir(os.path.join("datos", "vencimientos.json"), json.dumps(proximos_vencimientos(), ensure_ascii=False))
    escribir("datos-al-dia.html", pagina_datos(notas))
    os.makedirs(os.path.join(SALIDA, "datos"), exist_ok=True)
    escribir(os.path.join("datos", "datos-del-dia.json"), json.dumps(datos_para_calculadoras(), ensure_ascii=False))
    try:
        escribir(os.path.join("datos", "para-shorts.json"), json.dumps(para_shorts(notas), ensure_ascii=False))
    except Exception as ex:  # el puente con la fábrica de videos nunca tiene que frenar la web
        print("Aviso: no pude armar datos/para-shorts.json:", ex)
    por_slug = {c["slug"]: c for c in convenios}
    def calc_conv(archivo, salida_html, slug, titulo, desc):
        c = por_slug.get(slug) or {}
        datos = dict(c.get("escala") or {}, slug=slug)
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            cuerpo = f.read().replace('<script src="sueldo.js', '<script>window.RC_ESCALA=' + json.dumps(datos, ensure_ascii=False).replace("</", "<\\/") + ';</script><script src="sueldo.js')
        escribir(salida_html, pagina(titulo, cuerpo, "", desc, salida_html, herramienta_ld(titulo.split(":")[0].split(" | ")[0], desc, salida_html),
                                     [("Calculadoras", "calculadoras.html"), (titulo.split(":")[0].split(" | ")[0], salida_html)]))
    calc_conv("sueldo-comercio.html", "sueldo-comercio.html", "comercio", "Calculadora de sueldo Empleados de Comercio 2026: neto con antigüedad y presentismo | Ramacontable",
              "Calculá el sueldo de comercio con la escala vigente: básico por categoría, antigüedad, presentismo, sumas no remunerativas, descuentos y neto.")
    calc_conv("sueldo-casas.html", "sueldo-casas-particulares.html", "casas-particulares", "Sueldo de empleadas domésticas 2026: calculadora por hora y mes | Ramacontable",
              "Calculá el sueldo de casas particulares por categoría, con o sin retiro, mensual o por hora, con antigüedad y zona desfavorable.")
    CALCS = [("actualizacion.html", "Calculadora de actualización de montos por inflación, CER, UVA, dólar y tasas", "Actualizá montos y deudas entre dos fechas con datos oficiales del BCRA: inflación, CER, UVA, ICL, dólar oficial y tasas."),
             ("dias-habiles.html", "Calculadora de días hábiles 2026 con feriados", "Contá días hábiles entre dos fechas o calculá el vencimiento de un plazo, descontando sábados, domingos y feriados nacionales."),
             ("plazo-fijo.html", "Simulador de plazo fijo: intereses y TEA", "Calculá los intereses de un plazo fijo, la TEA y cuánto tenés si lo renovás, con la tasa promedio del BCRA."),
             ("prestamos.html", "Calculadora de préstamos: cuota y cuadro de amortización", "Calculá la cuota de un préstamo en sistema francés o alemán, el total de intereses y el cuadro de amortización."),
             ("vacaciones.html", "Calculadora de vacaciones 2026: días y cuánto se cobra", "Calculá los días de vacaciones según antigüedad y cuánto se cobra: sueldo ÷ 25 y plus vacacional (LCT arts. 150 a 157)."),
             ("liquidacion-final.html", "Calculadora de liquidación final e indemnización por despido 2026", "Calculá la liquidación final por renuncia o despido: indemnización art. 245, preaviso, integración, SAC y vacaciones proporcionales."),
             ("horas-extras.html", "Calculadora de horas extras al 50% y al 100%", "Calculá el valor de las horas extras al 50% y al 100% a partir del sueldo y la jornada (art. 201 LCT)."),
             ("feriado-trabajado.html", "Calculadora de feriado trabajado: cuánto se paga", "Calculá cuánto te pagan si trabajás un feriado nacional o un día no laborable: mensualizados (sueldo ÷ 25) y jornalizados (horas × 2)."),
             ("iva.html", "Calculadora de IVA: agregar o quitar IVA", "Sumá o quitá el IVA de un importe con alícuotas del 21%, 10,5%, 27% y otras."),
             ("conversor-dolar.html", "Conversor de dólar a pesos: oficial, MEP, CCL, tarjeta, cripto y blue", "Convertí pesos a dólares y dólares a pesos con las cotizaciones de hoy: oficial, mayorista, MEP, CCL, tarjeta, cripto y blue."),
             ("monotributo-categoria.html", "Calculadora de categoría del Monotributo 2026", "Cargá lo que facturaste en los últimos 12 meses y mirá en qué categoría del Monotributo estás y cuánto pagás por mes."),
             ("monotributo-o-responsable-inscripto.html", "¿Monotributo o Responsable Inscripto? Calculadora 2026", "Compará cuánto te queda por año como monotributista y como Responsable Inscripto: IVA, Ganancias, autónomos e Ingresos Brutos con valores vigentes."),
             ("intereses-arca.html", "Calculadora de intereses resarcitorios de ARCA", "Calculá los intereses por pagar tarde un impuesto o aporte a ARCA, con la tasa vigente y los días de atraso."),
             ("actualizacion-alquiler.html", "Calculadora de actualización de alquiler por ICL o IPC", "Calculá cuánto aumenta tu alquiler por ICL o por inflación (IPC) entre dos fechas, con datos oficiales del BCRA."),
             ("agenda-vencimientos.html", "Agenda de vencimientos por CUIT", "Cargá la terminación de CUIT de tus clientes y mirá solo sus vencimientos de ARCA, con descarga al calendario."),
             ("retencion-ganancias.html", "Calculadora de retención de Ganancias sobre el sueldo 2026", "Estimá cuánto te retienen de Ganancias por mes en el sueldo, con las deducciones y la escala vigentes."),
             ("embargo-sueldo.html", "Calculadora de embargo de sueldo 2026 (Decreto 484/87)", "Calculá cuánto se puede embargar de un sueldo según el salario mínimo vigente: inembargable hasta 1 SMVM, 10% y 20% del excedente.")]
    for k in PROX_SEMESTRAL:
        r_, h_ = pagina_proximo_semestral(k, notas)
        escribir(r_ + ".html", h_)
    h_facpce = pagina_indices_facpce(notas)
    if h_facpce:
        escribir("indices-facpce.html", h_facpce)
    for archivo, titulo, desc in CALCS:
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            escribir(archivo, pagina(titulo + " | Ramacontable", f.read(), "", desc, archivo, herramienta_ld(titulo, desc, archivo),
                                     [("Calculadoras", "calculadoras.html"), (titulo.split(":")[0], archivo)]))
    for archivo, titulo, desc in [("calculadoras.html", "Calculadoras de sueldos y aguinaldo | Ramacontable", "Calculadoras gratuitas para liquidar sueldos: comercio, casas particulares y aguinaldo, con escalas vigentes."),
                                  ("feriados.html", "Feriados 2026 Argentina: calendario completo y cómo se pagan | Ramacontable", "Calendario de feriados 2026 en Argentina: inamovibles, trasladables y días no laborables, y cómo se liquida trabajar un feriado.")]:
        with open(os.path.join(RAIZ, "paginas", archivo), encoding="utf-8") as f:
            cuerpo = f.read()
        if archivo == "feriados.html":
            extra = [x for fila in VENC for x in fila.get("feriados") or [] if f'data-f="{x["fecha"]}"' not in cuerpo]
            if extra:
                filas = "".join(f'<tr data-f="{e(x["fecha"])}"><td>{int(x["fecha"][8:])}/{int(x["fecha"][5:7])}</td><td>{e(x["nombre"])}'
                                + (f' ({e(x["norma"])})' if x.get("norma") else "") + f'</td><td><span class="tipo-f t-no ">{e(x.get("tipo",""))}</span></td></tr>' for x in extra)
                cuerpo = cuerpo.replace("</tbody></table></div>", "</tbody></table></div>" + '<h2>Feriados y días no laborables agregados durante el año</h2><div class="tabla"><table class="feriados"><thead><tr><th>Fecha</th><th>Detalle</th><th>Tipo</th></tr></thead><tbody>' + filas + "</tbody></table></div>", 1)
        escribir(archivo, pagina(titulo, cuerpo, "", desc, archivo))
    for c in convenios:
        escribir(f"escala-{c['slug']}.html", pagina_convenio(c, notas, aportes.get("convenio-" + c["slug"])))
    PARITARIAS_URLS[:] = [f"paritarias-{c['slug']}-{MESES[int(m[5:]) - 1]}-{m[:4]}" for c in convenios for m in _meses_paginas()]
    mapa, noticias, robots = sitemaps(todas, convenios)
    escribir("sitemap.xml", mapa)
    escribir("sitemap-noticias.xml", noticias)
    escribir("robots.txt", robots)
    escribir("llms.txt", llms_txt(todas, convenios))
    clave_in = "rc" + __import__("hashlib").sha1(sitio_url().encode()).hexdigest()[:30]
    escribir(clave_in + ".txt", clave_in)
    escribir("indexnow.json", json.dumps({"key": clave_in, "urls": urls_indexnow(todas, convenios)}))
    escribir(".nojekyll", "")
    print(f"Listo: {len(notas)} notas en {SALIDA}")


if __name__ == "__main__":
    main()
