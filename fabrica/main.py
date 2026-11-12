"""Punto de entrada: python -m fabrica.main generar | publicar --base-url URL | reporte"""
import argparse
import html
import json
import os
import shutil
import sys

from . import util

SALIDA = util.RAIZ / "out"
SITIO = SALIDA / "sitio"


def _turno():
    """1 = el video de siempre; 2 = el segundo video del día (turnos.json)."""
    try:
        return 2 if int(os.getenv("TURNO") or 1) == 2 else 1
    except ValueError:
        return 1


def _turnos(cfg):
    """Turnos activos: el 1 siempre; el 2 si turnos.json tiene segundo_turno en true."""
    lista = [1]
    if cfg.get("segundo_turno") and cfg.get("plan_semanal_2") and cfg.get("horarios_2"):
        lista.append(2)
    return lista


def _horarios(cfg, turno):
    return (cfg.get("horarios_2") if turno == 2 else cfg.get("horarios")) or {}


def _carpeta(fecha, turno):
    return fecha if turno == 1 else f"{fecha}-t{turno}"


def _serie_del_dia(cfg, turno=None):
    forzada = (os.getenv("SERIE") or "").strip().lower()
    if forzada in cfg["series"]:
        return forzada
    dia = str(util.ahora().isoweekday())
    turno = turno or _turno()
    valor = (cfg.get("plan_semanal_2") or {}).get(dia) if turno == 2 else None
    if not valor:
        valor = cfg["plan_semanal"][dia]
    return _resolver_plan(cfg, valor, dia, turno)


# ---------------------------------------------------------------- franjas especiales de la grilla
# En plan_semanal, además del nombre de una serie, puede ir:
#   "a|b"           competencia: se alternan semana por semana y, al terminar la prueba, queda la que más puntúa
#   "mejor:a|b"     cada semana sale la que viene puntuando más (según el último reporte)
#   "capitulos"     series por capítulos (series/*.json); mientras no estén activas, va "capitulos_respaldo"
RENDIMIENTO = "data/rendimiento_series.json"


def puntaje_series():
    """{clave: puntaje} del último reporte. Puntaje = (vistas + 15·(guardados+compartidos) + 10·comentarios) / videos."""
    datos = util.leer_json(RENDIMIENTO, {}) or {}
    salida = {}
    for clave, a in (datos.get("series") or {}).items():
        n = max(1, int(a.get("posts", 0)))
        salida[clave] = (a.get("vistas", 0) + 15 * (a.get("guardados", 0) + a.get("compartidos", 0))
                         + 10 * a.get("comentarios", 0)) / n
    return salida


def _semana():
    return util.ahora().isocalendar()[1]


def _resolver_plan(cfg, valor, dia, turno):
    valor = str(valor or "").strip()
    series = cfg["series"]
    if valor in series and valor != "capitulos":
        return valor
    if valor == "capitulos":
        try:
            from . import capitulos  # llega con las series por capítulos
            clave = capitulos.serie_de_hoy(cfg)
            if clave:
                return clave
        except ImportError:
            pass
        respaldo = cfg.get("capitulos_respaldo", "monotributo")
        return respaldo if respaldo in series else cfg["plan_semanal"].get(dia)
    mejor = valor.startswith("mejor:")
    opciones = [x.strip() for x in valor.split(":", 1)[-1].split("|") if x.strip() in series]
    if not opciones:
        util.log(f"Grilla: «{valor}» no es una serie conocida; uso la del día por defecto.")
        return next(iter(series))
    if len(opciones) == 1:
        return opciones[0]
    puntos = puntaje_series()
    if mejor:
        con_datos = [o for o in opciones if o in puntos]
        if len(con_datos) == len(opciones):
            elegida = max(opciones, key=lambda o: puntos[o])
            util.log(f"Grilla: sale la mejor de {opciones}: {elegida} ({int(puntos[elegida])} puntos)")
            return elegida
        return opciones[_semana() % len(opciones)]
    # competencia: alternan durante la prueba y después queda la ganadora (se anota en estado.json)
    llave = f"{turno}-{dia}"
    estado = util.leer_json("data/estado.json", {}) or {}
    ganadas = estado.get("competencias_resueltas") or {}
    if ganadas.get(llave, {}).get("plan") == valor and ganadas[llave].get("ganadora") in series:
        return ganadas[llave]["ganadora"]
    prueba = (cfg.get("competencias") or {}).get(llave) or {}
    hasta = prueba.get("hasta", "")
    hoy = util.ahora().strftime("%Y-%m-%d")
    if hasta and hoy > hasta and all(o in puntos for o in opciones):
        ganadora = max(opciones, key=lambda o: puntos[o])
        ganadas[llave] = {"plan": valor, "ganadora": ganadora, "fecha": hoy,
                          "puntos": {o: int(puntos[o]) for o in opciones}}
        estado["competencias_resueltas"] = ganadas
        util.guardar_json("data/estado.json", estado)
        util.log(f"Grilla: terminó la competencia {opciones}; queda {ganadora}.")
        return ganadora
    return opciones[_semana() % len(opciones)]


def _series_con_carrusel(cfg):
    """Series que en Instagram salen SIEMPRE también como carrusel (config: "carrusel_series")."""
    return cfg.get("carrusel_series", ["monotributo"])


def _temas():
    return (util.leer_json("temas.json", {}) or {}).get("temas", [])


def _tema_pedido(turno):
    """Un tema puntual que pediste (temas.json) y todavía no salió. Va en lugar del tema del día."""
    if (os.getenv("SERIE") or "").strip():
        return None  # si elegiste una serie a mano, manda esa
    hechos = set((util.leer_json("data/estado.json", {}) or {}).get("temas_hechos", []))
    hoy = util.ahora().strftime("%Y-%m-%d")
    for t in _temas():
        if not t.get("id") or t["id"] in hechos or str(t.get("turno", 1)) != str(turno):
            continue
        if t.get("desde", "") > hoy or (t.get("hasta") and t["hasta"] < hoy):
            continue
        return t
    return None


def _tema_por_id(tema_id):
    t = next((t for t in _temas() if tema_id and t.get("id") == tema_id), None)
    if t or not tema_id:
        return t
    try:  # también puede ser un capítulo de una serie (series/*.json)
        from . import capitulos
        return capitulos.tema_por_id(tema_id)
    except Exception:  # noqa
        return None


def _serie_con_tema(serie, tema):
    s = dict(serie)
    s["prompt"] = (f'TEMA OBLIGATORIO DE HOY (lo pidió el dueño de la cuenta): {tema["titulo"]}.\n'
                   + tema.get("prompt", "").strip() + "\n"
                   "- Usá SOLO los datos del MATERIAL DE REFERENCIA, que están chequeados a mano. No agregues montos, "
                   "fechas, porcentajes ni requisitos que no estén ahí.")
    cierre = (tema.get("cierre") or {}).get("voz")
    if cierre:  # el cierre lo pone la fábrica: que el guion no lo anticipe ni lo repita
        s["prompt"] += ("\n- La última escena ya está escrita y la pone la fábrica: «" + cierre.strip() + "». Escribí el resto "
                        "para que termine justo antes de eso: no anticipes ni repitas esa idea ni sus palabras en la "
                        "escena anterior.")
    if tema.get("palabras_max"):
        s["palabras_max"] = tema["palabras_max"]
    return s


def _carrusel_tema(tema):
    """Placas fijas del tema (escritas y chequeadas a mano). Se respetan los % tal cual."""
    from . import escritor
    placas = []
    for x in tema.get("carrusel") or []:
        titulo = " ".join(str(x.get("titulo") or "").split())
        if titulo:
            placas.append({"titulo": escritor._siglas(titulo, True),
                           "cuerpo": escritor._siglas("\n".join(" ".join(ln.split()) for ln in
                                                                str(x.get("cuerpo") or "").split("\n") if ln.strip())),
                           "emoji": escritor._emoji(x.get("emoji"), "💡")})
    return placas[:10] if len(placas) >= 3 else []


_DIAS = {1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves", 5: "viernes", 6: "sábado", 7: "domingo"}


def _num(x, decimales):
    t = f"{x:,.{decimales}f}"
    return t.replace(",", "X").replace(".", ",").replace("X", ".")


def _cotizacion(d):
    """(precio, cierre anterior) de una cotización: Yahoo y, para monedas, AwesomeAPI de respaldo. None si no hay."""
    if d.get("yahoo"):
        try:
            from urllib.parse import quote
            r = util.pedir("GET", "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(d["yahoo"], safe=""),
                           intentos=2, timeout=30, params={"range": "1d", "interval": "5m"},
                           headers={"User-Agent": "Mozilla/5.0"})
            if r is not None and r.status_code == 200:
                meta = r.json()["chart"]["result"][0]["meta"]
                precio, previo = meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
                if precio and previo:
                    return float(precio), float(previo)
        except Exception as e:  # noqa
            util.log("No pude leer", d["yahoo"], "de Yahoo:", util.ocultar(e))
    if d.get("awesome"):
        try:
            r = util.pedir("GET", f'https://economia.awesomeapi.com.br/json/last/{d["awesome"]}', intentos=2, timeout=30)
            if r is not None and r.status_code == 200:
                x = next(iter(r.json().values()))
                precio = float(x["bid"])
                return precio, precio - float(x["varBid"])
        except Exception as e:  # noqa
            util.log("No pude leer", d["awesome"], "de AwesomeAPI:", util.ocultar(e))
    return None


def _datos_vivos(tema):
    """Cotizaciones del momento en que se arma el video, para contar «cómo estamos ahora» (vacío si no hay)."""
    lineas, leidas = [], {}
    signo = lambda v: ("+" if v >= 0 else "−") + _num(abs(v), 1) + "%"  # noqa
    for d in tema.get("datos_vivos") or []:
        res = _cotizacion(d)
        if not res:
            continue
        leidas[d.get("yahoo") or d.get("awesome")] = res
        precio, previo = res
        if d.get("referencia"):  # comparar contra un valor fijo (por ejemplo, el cierre antes de la elección)
            previo = float(d["referencia"])
        dec, unidad, contra = int(d.get("decimales", 2)), d.get("unidad", ""), d.get("contra", "el cierre anterior")
        if d.get("moneda"):  # una moneda contra el dólar: se cuenta cuánto perdió o ganó la moneda, no el dólar
            var = (previo / precio - 1) * 100
            lineas.append(f'- {d["nombre"]}: {"perdió" if var < 0 else "ganó"} {_num(abs(var), 1)}% de su valor contra '
                          f'el dólar desde {contra}. Hoy 1 dólar cuesta {_num(precio, dec)} {unidad} (antes, '
                          f'{_num(previo, dec)}).')
            for pr in d.get("precios") or []:  # ejemplos de gasto pasados a dólares, hechos acá (no por la IA)
                monto = float(pr["monto"])
                lineas.append(f'  · {pr["que"]}: {_num(monto, 0)} {unidad} = {_num(monto / precio, 0)} dólares hoy; '
                              f'antes eran {_num(monto / previo, 0)} dólares.')
            continue
        var = (precio / previo - 1) * 100
        linea = (f'- {d["nombre"]}: {_num(precio, dec)} {unidad} ({signo(var)} contra {contra}, que fue de '
                 f'{_num(previo, dec)} {unidad})')
        fx = leidas.get(d.get("en_dolares_con"))
        if fx:  # cuánto cayó medido en dólares (lo que ve un inversor de afuera)
            linea += f'; medido en dólares: {signo(((precio / previo) * (fx[1] / fx[0]) - 1) * 100)}'
        lineas.append(linea)
    if not lineas:
        return ""
    t = util.ahora()
    return (f"DATOS ACTUALIZADOS del {_DIAS[t.isoweekday()]} {t:%d/%m} a las {t:%H:%M} (hora de Argentina). Son los más "
            "nuevos: usalos para contar cómo está todo ahora, diciendo el día y el momento (por ejemplo «el lunes a la "
            "tarde»), y lo de la apertura solo como contexto.\n" + "\n".join(lineas))


def _aplicar_cierre(contenido, tema):
    """Si el tema trae un cierre fijo (por ejemplo una pregunta para que la gente comente), va en la última escena."""
    cierre = (tema or {}).get("cierre") or {}
    if not cierre.get("voz") or not contenido.get("escenas"):
        return contenido
    from . import escritor
    escenas = [dict(e) for e in contenido["escenas"]]
    escenas[-1]["texto_voz"] = escritor._limpiar(cierre["voz"], voz=True)
    escenas[-1]["texto_pantalla"] = escritor._siglas(escritor._limpiar(cierre.get("pantalla") or cierre["voz"]))
    if cierre.get("emoji"):
        escenas[-1]["emoji"] = cierre["emoji"]
    return dict(contenido, escenas=escenas,
                palabras=sum(len(e["texto_voz"].split()) for e in escenas))


def _fuente_tema(tema):
    datos = tema["datos"]
    vivo = _datos_vivos(tema)
    if vivo:
        util.log("Datos del momento:", vivo.split("\n", 1)[-1])
        datos = vivo + "\n\n" + datos
    elif tema.get("datos_vivos"):
        util.avisar("No pude leer las cotizaciones del momento", "El guion usa solo los datos cargados en temas.json.")
    return {"id": "tema:" + tema["id"], "tipo": "noticia", "canal": tema.get("fuente", "normativa oficial"),
            "titulo": tema["titulo"], "publicado": tema.get("fecha_datos", ""), "transcripcion": datos}


def _marcar_tema(p, resultados):
    """El tema pedido ya salió en alguna red: no se repite."""
    if not p.get("tema_id") or not any(r.get("ok") for r in resultados.values()):
        return
    estado = util.leer_json("data/estado.json", {}) or {}
    hechos = estado.get("temas_hechos", [])
    if p["tema_id"] not in hechos:
        estado["temas_hechos"] = hechos + [p["tema_id"]]
        util.guardar_json("data/estado.json", estado)


def _base_paginas():
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return None
    duenio, nombre = repo.split("/", 1)
    return f"https://{duenio.lower()}.github.io/{nombre}/"


def _dias_pagina():
    """Cuántos días quedan los videos en la página (config.json → dias_en_pagina)."""
    try:
        return max(1, int(util.config().get("dias_en_pagina", 7)))
    except (TypeError, ValueError):
        return 7


def _traer_anteriores(actual):
    """La página de GitHub se reemplaza entera en cada corrida. Traigo los videos de los últimos días (dias_en_pagina)
    para que los links de los mails (y el video para TikTok) sigan andando."""
    base = _base_paginas()
    desde = (util.ahora() - util.timedelta(days=_dias_pagina())).strftime("%Y-%m-%d")
    quedan = [x for x in util.leer_json("data/sitio.json", []) or []
              if x.get("fecha", "") >= desde and x.get("carpeta") != actual]
    if not base:
        return quedan
    for x in quedan:
        for rel in x.get("archivos", []):
            try:
                r = util.pedir("GET", base + rel, intentos=2, timeout=120)
                if r is not None and r.status_code == 200:
                    destino = SITIO / rel
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    destino.write_bytes(r.content)
            except Exception as e:  # noqa
                util.log("No pude traer", rel, util.ocultar(e))
    return quedan


def _serie(cfg, clave_serie):
    serie = dict(cfg["series"][clave_serie])
    propio = util.RAIZ / "prompts" / "series" / f"{clave_serie}.md"
    if propio.exists():  # instrucciones de la serie mejoradas, sin tocar config.json
        serie["prompt"] = propio.read_text(encoding="utf-8").strip()
    extra = (cfg.get("_prompts_extra") or {}).get(clave_serie) or []
    if extra:  # ajustes que salieron de las sugerencias de mejora
        serie["prompt"] += "\nAjustes según lo que viene funcionando:\n" + "\n".join(f"- {x}" for x in extra)
    return serie


# Estilo de los carteles si la IA no eligió uno: historias → revista, plata y noticias → oscuro.
ESTILO_POR_SERIE = {"historias": "revista", "inventos": "revista", "laplata": "revista", "argentino_que": "revista",
                    "paso_de_verdad": "revista", "mito": "revista", "libro": "revista", "autor": "revista"}


def estilo_visual(cfg, clave_serie, contenido):
    """Estilo de los carteles animados del video. Impuestos siempre en cuaderno; el resto lo elige la IA
    según el tema (revista, oscuro o cuaderno) y, si no eligió, va por serie."""
    if clave_serie in cfg.get("graficos_cuaderno", ["monotributo"]):
        return "cuaderno"
    elegido = (contenido or {}).get("estilo_visual")
    if elegido in ("revista", "oscuro", "cuaderno"):
        return elegido
    return {**ESTILO_POR_SERIE, **cfg.get("estilo_por_serie", {})}.get(clave_serie, "oscuro")


def _producir(cfg, clave_serie, serie, contenido, fuentes, fuentes_detalle, firma_base, fecha, turno, nombre_carpeta,
              evitar=(), version=1, nota_url=""):
    """Arma placas, video y portada en out/sitio/<nombre_carpeta> y devuelve la publicación."""
    from . import carrusel, montaje, portal
    carpeta = SITIO / nombre_carpeta
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    placas = carrusel.generar(contenido, serie["nombre"], cfg["usuario"], carpeta)
    estilo = estilo_visual(cfg, clave_serie, contenido)
    montaje.generar(contenido, serie["nombre"], cfg["usuario"], carpeta, evitar=evitar, estilo_graficos=estilo)
    shutil.rmtree(carpeta / "_trabajo", ignore_errors=True)
    (carpeta / "spec.json").unlink(missing_ok=True)
    meta_video = util.leer_json(str((carpeta / "meta.json").relative_to(util.RAIZ)), {}) or {}
    if meta_video.get("clips_ids"):
        montaje.anotar_clips(meta_video["clips_ids"])
    try:
        from . import faltantes
        faltantes.anotar({"fecha": fecha, "turno": turno, "serie": clave_serie, "titulo": contenido.get("titulo")},
                         meta_video, contenido)
    except Exception as ex:  # noqa
        util.log("No pude anotar lo que faltó:", util.ocultar(ex))
    (carpeta / "meta.json").unlink(missing_ok=True)
    (SITIO / "index.html").write_text("<meta charset='utf-8'><p>Fábrica de Shorts</p>", encoding="utf-8")
    firma = firma_base
    if meta_video.get("clips_stock"):
        firma = firma + f'\nVideos de stock: {meta_video.get("banco")}.'
    tags = " ".join(contenido["hashtags"])
    descripcion = contenido["descripcion"]
    desc_yt = descripcion
    if carrusel.es_contable(contenido, serie["nombre"]):
        # Videos contables: la línea del blog va siempre primero (por código, no depende de la IA)
        descripcion = desc_yt = portal.con_linea_blog(descripcion)
        if nota_url:  # en YouTube el link se puede tocar: va directo a la nota
            desc_yt = f'{portal.LINEA_BLOG}\nNota completa: {portal.enlace(nota_url, "youtube")}\n\n' + \
                      descripcion.replace(portal.LINEA_BLOG, "").strip()
    return {
        "fecha": fecha,
        "serie": clave_serie,
        "serie_nombre": serie["nombre"],
        "titulo": contenido["titulo"],
        "caption": f'{contenido["titulo"]}\n\n{descripcion}\n\n{firma}\n\n{tags}'.strip(),
        "descripcion_youtube": f'{desc_yt}\n\n{firma}\n\n{tags} #shorts'.strip(),
        "tags": [t.lstrip("#") for t in contenido["hashtags"]],
        "guion": " ".join(e["texto_voz"] for e in contenido["escenas"]),
        "fuentes": fuentes,
        "fuentes_detalle": fuentes_detalle,
        "archivos": {"video": f"{nombre_carpeta}/video.mp4", "portada": f"{nombre_carpeta}/thumb.jpg",
                     "placas": [f"{nombre_carpeta}/{x.name}" for x in placas],
                     **({"video_ig": f"{nombre_carpeta}/video_ig.mp4"} if (carpeta / "video_ig.mp4").exists() else {})},
        "contenido": contenido,
        "video": meta_video,
        "turno": turno,
        "carpeta": nombre_carpeta,
        "base": _carpeta(fecha, turno),
        "firma_base": firma_base,
        "version": version,
        "nota_portal": nota_url or "",
    }


def _anotar_sitio(anteriores, p):
    a = p["archivos"]
    util.guardar_json("data/sitio.json", anteriores + [
        {"fecha": p["fecha"], "carpeta": p["carpeta"], "archivos": [a["video"], a["portada"]] + a["placas"] + ([a["video_ig"]] if a.get("video_ig") else [])}])


def generar(simulado=False):
    cfg = util.config()
    os.environ.setdefault("TTS_VOICE", cfg.get("voz", "es-AR-TomasNeural"))
    os.environ.setdefault("TTS_RATE", str(cfg.get("voz_velocidad", "+15%")))
    os.environ.setdefault("TTS_MAX_PAUSA", str(cfg.get("voz_pausa_maxima", 0.28)))
    from . import escritor, investigar  # importa después de fijar la voz

    turno = _turno()
    if not simulado:
        _sumar_intento(turno)
    inicio = util.datetime.now(util.ZoneInfo("UTC")).isoformat()
    clave_serie = _serie_del_dia(cfg, turno)
    tema = None if simulado else _tema_pedido(turno)
    if not tema and not simulado and clave_serie == "capitulos":
        from . import capitulos
        tema = capitulos.tema_de_hoy(cfg)
    if tema:
        clave_serie = tema.get("serie") if tema.get("serie") in cfg["series"] else clave_serie
        serie = _serie_con_tema(_serie(cfg, clave_serie), tema)
    else:
        serie = _serie(cfg, clave_serie)
        from . import mejoras
        serie["prompt"] += mejoras.bloque_aprendizajes()
    fecha = util.ahora().strftime("%Y-%m-%d")
    util.log("Serie de hoy:", serie["nombre"], f"(turno {turno})")

    historial = util.leer_json("data/historial.json", [])
    usados = {f for h in historial for f in h.get("fuentes", [])}
    titulos = [h["titulo"] for h in reversed(historial)]

    fuentes = []
    clave_yt = util.secreto("YT_API_KEY")
    if tema:
        fuentes = [_fuente_tema(tema)]
        util.log("Tema pedido:", tema["titulo"], "(en lugar del tema del día)")
    elif serie.get("modo") == "contable" and not simulado:
        from . import contable, portal
        referentes = contable.buscar(cfg.get("referentes_contables", {}), clave_yt, usados,
                                     cfg.get("fuentes_por_video", 2))
        util.log("Referentes:", [f'{f["canal"]}: {f["titulo"][:90]} ({f.get("tipo")}, {f.get("score")})'
                                 for f in referentes] or "ninguno")
        nota, ref = None, None
        if cfg.get("portal_primero", True):  # una nota ya verificada del portal, si es atractiva
            datos_portal = portal.traer(cfg)
            minimo = float(cfg.get("portal_puntaje_minimo", 7))
            if minimo > 0:
                nota, ref = portal.elegir(datos_portal, usados, referentes, cfg.get("portal_dias", 7), minimo)
            else:
                nota = portal.nota_para_video(datos_portal, usados, cfg.get("portal_dias", 7))
        if nota:
            fuentes = [nota] + ([ref] if ref else [])
            util.log("Tema del portal:", nota["titulo"], nota["score"], nota["url"])
        else:
            fuentes = referentes
            util.log("Sin nota del portal que valga un video: sigo con los referentes")
    elif clave_yt and not simulado:
        try:
            if serie.get("modo") == "virales":
                lista = serie["busquedas"]
                semana = util.ahora().isocalendar()[1]
                rotadas = [lista[(semana * 2 + k) % len(lista)] for k in range(len(lista))]
                fuentes = investigar.virales_mundo(rotadas, clave_yt, usados, cfg.get("fuentes_por_video", 2))
            else:
                fuentes = investigar.fuera_de_serie(serie.get("canales", []), clave_yt, usados,
                                                    cfg.get("fuentes_por_video", 2))
            for f in fuentes:
                f["transcripcion"] = investigar.transcripcion(f["id"])
            util.log("Fuentes:", [f'{f["canal"]}: {f["titulo"]} (x{f["score"]})' for f in fuentes])
        except Exception as e:  # noqa
            util.log("La investigación falló, sigo sin fuentes:", e)
    else:
        util.log("Sin YT_API_KEY: la IA elige el tema dentro de la serie")

    guardado = None
    if tema and tema.get("capitulo"):  # capítulo de serie: se usa el guion revisado 2 días antes, tal cual
        from . import capitulos
        guardado = capitulos.contenido_guardado(tema["id"])
    if guardado:
        contenido = guardado
        util.log("Uso el guion revisado del capítulo:", tema["id"])
    elif simulado:
        contenido = escritor.validar(json.loads((util.RAIZ / "data" / "ejemplo_contenido.json").read_text(encoding="utf-8")))
    else:
        try:
            contenido = escritor.escribir(serie, fuentes, titulos)
        except Exception as e:  # noqa  (un error suelto de Gemini no tiene que tirar el video del día)
            util.avisar("Falló el guion, pruebo de nuevo", util.ocultar(f"{type(e).__name__}: {e}"))
            contenido = escritor.escribir(serie, fuentes, titulos)
    nota_repetido = ""
    if not simulado and not tema:  # los temas que pediste vos no se controlan
        from . import repetidos

        def _medir(entradas):
            return _rendimiento(cfg, clave_yt, entradas=entradas)

        def _reescribir(evitar):
            otra = dict(serie)
            otra["prompt"] = (serie["prompt"] + "\n\nIMPORTANTE: el tema que salió primero repite una idea ya publicada. "
                              "Elegí OTRA idea central, bien distinta de estas (ni variantes): "
                              + "; ".join(evitar[:10]) + ".")
            return escritor.escribir(otra, [], list(evitar) + titulos)

        nuevo, nota_repetido = repetidos.controlar(contenido, historial, _medir, _reescribir)
        if nuevo is not contenido:
            fuentes = []  # el tema nuevo no sale de las fuentes del día: quedan libres para otro video
            contenido = nuevo
    if tema and _carrusel_tema(tema):
        contenido["carrusel"] = _carrusel_tema(tema)
    if tema:
        contenido = _aplicar_cierre(contenido, tema)
    if tema and tema.get("capitulo"):
        from . import capitulos
        if not contenido.get("animacion"):
            contenido = capitulos.animar(contenido, tema)
        contenido = capitulos.con_destino(contenido, tema)

    nombre_carpeta = _carpeta(fecha, turno)
    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    SITIO.mkdir(parents=True)
    util.guardar_json("out/inicio.json", {"inicio": inicio})
    anteriores = [] if simulado else _traer_anteriores(nombre_carpeta)
    firma = cfg.get("firma", "")
    if serie.get("modo") == "virales" and fuentes:
        firma = ("Inspirado en videos virales de " +
                 ", ".join(f'{f["canal"]} ({f["pais"]})' for f in fuentes) + ".\n" + firma)
    detalle = [{"canal": f["canal"], "titulo": f["titulo"], "score": f.get("score") or f.get("pais", "")}
               for f in fuentes]
    nota_url = next((f["url"] for f in fuentes if f.get("portal")), "")
    publicacion = _producir(cfg, clave_serie, serie, contenido, [f["id"] for f in fuentes], detalle, firma,
                            fecha, turno, nombre_carpeta, nota_url=nota_url)
    if tema:
        publicacion["tema_id"] = tema["id"]
    if nota_repetido:
        publicacion["control_repetidos"] = nota_repetido
    util.guardar_json("out/publicacion.json", publicacion)
    if not simulado:
        _anotar_sitio(anteriores, publicacion)
    util.log("Listo:", contenido["titulo"])


def _guion_capitulo(cfg, tema, cambios=""):
    """Escribe (o corrige) el guion de un capítulo, lo anima y lo guarda en data/guiones/."""
    from . import capitulos, escritor
    serie = _serie_con_tema(_serie(cfg, "capitulos"), tema)
    previo = capitulos.contenido_guardado(tema["id"])
    if cambios and previo:
        contenido = escritor.aplicar_cambios(serie, previo, cambios)
    else:
        contenido = escritor.escribir(serie, [_fuente_tema(tema)], [])
    contenido = _aplicar_cierre(contenido, tema)
    contenido = capitulos.animar(dict(contenido, animacion=None), tema)
    capitulos.guardar_guion(tema, contenido, "corregido" if cambios else "para revisar")
    return contenido


def preparar_capitulo():
    """Lunes: arma el guion del capítulo del miércoles y te lo manda con asunto URGENTE para revisarlo con tiempo."""
    from . import capitulos
    cfg = util.config()
    tema = capitulos.tema_de_hoy(cfg)
    if not tema:
        util.log("No hay capítulos pendientes.")
        return
    contenido = capitulos.contenido_guardado(tema["id"])
    if contenido:
        util.log("El capítulo ya tiene guion guardado: te lo mando para revisar.")
    else:
        contenido = _guion_capitulo(cfg, tema)
    capitulos.mail_revision(tema, contenido)


def corregir_capitulo():
    """Aplica los cambios que escribiste (workflow «Corregir guion») al guion del próximo capítulo."""
    from . import capitulos
    cfg = util.config()
    cambios = (os.getenv("CAMBIOS") or "").strip()
    tema = capitulos.tema_de_hoy(cfg)
    if not tema or not cambios:
        util.log("No hay capítulo pendiente o no escribiste cambios.")
        return
    contenido = _guion_capitulo(cfg, tema, cambios)
    capitulos.mail_revision(tema, contenido, " (corregido)")


def rehacer():
    """Rehace el video con los cambios que pediste (el pedido lo dejó «esperar» en out/pedido.json)."""
    from . import escritor
    cfg = util.config()
    os.environ.setdefault("TTS_VOICE", cfg.get("voz", "es-AR-TomasNeural"))
    os.environ.setdefault("TTS_RATE", str(cfg.get("voz_velocidad", "+15%")))
    p = util.leer_json("out/publicacion.json")
    pedido = util.leer_json("out/pedido.json", {}) or {}
    cambios = (pedido.get("cambios") or "").strip()
    serie = _serie(cfg, p["serie"])
    tema = _tema_por_id(p.get("tema_id"))
    if tema:
        serie = _serie_con_tema(serie, tema)
    version = int(p.get("version", 1)) + 1
    util.log(f"Rehago el video (versión {version}) con tus cambios:", cambios)
    try:
        pedido_ia = cambios
        vivo = _datos_vivos(tema) if tema else ""
        if cambios and vivo:  # al rehacerlo, los números del mercado se actualizan a la hora del cambio
            pedido_ia += "\n\nAdemás, si el guion da números del mercado, actualizalos con estos:\n" + vivo
        contenido = escritor.aplicar_cambios(serie, p["contenido"], pedido_ia) if cambios else p["contenido"]
    except Exception as e:  # noqa
        util.avisar("No pude aplicar los cambios al guion", f"Sigo con el guion anterior. Motivo: {util.ocultar(e)}")
        contenido = p["contenido"]
    if tema and _carrusel_tema(tema) and "carrusel" not in cambios.lower() and "placa" not in cambios.lower():
        contenido = dict(contenido, carrusel=_carrusel_tema(tema))  # las placas fijas no se tocan
    if tema and not any(x in cambios.lower() for x in ("cierre", "final", "pregunta", "termin")):
        contenido = _aplicar_cierre(contenido, tema)  # el cierre fijo se mantiene salvo que pidas cambiarlo
    if tema and tema.get("capitulo"):
        from . import capitulos
        contenido = capitulos.animar(contenido, tema)
    otros_clips = any(x in cambios.lower() for x in ("clip", "imagen", "imágen", "fondo", "toma", "visual", "video de fondo"))
    evitar = set((p.get("video") or {}).get("clips_ids") or []) if otros_clips else set()
    nombre = f'{p.get("base") or p["carpeta"]}-v{version}'
    try:
        nueva = _producir(cfg, p["serie"], serie, contenido, p.get("fuentes", []), p.get("fuentes_detalle", []),
                          p.get("firma_base", cfg.get("firma", "")), p["fecha"], p.get("turno", 1), nombre,
                          evitar=evitar, version=version, nota_url=p.get("nota_portal", ""))
    except Exception as e:  # noqa
        # si algo falla, no se pierde el día: sale la versión anterior
        util.avisar("No pude rehacer el video", f"Sale la versión anterior. Motivo: {util.ocultar(e)}")
        return
    if p.get("tema_id"):
        nueva["tema_id"] = p["tema_id"]
    nueva["cambios_pedidos"] = (p.get("cambios_pedidos") or []) + [cambios]
    nueva["pedido_creado"] = pedido.get("creado", "")
    util.guardar_json("out/publicacion.json", nueva)
    anteriores = [x for x in (util.leer_json("data/sitio.json", []) or []) if x.get("carpeta") != nombre]
    _anotar_sitio(anteriores, nueva)
    util.log("Versión nueva lista:", nueva["titulo"])


def publicar(base_url):
    from . import publicar as pub
    cfg = util.config()
    p = util.leer_json("out/publicacion.json")
    base = base_url.rstrip("/") + "/"
    decision = (util.leer_json("out/decision.json", {}) or {}).get("decision", "publicar")
    if decision == "cancelar":
        historial = util.leer_json("data/historial.json", []) or []
        historial.append({"fecha": p["fecha"], "turno": p.get("turno", 1), "hora": util.ahora().strftime("%H:%M"),
                          "serie": p["serie"], "titulo": p["titulo"], "fuentes": p["fuentes"], "resultados": {},
                          "cancelado": True})
        util.guardar_json("data/historial.json", historial[-400:])
        util.avisar("No se publicó", "Pediste que este video no salga hoy.")
        try:
            pub.mail(f'No se publicó (lo pediste): {p["titulo"]}',
                     f'<p>Como pediste, <b>{html.escape(p["titulo"])}</b> no se publicó. Si lo querés subir a mano, '
                     f'acá está el <a href="{base}{p["archivos"]["video"]}">video</a> (el link dura {_dias_pagina()} días).</p>')
        except Exception as ex:  # noqa
            util.log("No pude mandar el mail:", ex)
        return
    url = lambda rel: base + rel  # noqa
    video_local = SITIO / p["archivos"]["video"]
    hoy_carrusel = util.ahora().isoweekday() in cfg.get("carrusel_dias", []) and p.get("turno", 1) == 1
    if p.get("serie") in _series_con_carrusel(cfg) and p["archivos"].get("placas"):
        hoy_carrusel = True  # el contenido contable va siempre también como carrusel (queda para el perfil del estudio)
    tema = _tema_por_id(p.get("tema_id"))
    if tema and tema.get("carrusel_ig") and p["archivos"].get("placas"):
        hoy_carrusel = True  # los temas que pediste van también como carrusel
    quiere = cfg.get("publicar", {})
    resultados = {}

    def intentar(nombre, fn):
        try:
            resultados[nombre] = {"ok": True, "id": fn()}
        except Exception as e:  # noqa
            resultados[nombre] = {"ok": False, "error": str(e)[:300]}
        util.log(nombre, resultados[nombre])

    if quiere.get("instagram_reel"):
        intentar("instagram_reel", lambda: pub.instagram_reel(url(p["archivos"].get("video_ig") or p["archivos"]["video"]),
                                                              url(p["archivos"]["portada"]), p["caption"]))
    if quiere.get("instagram_carrusel") and hoy_carrusel:
        intentar("instagram_carrusel", lambda: pub.instagram_carrusel([url(x) for x in p["archivos"]["placas"]],
                                                                      p["caption"]))
    if quiere.get("youtube"):
        intentar("youtube", lambda: pub.youtube(video_local, p["titulo"], p["descripcion_youtube"], p["tags"],
                                                cfg.get("youtube_privacidad", "public")))
    if quiere.get("tiktok"):
        intentar("tiktok", lambda: pub.tiktok(video_local, p["caption"], cfg.get("tiktok_privacidad", "SELF_ONLY")))
    if quiere.get("facebook"):
        intentar("facebook", lambda: pub.facebook_reel(video_local, p["caption"], p["titulo"]))

    historial = util.leer_json("data/historial.json", [])
    historial.append({"fecha": p["fecha"], "turno": p.get("turno", 1), "hora": util.ahora().strftime("%H:%M"),
                      "serie": p["serie"], "titulo": p["titulo"], "fuentes": p["fuentes"], "resultados": resultados,
                      "guion": p.get("guion", "")[:400], "tema_id": p.get("tema_id", "")})
    util.guardar_json("data/historial.json", historial[-400:])
    _marcar_tema(p, resultados)
    _registro(p, resultados, base)
    _mail_diario(p, resultados, base)
    resumen(base_url, resultados)

    if resultados and not any(r["ok"] for r in resultados.values()):
        util.log("No se pudo publicar en ninguna red")
        sys.exit(1)


def resumen(base_url, res=None):
    """Escribe el resumen visible en la pestaña Actions de GitHub (con las placas a la vista)."""
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    p = util.leer_json("out/publicacion.json")
    if not (destino and p):
        return
    base = base_url.rstrip("/") + "/"
    md = [f'## {p["serie_nombre"]}: {p["titulo"]}', ""]
    for red, r in (res or {}).items():
        md.append(f'- **{red}**: ' + ("✅ publicado" if r["ok"] else "❌ " + r["error"]))
    v = p.get("video") or {}
    if v:
        md += [f'Voz: {v.get("voz", "?")} · {v.get("duracion", "?")} s · fondos: {v.get("clips_stock", 0)} de '
               f'{v.get("clips", 0)} clips de {v.get("banco") or "stock"}, {v.get("clips_propios", 0)} propios, '
               f'{v.get("postales", 0)} postales de Argentina · música: {v.get("musica") or "no"}', ""]
    md += ["", f'[▶️ Ver el video]({base}{p["archivos"]["video"]}) · [Portada]({base}{p["archivos"]["portada"]})', ""]
    md += [" ".join(f'<img src="{base}{x}" width="180">' for x in p["archivos"]["placas"]), ""]
    md += ["**Texto para publicar:**", "", "```", p["caption"], "```", "", "**Guion:** " + p["guion"]]
    with open(destino, "a", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")


def _registro(p, res, base):
    lineas = [f'# {p["fecha"]} · {p["serie_nombre"]}', "", f'**{p["titulo"]}**', ""]
    for red, r in res.items():
        lineas.append(f'- {red}: ' + ("publicado (" + str(r["id"]) + ")" if r["ok"] else "ERROR: " + r["error"]))
    a = p.get("archivos") or {}
    if base and a.get("video"):
        links = [f'[Video]({base}{a["video"]})']
        if a.get("portada"):
            links.append(f'[Portada]({base}{a["portada"]})')
        if a.get("placas"):
            links.append(f'[Carrusel]({base}{a["placas"][0]})')
        lineas += ["", " · ".join(links) + f" (para bajarlos: duran {_dias_pagina()} días)"]
    yt = res.get("youtube") or {}
    if yt.get("ok") and yt.get("id"):
        lineas += ["", f'Ver en YouTube: https://youtube.com/shorts/{yt["id"]}']
    lineas += ["", "Basado en: " + ("; ".join(f'{f["canal"]} - {f["titulo"]} (x{f["score"]})'
                                              for f in p["fuentes_detalle"]) or "tema propio"),
               "", "## Texto", "", p["caption"], "", "## Guion", "", p["guion"]]
    ruta = util.RAIZ / "publicaciones" / f'{p.get("base") or p.get("carpeta") or p["fecha"]}.md'
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def _faltas_mail(p):
    try:
        from . import faltantes
        return faltantes.bloque_mail(p)
    except Exception as ex:  # noqa
        util.log("No pude resumir lo que faltó:", util.ocultar(ex))
        return ""


def _mail_diario(p, res, base):
    from . import publicar as pub
    e = html.escape
    filas = "".join(
        f'<li><b>{e(red)}</b>: {"✅ publicado" if r["ok"] else "❌ " + e(r["error"])}</li>' for red, r in res.items())
    estado = util.leer_json("data/estado.json", {})
    aviso = f'<p style="color:#b00">⚠️ {e(estado["ig_aviso"])}</p>' if estado.get("ig_aviso") else ""
    if res.get("instagram_reel") and not res["instagram_reel"]["ok"]:
        aviso += ('<p style="color:#b00">⚠️ <b>No salió en Instagram.</b> Bajá el video del link de abajo y subilo '
                  'a mano como Reel, con la portada y el texto de este mail.</p>')
    cuerpo = (f'<h2>{e(p["serie_nombre"])}: {e(p["titulo"])}</h2><ul>{filas}</ul>{aviso}'
              f'<p><a href="{base}{p["archivos"]["video"]}">Video</a> · '
              f'<a href="{base}{p["archivos"]["portada"]}">Portada</a> · '
              + (f'<a href="{base}{p["archivos"]["placas"][0]}">Carrusel</a>' if p["archivos"].get("placas") else "")
              + f' (los links duran {_dias_pagina()} días)</p>'
              f'<p><b>Texto:</b><br>{e(p["caption"]).replace(chr(10), "<br>")}</p>'
              f'<p><b>Para TikTok:</b> bajá el video y, antes de publicar, tocá <b>Más opciones</b> y activá '
              f'<b>«Contenido generado por IA»</b> (la voz es de IA).</p>'
              + (f'<p><b>Temas repetidos:</b> {e(p["control_repetidos"])}</p>' if p.get("control_repetidos") else "")
              + _faltas_mail(p) +
              f'<hr><p style="color:#666">{e(p["guion"])}</p>')
    try:
        segundo = " (2º del día)" if p.get("turno", 1) == 2 else ""
        pub.mail(f'Short del día{segundo}: {p["titulo"]}', cuerpo)
    except Exception as ex:  # noqa
        util.log("No pude mandar el mail:", ex)


def _rendimiento(cfg, clave_yt, dias=30, entradas=None):
    """Cómo le fue a cada serie nuestra (YouTube + Instagram + Facebook + lo que cargaste de TikTok).
    Por defecto, los últimos `dias`; o las publicaciones que le pases en `entradas`."""
    from . import investigar
    from . import publicar as pub
    hist = con_reintentos(util.leer_json("data/historial.json", []) or [])
    desde = (util.ahora() - util.timedelta(days=dias)).strftime("%Y-%m-%d")
    recientes = con_reintentos(list(entradas)) if entradas is not None else None
    recientes = recientes if entradas is not None else [h for h in hist if h.get("fecha", "") >= desde]
    yt_ids = [h["resultados"]["youtube"]["id"] for h in recientes
              if h.get("resultados", {}).get("youtube", {}).get("ok")]
    yt = investigar.estadisticas_youtube(yt_ids, clave_yt) if (clave_yt and yt_ids) else {}
    tiktok = util.leer_json("data/tiktok_vistas.json", {}) or {}
    filas = []
    for h in recientes:
        res = h.get("resultados", {})
        fila = {"fecha": h["fecha"], "hora": h.get("hora", ""), "turno": h.get("turno", 1), "serie": h["serie"],
                "titulo": h["titulo"], "vistas": 0, "guardados": 0, "compartidos": 0, "comentarios": 0, "likes": 0}
        if res.get("facebook", {}).get("ok"):
            fila["vistas"] += pub.facebook_metricas(res["facebook"]["id"]).get("vistas", 0)
        fila["vistas"] += tiktok.get(f'{h["fecha"]}#{h.get("turno", 1)}', 0)
        if res.get("youtube", {}).get("ok"):
            m = yt.get(res["youtube"]["id"], {})
            fila["vistas"] += m.get("vistas", 0)
            fila["likes"] += m.get("likes", 0)
            fila["comentarios"] += m.get("comentarios", 0)
        for red in ("instagram_reel", "instagram_carrusel"):
            if res.get(red, {}).get("ok"):
                m = pub.instagram_metricas(res[red]["id"])
                fila["vistas"] += m.get("views", m.get("reach", 0))
                fila["guardados"] += m.get("saved", 0)
                fila["compartidos"] += m.get("shares", 0)
                fila["comentarios"] += m.get("comments", 0)
                fila["likes"] += m.get("likes", 0)
        filas.append(fila)
    por_serie = {}
    for f in filas:
        nombre = cfg["series"].get(f["serie"], {}).get("nombre", f["serie"])
        a = por_serie.setdefault(nombre, {"posts": 0, "vistas": 0, "guardados": 0, "compartidos": 0,
                                          "comentarios": 0})
        a["posts"] += 1
        for k in ("vistas", "guardados", "compartidos", "comentarios"):
            a[k] += f[k]
    return filas, por_serie


# ---------------------------------------------------------------- horarios
# GitHub no respeta el reloj: en la práctica dispara cada 2 o 3 horas y con atraso. Por eso la fábrica
# arranca con el primer aviso que llega dentro de las 5 horas previas al horario, arma el video y
# espera hasta el minuto exacto para publicar.
ANTICIPO_MAX = 300  # minutos antes del horario en que ya puede arrancar (el trabajo de GitHub dura hasta 6 h)
TARDE_MAX = 180     # si el aviso llega tarde, publica igual hasta 3 horas después del horario
INTENTOS_MAX = 2    # si falla, lo reintenta una vez más ese día (no más, para no llenarte de avisos)


def _clave_intento(fecha, turno):
    return fecha if turno == 1 else f"{fecha}#{turno}"


def _intentos(fecha, turno=1):
    return int((util.leer_json("data/estado.json", {}).get("intentos") or {}).get(_clave_intento(fecha, turno), 0))


def _sumar_intento(turno=1):
    """Anota que el reloj arrancó a fabricar este turno hoy (se guarda aunque la corrida falle)."""
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return
    estado = util.leer_json("data/estado.json", {})
    hoy = util.ahora().strftime("%Y-%m-%d")
    intentos = {k: v for k, v in (estado.get("intentos") or {}).items() if k[:10] >= hoy}  # solo los de hoy
    clave = _clave_intento(hoy, turno)
    intentos[clave] = intentos.get(clave, 0) + 1
    estado["intentos"] = intentos
    util.guardar_json("data/estado.json", estado)


def _objetivo(cfg, momento=None, turno=1):
    momento = momento or util.ahora()
    h = _horarios(cfg, turno).get(str(momento.isoweekday()))
    if not h:
        return None
    hh, mm = (int(x) for x in str(h).split(":")[:2])
    return momento.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _ya_salio(hoy, turno):
    return any(h.get("fecha") == hoy and int(h.get("turno", 1) or 1) == turno
               for h in util.leer_json("data/historial.json", []) or [])


def _toca_turno(cfg, ahora, turno):
    """(sí/no, motivo, horario objetivo) para un turno a esta hora."""
    objetivo = _objetivo(cfg, ahora, turno)
    hoy = ahora.strftime("%Y-%m-%d")
    if objetivo is None:
        return False, "hoy no tiene horario", None
    if _ya_salio(hoy, turno):
        return False, "hoy ya se publicó", objetivo
    from . import revision
    if revision.cancelado(hoy, turno):
        return False, "pediste que hoy no salga", objetivo
    if _intentos(hoy, turno) >= INTENTOS_MAX:
        return False, f"hoy ya se intentó {INTENTOS_MAX} veces y falló; mañana sigue normal", objetivo
    faltan = (objetivo - ahora).total_seconds() / 60
    if 0 < faltan <= ANTICIPO_MAX:
        return True, (f"faltan {faltan:.0f} minutos para las {objetivo:%H:%M}: lo armo ahora y espero "
                      f"hasta esa hora para publicar"), objetivo
    if -TARDE_MAX <= faltan <= 0:
        return True, (f"ya pasaron {-faltan:.0f} minutos de las {objetivo:%H:%M} y no salió "
                      f"(el aviso de GitHub llegó tarde o falló): publico apenas esté listo"), objetivo
    return False, f"faltan {faltan:.0f} minutos para las {objetivo:%H:%M}", objetivo


def toca():
    """Lo usa el reloj de GitHub: ¿hay que fabricar y publicar ahora? ¿Qué turno?
    Si tocan los dos, va primero el de horario más temprano (el otro arranca con el aviso siguiente)."""
    cfg = util.config()
    try:
        turno = 2 if int(os.getenv("TURNO_MANUAL") or 1) == 2 else 1
    except ValueError:
        turno = 1
    si, motivos = True, ["ejecución manual"]
    if os.getenv("GITHUB_EVENT_NAME") == "schedule":
        ahora = util.ahora()
        si, motivos, candidatos = False, [], []
        for t in _turnos(cfg):
            ok, motivo, objetivo = _toca_turno(cfg, ahora, t)
            motivos.append(f"turno {t}: {motivo}")
            if ok:
                candidatos.append((objetivo, t))
        if candidatos:
            si, turno = True, min(candidatos)[1]
            motivos.append(f"→ arranca el turno {turno}")
    util.log("¿Toca publicar?", "sí" if si else "no", "·", " | ".join(motivos))
    salida = os.getenv("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"si={'true' if si else 'false'}\nturno={turno}\n")


def esperar(ultima=False):
    """Espera la hora de publicar mirando cada minuto si mandaste un pedido desde «Revisar video».
    Deja la decisión en out/decision.json y en la salida del paso: publicar, cancelar o cambios."""
    import time
    from . import revision
    cfg = util.config()
    turno = _turno()
    p = util.leer_json("out/publicacion.json", {}) or {}
    desde = max((util.leer_json("out/inicio.json", {}) or {}).get("inicio", ""), p.get("pedido_creado", ""))
    objetivo = _objetivo(cfg, turno=turno)
    decision, pedido = "publicar", {}
    if objetivo and (objetivo - util.ahora()).total_seconds() > 0:
        util.log(f"Video listo. Espero hasta las {objetivo:%H:%M} y mientras miro si pedís cambios.")
        util.avisar("Esperando la hora de publicar",
                    f"El video ya está listo y se mandó por mail para que lo revises. Esta corrida queda en marcha "
                    f"(amarilla) hasta las {objetivo:%H:%M} y ahí publica. Es normal.")
    while True:
        for x in revision.nuevos(revision.leer_remotos(), p.get("fecha", ""), turno, desde):
            desde = x.get("creado", desde)
            if x.get("accion") == "cambios" and ultima:
                util.avisar("Ya no se aceptan más cambios", "Este video ya se rehízo dos veces: sale esta versión.")
                continue
            decision, pedido = x.get("accion", "publicar"), x
            break
        if pedido:
            break
        if not objetivo or (objetivo - util.ahora()).total_seconds() <= 0:
            break
        time.sleep(min(60, max(1, (objetivo - util.ahora()).total_seconds())))
    util.log("Decisión:", decision, pedido.get("cambios", ""))
    util.guardar_json("out/decision.json", {"decision": decision, "pedido": pedido})
    util.guardar_json("out/pedido.json", pedido)
    salida = os.getenv("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"decision={decision}\n")


def online(base_url):
    """Espera a que el video nuevo se pueda ver en la página (Instagram lo baja de ahí)."""
    import time
    p = util.leer_json("out/publicacion.json")
    url = base_url.rstrip("/") + "/" + p["archivos"]["video"]
    for _ in range(36):
        try:
            r = util.pedir("HEAD", url, intentos=1, timeout=30)
            if r is not None and r.status_code == 200:
                util.log("Online:", url)
                return
        except Exception:  # noqa
            pass
        time.sleep(10)
    raise RuntimeError("Los archivos no aparecieron online: " + url)


def listo(base_url):
    """Te manda el video apenas está listo, con la hora a la que sale y cómo pedir cambios."""
    from . import publicar as pub
    from . import revision
    e = html.escape
    cfg = util.config()
    p = util.leer_json("out/publicacion.json")
    base = base_url.rstrip("/") + "/"
    objetivo = _objetivo(cfg, turno=_turno())
    cuando = (f"hoy a las {objetivo:%H:%M}" if objetivo and objetivo > util.ahora()
              else "en unos minutos (ya es la hora)")
    v = p.get("version", 1)
    version = f" · versión {v} con tus cambios" if v > 1 else ""
    link = revision.link_formulario()
    tema = _tema_por_id(p.get("tema_id"))
    pedido = (f'<p>📌 Es el tema que pediste: <b>{e(tema["titulo"])}</b>. Revisá bien los datos: si algo no '
              f'cierra, pedí el cambio.</p>') if tema else ""
    placas = p["archivos"].get("placas") or []
    if placas and ((tema and tema.get("carrusel_ig")) or p.get("serie") in _series_con_carrusel(cfg)):
        pedido += ('<p><b>En Instagram sale también como carrusel:</b> '
                   + " · ".join(f'<a href="{base}{x}">{i}</a>' for i, x in enumerate(placas, 1)) + '</p>')
    cuerpo = (f'<h2>{e(p["serie_nombre"])}: {e(p["titulo"])}</h2>{pedido}'
              f'<p><b>Sale {cuando}</b> en Instagram, YouTube y Facebook{version}. '
              f'Si no hacés nada, se publica solo.</p>'
              f'<p><a href="{base}{p["archivos"]["video"]}">▶️ Ver el video</a> · '
              f'<a href="{base}{p["archivos"]["portada"]}">Portada</a></p>'
              f'<p><b>¿Querés cambiar algo?</b> Entrá a <a href="{link}">Revisar video</a> → <b>Run workflow</b>, '
              f'elegí qué hacer (pedir cambios, publicar ya o no publicar hoy), escribí qué cambiar y tocá '
              f'<b>Run workflow</b>. En unos 10 minutos te llega la versión nueva.</p>'
              f'<p><b>Texto:</b><br>{e(p["caption"]).replace(chr(10), "<br>")}</p>'
              f'<hr><p style="color:#666"><b>Guion:</b> {e(p["guion"])}</p>'
              f'<p style="color:#666">Al subirlo a TikTok, activá «Contenido generado por IA» en Más opciones.</p>')
    try:
        segundo = " (2º del día)" if p.get("turno", 1) == 2 else ""
        pub.mail(f'Listo para revisar{segundo}: {p["titulo"]}', cuerpo)
    except Exception as ex:  # noqa
        util.log("No pude mandar el mail:", ex)


def revisar():
    """Lo usa el formulario «Revisar video»: anota tu pedido para la corrida que está esperando."""
    from . import revision
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    try:
        x = revision.registrar(os.getenv("ACCION", ""), os.getenv("TURNO_PEDIDO", ""), os.getenv("CAMBIOS", ""))
        texto = {"cambios": "Listo: la fábrica rehace el video con tus cambios y te manda la versión nueva por mail "
                            "en unos 10 minutos. Si para entonces ya pasó la hora, se publica apenas esté.",
                 "publicar": "Listo: se publica en el próximo minuto.",
                 "cancelar": "Listo: hoy no se publica. Te llega un mail con el link por si lo querés subir a mano."}
        msg = texto[x["accion"]]
    except ValueError as e:
        msg = f"❌ {e}"
        if destino:
            open(destino, "a", encoding="utf-8").write(f"## Revisar video\n\n{msg}\n")
        util.log(msg)
        sys.exit(1)
    util.log(msg)
    if destino:
        open(destino, "a", encoding="utf-8").write(f"## Revisar video\n\n{msg}\n")


def _franjas(propias):
    horas = {}
    for f in propias:
        if f.get("hora"):
            x = horas.setdefault(f["hora"][:2] + " h", {"posts": 0, "vistas": 0})
            x["posts"] += 1
            x["vistas"] += f["vistas"]
    return horas


def _para_mejoras(cfg, por_serie_max=None, edad_min=None):
    """Lo que se usa para sugerir cambios: los últimos 10 videos de cada serie que tengan 2 días o más
    (así ya juntaron vistas), y los de los últimos 120 días para ver si los cambios funcionaron."""
    n = int(por_serie_max or cfg.get("mejoras_videos_por_serie", 10))
    edad = int(edad_min if edad_min is not None else cfg.get("mejoras_dias_minimos", 2))
    hasta = (util.ahora() - util.timedelta(days=edad)).strftime("%Y-%m-%d")
    desde = (util.ahora() - util.timedelta(days=120)).strftime("%Y-%m-%d")
    hist = [h for h in con_reintentos(util.leer_json("data/historial.json", []) or [])
            if desde <= h.get("fecha", "") <= hasta and not h.get("cancelado")
            and any((r or {}).get("ok") for r in (h.get("resultados") or {}).values())]
    elegidas, cuenta = [], {}
    for h in sorted(hist, key=lambda x: (x["fecha"], x.get("hora", "")), reverse=True):
        if cuenta.get(h["serie"], 0) < n:
            cuenta[h["serie"]] = cuenta.get(h["serie"], 0) + 1
            elegidas.append(h)
    return _rendimiento(cfg, util.secreto("YT_API_KEY"), entradas=list(reversed(elegidas)))


def _proponer_hoy(analisis=None, cfg=None, rendimiento=None):
    """Arma sugerencias de mejora con los números de hoy (las usa el reporte y la corrida diaria de mejoras)."""
    from . import mejoras
    cfg = cfg or util.config()
    propias, por_serie = _para_mejoras(cfg)
    analisis = mejoras.guardar_aprendizajes(propias, analisis)
    return mejoras.proponer(cfg, por_serie, propias, _franjas(propias), analisis)


def cargar_tiktok():
    """Formulario «Cargar vistas de TikTok»."""
    from . import mejoras
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    try:
        n = mejoras.cargar_tiktok(os.getenv("VISTAS", ""))
        msg = f"Listo: cargué las vistas de TikTok de {n} videos."
    except ValueError as e:
        msg = f"❌ {e}"
    util.log(msg)
    if destino:
        open(destino, "a", encoding="utf-8").write(f"## Vistas de TikTok\n\n{msg}\n")
    if msg.startswith("❌"):
        sys.exit(1)


def sugerencia():
    """Tu respuesta a una sugerencia de mejora (formulario «Responder sugerencia»)."""
    from . import mejoras
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    try:
        p = mejoras.responder(os.getenv("RESPUESTA", ""), os.getenv("CAMBIOS", ""), os.getenv("NUMERO", ""))
        msg = f'Listo: #{p["id"]} {p["titulo"]} quedó {p["estado"]}.'
    except ValueError as e:
        msg = f"❌ {e}"
        util.log(msg)
        if destino:
            open(destino, "a", encoding="utf-8").write(f"## Responder sugerencia\n\n{msg}\n")
        sys.exit(1)
    util.log(msg)
    if destino:
        open(destino, "a", encoding="utf-8").write(f"## Responder sugerencia\n\n{msg}\n")


def reporte():
    from . import escritor, investigar
    from . import publicar as pub
    cfg = util.config()
    clave = util.secreto("YT_API_KEY")
    if not clave:
        util.log("Sin YT_API_KEY no hay reporte")
        return
    cache = util.leer_json("data/canales.json", {})
    vistos, filas = set(), []
    ref = cfg.get("referentes_contables", {})
    for s in list(cfg["series"].values()) + [{"canales": ref.get("youtube", [])}]:
        for b in s.get("canales", []):
            if b.lower() in vistos:
                continue
            vistos.add(b.lower())
            m = investigar.metricas_canal(b, clave, cache)
            if m:
                filas.append(m)
    util.guardar_json("data/canales.json", cache)
    propias, por_serie = _rendimiento(cfg, clave)
    nuestro = "\n".join(
        f'- {serie}: {a["posts"]} publicaciones, {a["vistas"] // max(a["posts"], 1)} vistas promedio, '
        f'{a["guardados"]} guardados, {a["compartidos"]} compartidos, {a["comentarios"]} comentarios'
        for serie, a in sorted(por_serie.items(), key=lambda x: -x[1]["vistas"] / max(x[1]["posts"], 1)))
    mejores = sorted(propias, key=lambda f: -f["vistas"])[:3]
    peores = sorted(propias, key=lambda f: f["vistas"])[:3]
    resumen = "\n\n".join(
        f'CANAL {f["canal"]} | {f["videos_por_semana"]} videos/semana | vistas típicas {f["mediana"]} | '
        f'{f["pct_shorts"]}% Shorts\n' + "\n".join(
            f'  - "{t["titulo"]}" ({t["vistas"]} vistas, {t["veces"]} veces lo normal)' for t in f["top"])
        for f in filas)
    try:
        from . import contable
        ig = contable.resumen_instagram(ref.get("instagram", []))
        if ig:
            resumen += "\n\n" + ig
    except Exception as ex:  # noqa
        util.log("No pude leer el Instagram de los referentes:", util.ocultar(ex))
    sistema = ("Sos analista de contenido de una cuenta argentina sin cara de Shorts, Reels y TikTok sobre plata, "
               "economía, libros de dinero e impuestos. Respondé en español rioplatense natural.")
    pedido = ("Con estas métricas de canales de referencia, devolvé un JSON con: "
              '{"patrones": ["..."], "formatos_que_rinden": ["..."], "estructuras_virales": ["..."], '
              '"ideas": [{"serie": "...", "titulo": "...", "miniatura": "..."}]} '
              "con 5 patrones, 5 formatos, 5 estructuras y 10 ideas originales adaptadas a Argentina para nuestras "
              "series (" + ", ".join(s["nombre"] for s in cfg["series"].values()) + "). "
              'Además sumá "series_reforzar": ["..."] y "series_cambiar": [{"serie": "...", "por_que": "...", '
              '"propuesta": "..."}] mirando NUESTRO RENDIMIENTO (si todavía hay pocos datos, decilo).\n\n'
              "NUESTRO RENDIMIENTO (últimos 30 días, por serie):\n" + (nuestro or "(todavía sin datos)") +
              "\n\nCOMPETENCIA:\n" + resumen)
    from . import faltantes
    faltas_txt = faltantes.para_ia(7)
    if faltas_txt:
        pedido += ("\n\nLO QUE LE FALTÓ A NUESTROS VIDEOS ESTA SEMANA (escenas donde lo que se veía no pegaba del todo "
                   "con lo que se decía):\n" + faltas_txt + "\n\nCon eso, sumá al JSON \"pedidos_material\": hasta 6 "
                   "pedidos concretos y fáciles de conseguir, ordenados por cuánto mejorarían los próximos videos: "
                   '[{"que": "clip" o "foto" o "dibujito", "pedido": "qué conseguir, dicho simple (ej. Grabá 5 '
                   'segundos de un posnet cobrando, en vertical)", "nombre_archivo": "posnet-cobro.mp4" (solo para '
                   'clip o foto), "por_que": "para qué videos sirve"}]. Agrupá lo que se repite; nada con caras de '
                   'personas.')
    try:
        a = escritor.gemini(sistema, pedido, temperatura=0.7)
    except Exception as ex:  # noqa
        a = {"patrones": [f"No se pudo analizar: {ex}"]}
    fecha = util.ahora().strftime("%Y-%m-%d")
    md = [f"# Reporte de competencia · {fecha}", "", "| Canal | Videos/semana | Vistas típicas | % Shorts |",
          "|---|---|---|---|"]
    md += [f'| {f["canal"]} | {f["videos_por_semana"]} | {f["mediana"]:,} | {f["pct_shorts"]}% |' for f in filas]
    for titulo, clave_a in [("Patrones", "patrones"), ("Formatos que rinden", "formatos_que_rinden"),
                            ("Estructuras virales", "estructuras_virales")]:
        md += ["", f"## {titulo}", ""] + [f"- {x}" for x in a.get(clave_a, [])]
    md += ["", "## Cómo nos fue (últimos 30 días)", ""]
    try:  # lo usan las competencias de la grilla ("a|b" y "mejor:a|b")
        por_nombre = {v.get("nombre", k): k for k, v in cfg["series"].items()}
        util.guardar_json(RENDIMIENTO, {"fecha": fecha, "series": {por_nombre.get(k, k): a for k, a in por_serie.items()}})
    except Exception as ex:  # noqa
        util.log("No pude guardar el rendimiento por serie:", ex)
    if por_serie:
        md += ["| Serie | Publicaciones | Vistas promedio | Guardados | Compartidos | Comentarios |",
               "|---|---|---|---|---|---|"]
        md += [f'| {k} | {a["posts"]} | {a["vistas"] // max(a["posts"], 1):,} | {a["guardados"]} | '
               f'{a["compartidos"]} | {a["comentarios"]} |'
               for k, a in sorted(por_serie.items(), key=lambda x: -x[1]["vistas"] / max(x[1]["posts"], 1))]
        md += ["", "Lo que mejor anduvo: " + "; ".join(f'{f["titulo"]} ({f["vistas"]:,})' for f in mejores),
               "", "Lo que peor anduvo: " + "; ".join(f'{f["titulo"]} ({f["vistas"]:,})' for f in peores)]
    else:
        md += ["Todavía no hay publicaciones para medir."]
    horas = _franjas(propias)
    if horas:
        md += ["", "## Por horario de publicación", "", "| Franja | Publicaciones | Vistas promedio |", "|---|---|---|"]
        md += [f'| {k} | {v["posts"]} | {v["vistas"] // max(v["posts"], 1):,} |' for k, v in
               sorted(horas.items(), key=lambda x: -x[1]["vistas"] / max(x[1]["posts"], 1))]
    md += ["", "## Qué reforzar y qué cambiar", ""]
    md += [f"- Reforzar: {x}" for x in a.get("series_reforzar", [])]
    md += [f'- Cambiar **{x.get("serie", "")}**: {x.get("por_que", "")} → {x.get("propuesta", "")}'
           for x in a.get("series_cambiar", []) if isinstance(x, dict)]
    try:
        nuevas = _proponer_hoy(a, cfg, (propias, por_serie))
    except Exception as ex:  # noqa
        util.log("No pude armar las sugerencias:", util.ocultar(ex))
        nuevas = []
    if nuevas:
        from . import mejoras
        md += ["", "## Sugerencias de cambio (te llega una por día por mail; si no respondés, se aplica sola)", ""]
        md += [f'- #{p["id"]} {p["titulo"]}: {mejoras.describir(cfg, p)}' for p in nuevas]
    md += ["", "## Lo que le falta a la fábrica (cómo ayudarla)", ""]
    pedidos = [x for x in a.get("pedidos_material", []) if isinstance(x, dict) and x.get("pedido")]
    if pedidos:
        for x in pedidos:
            arch = f' → subilo como `assets/clips/{x["nombre_archivo"]}`' if x.get("nombre_archivo") and x.get("que") != "dibujito" else ""
            md.append(f'- **{str(x.get("que", "")).capitalize()}**: {x["pedido"]}{arch}'
                      + (f' ({x["por_que"]})' if x.get("por_que") else ""))
    else:
        md += [f"- {x}" for x in faltantes.resumen_simple(7)] or ["- Esta semana no faltó nada importante."]
    if pedidos or faltantes.ultimos(7):
        md += ["", "Clips y fotos: con el celu en vertical, 5-10 segundos, sin caras. Se suben en el repo dentro de "
               "`assets/clips/` (Add file → Upload files), con un nombre que diga qué se ve. Los dibujitos se los "
               "pedís a Claude y te pasa el archivo para subir."]
    md += ["", "## Ideas para las próximas semanas", ""]
    md += [f'- **{i.get("serie", "")}**: {i.get("titulo", "")} · miniatura: "{i.get("miniatura", "")}"'
           for i in a.get("ideas", [])]
    md += ["", "## Lo que más rindió en cada canal", "", resumen]
    ruta = util.RAIZ / "reportes" / f"{fecha}.md"
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_text("\n".join(md) + "\n", encoding="utf-8")
    try:
        pub.mail(f"Reporte semanal de competencia · {fecha}",
                 "<pre style='font-family:Arial;white-space:pre-wrap'>" + html.escape("\n".join(md)) + "</pre>")
    except Exception as ex:  # noqa
        util.log("No pude mandar el mail:", ex)


# ---------------------------------------------------------------- reintentar lo que no salió
REINTENTABLES = ("instagram_reel", "instagram_carrusel", "facebook")
REINTENTOS = "data/reintentos.json"  # aparte del historial, para no chocar con la publicación del día


def con_reintentos(historial):
    """El historial con lo que salió después en un reintento (pisa el error de ese día)."""
    reint = util.leer_json(REINTENTOS, {}) or {}
    for h in historial:
        extra = reint.get(f'{h.get("fecha")}#{h.get("turno", 1)}')
        if extra:
            h["resultados"] = {**(h.get("resultados") or {}), **extra}
    return historial


def _texto_publicado(base_nombre):
    """El texto (caption) que se usó, sacado del registro de publicaciones/."""
    ruta = util.RAIZ / "publicaciones" / f"{base_nombre}.md"
    if not ruta.exists():
        return None
    md = ruta.read_text(encoding="utf-8")
    if "## Texto" not in md:
        return None
    return md.split("## Texto", 1)[1].split("\n## Guion", 1)[0].strip()


def reintentar(cuales=""):
    """Vuelve a subir, solo en las redes donde falló, los videos que siguen en la página (dias_en_pagina).
    No arma nada nuevo ni toca las redes donde ya salió. `cuales`: vacío = todos los que fallaron; o fechas
    tipo 2026-10-27 o 2026-10-27-t2 separadas por coma."""
    from . import publicar as pub
    cfg = util.config()
    quiere = cfg.get("publicar", {})
    base = _base_paginas()
    if not base:
        util.log("No sé la dirección de la página (falta GITHUB_REPOSITORY)")
        sys.exit(1)
    elegidos = {x.strip() for x in (cuales or "").split(",") if x.strip()}
    desde = (util.ahora() - util.timedelta(days=_dias_pagina())).strftime("%Y-%m-%d")
    historial = con_reintentos(util.leer_json("data/historial.json", []) or [])
    sitio = util.leer_json("data/sitio.json", []) or []
    reint = util.leer_json(REINTENTOS, {}) or {}
    informe, alguno = [], False
    for h in historial:
        if h.get("cancelado") or h.get("fecha", "") < desde:
            continue
        nombre = _carpeta(h["fecha"], h.get("turno", 1))
        if elegidos and nombre not in elegidos and h["fecha"] not in elegidos:
            continue
        res = h.setdefault("resultados", {})
        faltan = [r for r in REINTENTABLES if r in res and not res[r].get("ok") and quiere.get(r)]
        if not faltan:
            continue
        carpetas = [x for x in sitio if x.get("carpeta") == nombre or str(x.get("carpeta", "")).startswith(nombre + "-v")]
        texto = _texto_publicado(nombre)
        if not carpetas or not texto:
            informe.append((h["titulo"], {r: {"ok": False, "error": "ya no está el video o el texto (pasaron más de "
                                                                     f"{_dias_pagina()} días)"} for r in faltan}))
            continue
        archivos = carpetas[-1]["archivos"]
        video_rel, portada_rel, placas = archivos[0], archivos[1], archivos[2:]
        local = SALIDA / "reintento" / f"{nombre}.mp4"
        local.parent.mkdir(parents=True, exist_ok=True)
        r = util.pedir("GET", base + video_rel, intentos=3, timeout=180)
        if r is None or r.status_code != 200:
            informe.append((h["titulo"], {x: {"ok": False, "error": "no pude bajar el video de la página"} for x in faltan}))
            continue
        local.write_bytes(r.content)
        util.log(f"Reintento {nombre} ({h['titulo']}) en:", ", ".join(faltan))
        nuevos = {}
        for red in faltan:
            try:
                if red == "instagram_reel":
                    rid = pub.instagram_reel(base + video_rel, base + portada_rel, texto)
                elif red == "instagram_carrusel":
                    if not placas:
                        raise RuntimeError("no hay placas guardadas")
                    rid = pub.instagram_carrusel([base + x for x in placas], texto)
                else:
                    rid = pub.facebook_reel(local, texto, h["titulo"])
                nuevos[red] = {"ok": True, "id": rid, "reintento": util.ahora().strftime("%Y-%m-%d %H:%M")}
                alguno = True
            except Exception as e:  # noqa
                nuevos[red] = {"ok": False, "error": str(e)[:300]}
            util.log(red, nuevos[red])
        clave_r = f'{h["fecha"]}#{h.get("turno", 1)}'
        reint[clave_r] = {**reint.get(clave_r, {}), **nuevos}
        informe.append((h["titulo"], nuevos))
    util.guardar_json(REINTENTOS, reint)
    if not informe:
        util.log("No hay nada pendiente: todo lo de los últimos días ya salió (o no está en la página).")
        return
    e = html.escape
    cuerpo = "".join(
        f"<h3>{e(t)}</h3><ul>" + "".join(
            f'<li><b>{e(red)}</b>: {"✅ publicado" if r["ok"] else "❌ " + e(r["error"])}</li>' for red, r in rr.items())
        + "</ul>" for t, rr in informe)
    try:
        pub.mail("Reintento de publicación", cuerpo)
    except Exception as ex:  # noqa
        util.log("No pude mandar el mail:", ex)
    if not alguno:
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["generar", "publicar", "resumen", "reporte", "toca", "esperar", "probar",
                                       "rehacer", "listo", "revisar", "online", "mejoras", "sugerencia", "tiktok",
                                       "reintentar", "preparar_capitulo", "corregir_capitulo"])
    ap.add_argument("--ultima", action="store_true")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--simulado", action="store_true")
    a = ap.parse_args()
    try:
        if a.accion == "toca":
            toca()
        elif a.accion == "preparar_capitulo":
            preparar_capitulo()
        elif a.accion == "corregir_capitulo":
            corregir_capitulo()
        elif a.accion == "mejoras":
            from . import mejoras
            mejoras.diario(regenerar=_proponer_hoy, medir=lambda: _para_mejoras(util.config())[0])
        elif a.accion == "tiktok":
            cargar_tiktok()
        elif a.accion == "reintentar":
            reintentar(os.getenv("CUALES", ""))
        elif a.accion == "sugerencia":
            sugerencia()
        elif a.accion == "esperar":
            esperar(a.ultima)
        elif a.accion == "rehacer":
            rehacer()
        elif a.accion == "listo":
            listo(a.base_url)
        elif a.accion == "online":
            online(a.base_url)
        elif a.accion == "revisar":
            revisar()
        elif a.accion == "generar":
            generar(a.simulado)
        elif a.accion == "publicar":
            publicar(a.base_url)
        elif a.accion == "resumen":
            resumen(a.base_url)
        elif a.accion == "probar":
            from . import probar
            probar.probar()
        else:
            reporte()
    except Exception as error:  # noqa
        import traceback
        print(util.ocultar(traceback.format_exc()), flush=True)
        util.avisar_error(a.accion, error)
        sys.exit(1)
