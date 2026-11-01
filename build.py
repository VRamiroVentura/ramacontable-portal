"""Arma la web estática del portal Ramacontable.

Lee las notas de la carpeta notas/ (un .json por nota) y genera en sitio/:
portada, una página por sección y una página por nota.
Las claves públicas de Supabase se toman de las variables de entorno
SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY (en GitHub vienen de los Secrets).
"""
import html, json, os, re, shutil, glob, datetime, urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(RAIZ, "sitio")

SECCIONES = {
    "sueldos": "Sueldos",
    "impuestos": "Impuestos",
    "profesion": "Profesión",
    "economia": "Economía",
}
REDES = {
    "Instagram": "https://www.instagram.com/ramacontable",
    "YouTube": "https://www.youtube.com/@ramacontable",
    "TikTok": "https://www.tiktok.com/@ramacontable",
}
MAIL = "ramacontable@gmail.com"
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


def cargar_notas():
    notas = []
    for ruta in glob.glob(os.path.join(RAIZ, "notas", "*.json")):
        with open(ruta, encoding="utf-8") as f:
            n = json.load(f)
        notas.append(n)
    notas.sort(key=lambda n: (n["fecha"], n["slug"]), reverse=True)
    return notas


ICONOS = {
    "Instagram": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>',
    "YouTube": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="4"/><path d="M10 9l5 3-5 3z" fill="currentColor"/></svg>',
    "TikTok": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3v11a4 4 0 1 1-4-4"/><path d="M14 3c.5 3 2.5 5 5 5"/></svg>',
}


def pagina(titulo, cuerpo, actual="", descripcion=""):
    menu = "".join(
        f'<a href="{k}.html"{" aria-current=page" if k == actual else ""}>{v}</a>'
        for k, v in SECCIONES.items())
    redes = "".join(
        f'<a href="{u}" target="_blank" rel="noopener" aria-label="{n}">{ICONOS[n]}</a>'
        for n, u in REDES.items())
    anio = datetime.date.today().year
    return f"""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)}</title>
<meta name="description" content="{e(descripcion or 'Novedades contables, impositivas y laborales explicadas claro, y una comunidad que muestra cómo se aplican.')}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=swap">
<link rel="stylesheet" href="estilos.css">
<link rel="icon" href="logo.svg" type="image/svg+xml">
</head><body>
<header class="cab"><div class="wrap fila">
<a class="logo" href="index.html">{LOGO_SVG}<span>ramacontable</span></a>
<nav class="menu">{menu}<a class="chico" href="herramientas.html">Vencimientos</a></nav>
<div id="sesion" class="sesion"><button class="btn" data-ingresar>Ingresar</button></div>
</div></header>
<main class="wrap">{cuerpo}</main>
<footer class="pie"><div class="wrap">
<a class="logo" href="index.html">{LOGO_SVG}<span>ramacontable</span></a>
<p>Novedades de la profesión contable explicadas claro.</p>
<div class="redes">{redes}</div>
<p><a href="mailto:{MAIL}">{MAIL}</a></p>
<p class="legal">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. · <a href="terminos.html">Términos y privacidad</a> · © {anio} Ramacontable</p>
</div></footer>
<div id="modal" class="modal" hidden></div>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js"></script>
<script src="vendor/purify.min.js"></script>
<script src="vendor/jszip.min.js"></script>
<script src="config.js"></script>
<script src="editor.js"></script>
<script src="app.js"></script>
</body></html>"""


def tarjeta(n, grande=False):
    clase = "tarjeta grande" if grande else "tarjeta"
    pastilla = f'<span class="pastilla">{e(n["dato"])}</span>' if n.get("dato") else ""
    return f"""<a class="{clase}" href="nota-{n['slug']}.html"><div class="tx">
<p class="ante">{e(n['antetitulo'])}</p><h2>{e(n['titulo'])}</h2>
{f"<p class='resumen'>{e(n['encorto'])}</p>" if grande else ""}
<p class="meta">{pastilla}{fecha_larga(n['fecha'])} · <span data-contador="{n['slug']}"></span></p></div></a>"""


def lateral(notas):
    esperando = "".join(
        f'<li><a href="nota-{n["slug"]}.html#aplica">{e(n["titulo"])}</a><span>Sé el primero en explicarlo</span></li>'
        for n in notas[:4])
    return f"""<aside class="lateral">
<section class="caja"><h3>Notas esperando su paso a paso</h3><ul class="esperando" id="esperando">{esperando}</ul></section>
<section class="caja" id="destacados" hidden><h3>Destacados de la comunidad</h3><ol id="ranking"></ol></section>
<section class="caja"><h3>Vencimientos que se vienen</h3><ul class="venc">
<li><span>DDJJ Ganancias 2025 (personas humanas)</span><b>16/11</b></li>
<li><span>Adhesión a planes de pago MiPyME y salud</span><b>30/12</b></li>
</ul><a class="mas" href="herramientas.html">Ver todos</a></section>
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
    return ""


def pagina_nota(n, notas, aportes=None):
    verif = ("Elaborada con fuentes oficiales." if n.get("verificada")
             else "Pendiente de verificación con fuente oficial.")
    cuerpo = "".join(bloque(b) for b in n["cuerpo"])
    sec = SECCIONES[n["seccion"]]
    contenido = f"""<div class="grilla"><article class="nota" data-nota="{n['slug']}">
<p class="miga"><a href="{n['seccion']}.html">{sec}</a></p>
<p class="ante">{e(n['antetitulo'])}</p>
<h1>{e(n['titulo'])}</h1>
<p class="firma">Redacción Ramacontable · {fecha_larga(n['fecha'])}</p>
<div class="encorto"><b>En corto</b><p>{e(n['encorto'])}</p></div>
{cuerpo}
<p class="fuente"><b>Fuente:</b> {e(n['fuente'])}</p>
<p class="aviso">Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. {verif}</p>

<div class="pestanas" role="tablist" id="aplica">
<button role="tab" aria-selected="true" data-tab="pasos">¿Cómo se aplica? <span data-n="pasos">0</span></button>
<button role="tab" aria-selected="false" data-tab="opiniones">Opiniones <span data-n="opiniones">0</span></button>
</div>
<section class="panel" data-panel="pasos">
<p class="ayuda">Mostrá cómo se liquida o se aplica esta novedad, paso a paso y explicando el porqué. Los más votados quedan arriba.</p>
<div id="lista-pasos" class="lista">{pasos_estaticos(aportes or [])}</div>
<button class="btn ancho" data-nuevo-paso>Subir mi paso a paso</button>
</section>
<section class="panel" data-panel="opiniones" hidden>
<p class="ayuda">¿Qué opinás de esta novedad? Tu comentario lo pueden votar los demás.</p>
<form id="form-opinion" class="form-op"><textarea name="texto" rows="3" maxlength="1500" placeholder="Escribí tu opinión" required></textarea><button class="btn">Publicar</button></form>
<div id="lista-opiniones" class="lista"></div>
</section>
</article>{lateral(notas)}</div>"""
    return pagina(f"{n['titulo']} | Ramacontable", contenido, n["seccion"], n["encorto"])


def portada(notas, titulo_pag="Ramacontable | Comunidad contable", actual="", encabezado=""):
    if not notas:
        lista = '<p class="vacio">Todavía no hay notas en esta sección.</p>'
    else:
        lista = tarjeta(notas[0], grande=True) + '<div class="tarjetas">' + "".join(tarjeta(n) for n in notas[1:]) + "</div>"
    cab = f'<h1 class="titsec">{e(encabezado)}</h1>' if encabezado else ""
    return pagina(titulo_pag, f'<div class="grilla"><section>{cab}{lista}</section>{lateral(notas)}</div>', actual)


def main():
    if os.path.exists(SALIDA):
        shutil.rmtree(SALIDA)
    shutil.copytree(os.path.join(RAIZ, "web"), SALIDA)
    notas = cargar_notas()
    with open(os.path.join(SALIDA, "config.js"), "w", encoding="utf-8") as f:
        f.write("window.RC_CONFIG=" + json.dumps({
            "url": os.environ.get("SUPABASE_URL", "").strip().rstrip("/"),
            "key": os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip(),
        }) + ";")
    escribir = lambda nombre, txt: open(os.path.join(SALIDA, nombre), "w", encoding="utf-8").write(txt)
    escribir("index.html", portada(notas))
    for k, v in SECCIONES.items():
        escribir(f"{k}.html", portada([n for n in notas if n["seccion"] == k], f"{v} | Ramacontable", k, v))
    aportes = cargar_aportes()
    for n in notas:
        escribir(f"nota-{n['slug']}.html", pagina_nota(n, notas, aportes.get(n['slug'])))
    with open(os.path.join(RAIZ, "paginas", "herramientas.html"), encoding="utf-8") as f:
        escribir("herramientas.html", pagina("Vencimientos | Ramacontable", f.read()))
    with open(os.path.join(RAIZ, "paginas", "terminos.html"), encoding="utf-8") as f:
        escribir("terminos.html", pagina("Términos y privacidad | Ramacontable", f.read()))
    escribir(".nojekyll", "")
    print(f"Listo: {len(notas)} notas en {SALIDA}")


if __name__ == "__main__":
    main()
