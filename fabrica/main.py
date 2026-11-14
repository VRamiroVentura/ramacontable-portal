"""Fábrica de notas de Ramacontable.

Cada vuelta: lee fuentes oficiales y portales → agrupa por tema → decide qué publicar →
redacta con Gemini → verifica que no haya datos inventados → publica (o deja para revisar) → avisa por mail.
En modo "ensayo" no guarda nada: muestra en el resumen de la ejecución lo que hubiera publicado."""
import glob
import json
import os
import re
import unicodedata
from datetime import timedelta

from . import fuentes, gemini, mail, util

FUENTES_EXTRA = [{"nombre": "ARBA", "tipo": "oficial", "url": "https://web.arba.gov.ar/noticias"}, {"nombre": "Gobierno nacional (argentina.gob.ar)", "tipo": "oficial", "url": "https://www.argentina.gob.ar/noticias", "filtro": ["arca", "afip", "anses", "monotribut", "ganancias", "impuest", "iva", "salario", "jubil", "asignaci", "auh", "bcra", "banco central", "feriado", "decreto", "resolucion general", "aportes", "contribuciones", "trabajo", "empleo", "paritari", "convenio", "srt", "riesgos del trabajo", "aduana", "retencion", "percepcion"]}, {"nombre": "Tributum", "tipo": "portal", "url": "https://tributum.news/feed/"}, {"nombre": "Estudio Vilaplana", "tipo": "portal", "url": "https://www.estudiovilaplana.com.ar/feed/"}, {"nombre": "iProfesional Impuestos", "tipo": "apoyo", "url": "https://www.iprofesional.com/rss/impuestos.xml", "filtro": ["arca", "afip", "anses", "monotribut", "ganancias", "iva", "bienes personales", "ingresos brutos", "arba", "agip", "impuesto", "boletin oficial", "resolucion general", "decreto", "convenio", "paritaria", "escala", "salari", "sueldo", "aguinaldo", "indemniz", "aportes", "contribuciones", "seguridad social", "art ", "feriado", "vencimiento", "bcra", "comunicacion a", "reforma laboral"]}, {"nombre": "Calcular Sueldo", "tipo": "apoyo", "url": "https://calcularsueldo.com.ar/feed/", "filtro": ["arca", "afip", "anses", "monotribut", "ganancias", "iva", "bienes personales", "ingresos brutos", "arba", "agip", "impuesto", "boletin oficial", "resolucion general", "decreto", "convenio", "paritaria", "escala", "salari", "sueldo", "aguinaldo", "indemniz", "aportes", "contribuciones", "seguridad social", "art ", "feriado", "vencimiento", "bcra", "comunicacion a", "reforma laboral"]}, {"nombre": "Econoblog", "tipo": "apoyo", "url": "https://www.econoblog.com.ar/feed/", "filtro": ["arca", "afip", "anses", "monotribut", "ganancias", "iva", "bienes personales", "ingresos brutos", "arba", "agip", "impuesto", "boletin oficial", "resolucion general", "decreto", "convenio", "paritaria", "escala", "salari", "sueldo", "aguinaldo", "indemniz", "aportes", "contribuciones", "seguridad social", "art ", "feriado", "vencimiento", "bcra", "comunicacion a", "reforma laboral"]}]

CONFIABLE = "Ignacio Online"  # lo que publica Ignacio se toma como correcto (pedido de Ramiro); se vigila si después lo edita o borra
# Blogs de confianza (pedido de Ramiro): con una sola nota de ellos alcanza para publicar; se vigila si la editan o la borran.
# Los de menor confianza (tipo "apoyo") siguen necesitando dos blogs o la fuente oficial. Se puede cambiar con "fuentes_confiables" en config.json.
CONFIABLES = ("Ignacio Online", "Contadores en Red", "Blog del Contador", "Tributum", "Estudio Vilaplana")


def _prompt(nombre):
    return (util.RAIZ / "prompts" / nombre).read_text(encoding="utf-8")


def _slug(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80] or "nota"


def _slug_sin_anio_falso(slug, nota):
    """El redactor a veces inventa un año viejo en la dirección (ej.: «...-octubre-2024» en una nota de 2026).
    Si el año de la dirección no figura en el título ni en el «En corto», se saca (junto con el mes que lo acompaña)."""
    texto = f"{nota.get('titulo', '')} {nota.get('encorto', '')} {nota.get('seo_titulo', '')}"
    meses = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
    for anio in set(re.findall(r"(?<![0-9])(20[0-9]{2})(?![0-9])", slug)):
        if anio in texto or anio == str(util.ahora().year):
            continue
        actual = str(util.ahora().year)
        if actual in texto and actual not in slug:  # el título habla de este año: se corrige el año y se conserva el mes
            slug = re.sub(rf"(?<![0-9]){anio}(?![0-9])", actual, slug)
            continue
        slug = re.sub(rf"(-(?:{meses}))*-{anio}(?=-|$)", "", slug)
        slug = re.sub(rf"^{anio}-", "", slug)
    return slug.strip("-") or "nota"


def _bloques_ok(cuerpo):
    salida = []
    for b in cuerpo if isinstance(cuerpo, list) else []:
        if isinstance(b, dict):
            if b.get("h"):
                salida.append({"h": str(b["h"])[:200]})
            elif b.get("p"):
                salida.append({"p": str(b["p"])[:3000]})
            elif isinstance(b.get("tabla"), list) and b["tabla"]:
                salida.append({"tabla": [[str(c)[:200] for c in fila][:8] for fila in b["tabla"][:40] if isinstance(fila, list)]})
    return salida


def _clasificar(control, dudas=()):
    """Separa los problemas del verificador en graves (pueden arruinar la nota) y menores."""
    altas, bajas = [], []
    for p in (control or {}).get("problemas") or []:
        if isinstance(p, dict):
            (bajas if str(p.get("gravedad", "")).lower() == "baja" else altas).append(
                {"dato": str(p.get("dato") or "")[:220], "fuente": str(p.get("fuente") or "")[:220], "revisar": str(p.get("revisar") or "")[:220]})
        elif str(p).strip():  # formato viejo (texto suelto): se trata como grave para no dejar pasar nada
            altas.append({"dato": str(p)[:300], "fuente": "", "revisar": ""})
    for d in dudas or []:
        altas.append({"dato": f"Duda del redactor: {str(d)[:250]}", "fuente": "", "revisar": ""})
    if (control or {}).get("agrega_ejemplos"):
        bajas.append({"dato": "Agrega un ejemplo práctico que no está en las fuentes", "fuente": "", "revisar": ""})
    return altas, bajas


def _motivo(altas):
    """Texto claro para el administrador: cuántos datos chequear y qué mirar en cada uno."""
    if not altas:
        return None
    lineas = [f"🔴 {len(altas)} {'dato' if len(altas) == 1 else 'datos'} para chequear antes de publicar"]
    for i, a in enumerate(altas, 1):
        txt = f"{i}) {a['revisar'] or a['dato']}"
        if a["revisar"] and a["dato"]:
            txt += f" — La nota dice: {a['dato']}"
        if a["fuente"]:
            txt += f" — Las fuentes: {a['fuente']}"
        lineas.append(txt)
    return "\n".join(lineas)[:1500]


class Fabrica:
    def __init__(self, db=None):
        self.cfg = util.config()
        self.activo = self.cfg.get("modo") == "activo"
        # vuelta rápida (cada 30 min): solo fuentes oficiales y el sumario del Boletín de Tributum; nada de guías ni escalas
        self.rapido = os.environ.get("RC_RAPIDO") == "1"
        self.db = db
        self.confiables = set(self.cfg.get("fuentes_confiables") or CONFIABLES)
        self.publicadas, self.revision, self.descartes, self.esperando = [], [], [], []
        self.convenios_act, self.convenios_rev = [], []
        self.guias = []
        self.guias_info = ""
        self.vencimientos_info, self.vencimientos_cambio = [], False
        self.observaciones, self.alertas, self.datos_obs = [], [], []
        self.convenios = self.cargar_convenios()

    # ---------- memoria ----------
    def notas_recientes(self):
        if not self.db:
            return []
        desde = (util.ahora() - timedelta(days=30)).date().isoformat()
        return self.db.select("notas", {"select": "slug,titulo,tema,fecha,estado", "fecha": f"gte.{desde}",
                                        "order": "fecha.desc", "limit": "200"})

    def fuentes_conocidas(self):
        if not self.db:
            return set()
        try:
            return {f["fuente"] for f in self.db.select("radar", {"select": "fuente", "limit": "5000"})}
        except gemini.SinTiempo:
            raise
        except Exception:  # noqa
            return set()

    def radar_previo(self):
        if not self.db:
            return {}
        desde = (util.ahora() - timedelta(days=self.cfg.get("dias_espera_segunda_fuente", 5))).isoformat()
        filas = self.db.select("radar", {"select": "*", "visto": f"gte.{desde}", "limit": "1000"})
        return {f["url"]: f for f in filas}

    def cargar_convenios(self):
        base = {}
        for ruta in glob.glob(str(util.RAIZ / "convenios" / "*.json")):
            c = json.load(open(ruta, encoding="utf-8"))
            base[c["slug"]] = c
        if self.db:
            try:
                for c in self.db.select("convenios", {"select": "*"}):
                    base[c["slug"]] = c
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.log("No pude leer convenios:", util.ocultar(str(e)))
        return base

    def sembrar(self):
        """Sube a Supabase las notas iniciales del repo (carpeta notas/) para poder editarlas desde la web."""
        filas = []
        for ruta in glob.glob(str(util.RAIZ / "notas" / "*.json")):
            n = json.load(open(ruta, encoding="utf-8"))
            filas.append({"slug": n["slug"], "fecha": n["fecha"], "seccion": n["seccion"], "antetitulo": n["antetitulo"],
                          "titulo": n["titulo"], "dato": n.get("dato"), "encorto": n["encorto"], "cuerpo": n["cuerpo"],
                          "fuente": n.get("fuente", ""), "fuentes": [], "verificada": bool(n.get("verificada")),
                          "estado": "publicada", "tema": n["titulo"]})
        if filas and self.db and self.activo:
            self.db.insertar_si_no_existe("notas", filas, "slug")
        if self.db and self.activo:
            convs = []
            for ruta in glob.glob(str(util.RAIZ / "convenios" / "*.json")):
                c = json.load(open(ruta, encoding="utf-8"))
                convs.append({k: c[k] for k in ("slug", "nombre", "cct", "partes", "descripcion")})
            if convs:
                try:
                    self.db.insertar_si_no_existe("convenios", convs, "slug")
                except gemini.SinTiempo:
                    raise
                except Exception as e:  # noqa
                    util.avisar("No pude guardar los convenios (¿falta correr esquema.sql en Supabase?)", str(e))

    # ---------- pasos ----------
    def leer_fuentes(self):
        items = []
        lista = list(self.cfg.get("fuentes", []))
        ya = {f.get("nombre") for f in lista}
        lista += [f for f in FUENTES_EXTRA if f["nombre"] not in ya]  # se suman solas, sin tocar config.json
        for ruta in sorted((util.RAIZ / "jurisdicciones").glob("*.json")):  # fuentes de provincias y municipios
            try:
                lista += [f for f in json.loads(ruta.read_text(encoding="utf-8")).get("fuentes") or [] if f.get("nombre") not in ya]
            except Exception as e:  # noqa
                util.avisar(f"No pude leer {ruta.name}", str(e))
        lista = [f for f in lista if "boletinoficial.gob.ar" not in f.get("url", "") or self.cfg.get("leer_boletin")]
        if self.rapido:
            lista = [f for f in lista if f.get("tipo") == "oficial" or f.get("nombre") == "Tributum"]  # no responde a GitHub; Tributum trae el sumario
        for f in lista:
            try:
                nuevos = fuentes.leer(f)
                util.log(f"{f['nombre']}: {len(nuevos)} novedades")
                items += nuevos
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar(f"No pude leer {f['nombre']}", str(e))
        return items

    def agrupar(self, items, recientes):
        lista = [{"id": i, "fuente": it["fuente"], "tipo": it["tipo"], "titulo": it["titulo"],
                  "resumen": (it.get("texto") or "")[:500]} for i, it in enumerate(items)]
        pedido = ("NOVEDADES:\n" + json.dumps(lista, ensure_ascii=False) +
                  "\n\nCONVENIOS:\n" + json.dumps([{"slug": c["slug"], "nombre": c["nombre"], "cct": c["cct"]} for c in self.convenios.values()], ensure_ascii=False) +
                  "\n\nNOTAS YA PUBLICADAS POR RAMACONTABLE (últimos 30 días):\n" +
                  json.dumps([{k: n.get(k) for k in ("slug", "titulo", "tema", "fecha")} for n in recientes if n.get("estado") != "borrada"],
                             ensure_ascii=False))
        return gemini.gemini(_prompt("agrupar.md"), pedido, temperatura=0.2).get("grupos", [])

    def redactar(self, grupo, items, recientes):
        textos = []
        for it in items:
            if len(it.get("texto") or "") < 1500:
                completo, _ = fuentes.detalle(it["url"])
                if len(completo) > len(it.get("texto") or ""):
                    it["texto"] = completo
            textos.append(f"--- FUENTE: {it['fuente']} ({'oficial' if it['tipo'] == 'oficial' else 'portal'})\n"
                          f"Título: {it['titulo']}\nTexto: {(it.get('texto') or '')[:6000]}")
        anterior = ""
        if grupo.get("actualiza"):
            prev = next((n for n in recientes if n["slug"] == grupo["actualiza"]), None)
            if prev:
                anterior = f"\n\nESTA NOTA ACTUALIZA la nota anterior «{prev['titulo']}» (slug {prev['slug']})."
        pedido = f"TEMA: {grupo.get('tema')}\nSECCIÓN: {grupo.get('seccion')}{anterior}\n\nFUENTES:\n" + "\n\n".join(textos)
        nota = gemini.gemini(_prompt("redactar.md"), pedido, temperatura=0.4)
        control = gemini.gemini(_prompt("verificar.md"),
                                "NOTA:\n" + json.dumps(nota, ensure_ascii=False) + "\n\nFUENTES:\n" + "\n\n".join(textos),
                                temperatura=0.1)
        self._textos = textos
        return nota, control

    def actualizar_convenio(self, grupo, nota_slug, textos=None, adjunto=None, doc=None):
        c = self.convenios.get(grupo.get("convenio"))
        if not c:
            return
        textos = textos if textos is not None else self._textos
        actual = {k: c.get(k) for k in ("nombre", "cct", "escala", "novedades", "calculo", "nr", "recibo", "preguntas", "fuente")}
        pedido = "PÁGINA ACTUAL DEL CONVENIO:\n" + json.dumps(actual, ensure_ascii=False) + "\n\nFUENTES DEL NUEVO ACUERDO:\n" + "\n\n".join(textos)
        control_txt = "\n\nFUENTES:\n" + "\n\n".join(textos)
        if adjunto:  # PDF oficial: va como archivo para que Gemini lea la tabla tal cual
            pedido = [{"text": pedido + "\n(La fuente principal es el PDF oficial adjunto.)"}, adjunto]
        nuevo = gemini.gemini(_prompt("convenio.md"), pedido, temperatura=0.3)
        verif = "NOTA:\n" + json.dumps(nuevo, ensure_ascii=False) + control_txt
        control = gemini.gemini(_prompt("verificar.md"), [{"text": verif + "\n(Las fuentes incluyen el PDF oficial adjunto.)"}, adjunto] if adjunto else verif, temperatura=0.1)
        esc = nuevo.get("escala") if isinstance(nuevo.get("escala"), dict) else None
        if esc:
            tabla = esc.get("tabla") if isinstance(esc.get("tabla"), list) else []
            esc = {"periodo": str(esc.get("periodo") or "")[:80], "vigencia": str(esc.get("vigencia") or "")[:120],
                   "tabla": [[str(x)[:80] for x in f][:10] for f in tabla[:80] if isinstance(f, list)], "aclaraciones": str(esc.get("aclaraciones") or "")[:800],
                   "doc": doc}
        datos = {"escala": esc or c.get("escala"), "novedades": _bloques_ok(nuevo.get("novedades")), "calculo": _bloques_ok(nuevo.get("calculo")) or c.get("calculo") or [],
                 "nr": _bloques_ok(nuevo.get("nr")) or c.get("nr") or [], "recibo": _bloques_ok(nuevo.get("recibo")) or c.get("recibo") or [],
                 "preguntas": [{"p": str(q.get("p"))[:200], "r": str(q.get("r"))[:500]} for q in (nuevo.get("preguntas") or []) if isinstance(q, dict) and q.get("p") and q.get("r")][:6],
                 "fuente": str(nuevo.get("fuente") or c.get("fuente") or "")[:300]}
        hist = list(c.get("historial") or [])
        per = str(nuevo.get("periodo_historial") or (esc or {}).get("periodo") or grupo.get("tema"))[:80]
        if not any(h.get("periodo") == per for h in hist):
            ap = nuevo.get("aumento_pct")
            hist.append({"periodo": per, "fecha": util.ahora().date().isoformat(), "nota": nota_slug,
                         "aumento_pct": float(ap) if isinstance(ap, (int, float)) and 0 < ap < 100 else None})
        altas, bajas = _clasificar(control, nuevo.get("dudas"))
        ok = not altas
        if ok and bajas:
            self.observaciones.append((f"Escala {c['nombre']}", "; ".join(b["dato"] for b in bajas)[:400]))
        motivo = _motivo(altas) or ""
        registro = {"slug": c["slug"], "nombre": c["nombre"], "periodo": per, "motivo": motivo, "datos": datos}
        (self.convenios_act if ok else self.convenios_rev).append(registro)
        if self.activo and self.db:
            if ok:
                self.db.update("convenios", {"slug": f"eq.{c['slug']}"}, dict(datos, historial=hist, propuesta=None, motivo_propuesta=None))
            else:
                self.db.update("convenios", {"slug": f"eq.{c['slug']}"}, {"propuesta": dict(datos, historial=hist), "motivo_propuesta": motivo})

    def revisar_escalas_oficiales(self):
        """Lee la página o el PDF oficial de cada sindicato y actualiza la escala si hay un documento nuevo."""
        locales = {}
        for ruta in glob.glob(str(util.RAIZ / "convenios" / "*.json")):
            c = json.load(open(ruta, encoding="utf-8"))
            if c.get("oficial") or c.get("buscar_portal"):
                locales[c["slug"]] = c
        orden = sorted((s for s in locales if s in self.convenios), key=lambda s: str(self.convenios[s].get("actualizado") or ""))
        hechos = 0
        for slug in orden:
            if hechos >= int(self.cfg.get("escalas_por_vuelta", 3)):
                break
            c, loc = self.convenios[slug], locales[slug]
            url = tipo = contenido = None
            if loc.get("oficial"):
                try:
                    url, tipo, contenido = fuentes.documento_oficial(loc["oficial"], loc.get("buscar_doc") or ())
                except gemini.SinTiempo:
                    raise
                except Exception as e:  # noqa
                    util.avisar(f"No pude leer la escala oficial de {c['nombre']}", str(e))
            if not url and loc.get("buscar_portal"):
                # sin fuente oficial (o no se pudo leer): las notas de escalas de Ignacio Online y Contadores en Red
                notas = [n for n in fuentes.buscar_portales(loc["buscar_portal"], 2) if "escala" in _slug(n["titulo"])]
                if notas:
                    url, tipo = notas[0]["url"], "portal"
                    contenido = "\n\n".join(f"--- FUENTE: {n['fuente']} (portal)\nTítulo: {n['titulo']}\n{n['texto']}" for n in notas[:3])
            if not url:
                if util.ahora().hour == 9:  # una vez por día alcanza (antes salía en cada vuelta)
                    util.avisar(f"Escala de {c['nombre']}", "no encontré documento oficial ni notas de escala en los portales")
                continue
            ya = {(c.get("escala") or {}).get("doc"), ((c.get("propuesta") or {}).get("escala") or {}).get("doc")}
            if url in ya:
                util.log(f"{c['nombre']}: sin escala nueva ({url})")
                continue
            hechos += 1
            util.log(f"{c['nombre']}: documento nuevo {url}")
            if tipo == "pdf":
                import base64
                adjunto = {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(contenido).decode()}}
                textos = [f"--- FUENTE OFICIAL (PDF del sindicato): {url}"]
            elif tipo == "portal":
                adjunto, textos = None, [contenido]
            else:
                adjunto, textos = None, [f"--- FUENTE OFICIAL (página del sindicato): {url}\n{contenido}"]
            try:
                self.actualizar_convenio({"convenio": slug, "tema": c["nombre"]}, None, textos, adjunto, url)
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar(f"No pude actualizar la escala de {c['nombre']}", str(e))

    # ---------- vencimientos y feriados ----------
    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

    def actualizar_vencimientos(self):
        """Una vez por día: arma los vencimientos y feriados del mes actual y del siguiente con lo que publicaron
        los portales. Solo se publica lo que confirman al menos `minimo_fuentes` fuentes distintas y no es estimado."""
        if not self.db:
            return
        try:
            cfg = json.loads((util.RAIZ / "vencimientos" / "fuentes.json").read_text(encoding="utf-8"))
            previos = {r["mes"]: r for r in self.db.select("vencimientos", {"select": "mes,actualizado"})}
        except gemini.SinTiempo:
            raise
        except Exception as e:  # noqa
            util.avisar("No pude leer la agenda de vencimientos (¿falta correr esquema.sql?)", str(e))
            return
        hoy = util.ahora().date()
        minimo = int(cfg.get("minimo_fuentes", 2))
        for k in (0, 1):
            anio, mes = hoy.year + (hoy.month - 1 + k) // 12, (hoy.month - 1 + k) % 12 + 1
            clave = f"{anio}-{mes:02d}"
            if str((previos.get(clave) or {}).get("actualizado") or "")[:10] == hoy.isoformat():
                continue
            nombre_mes = self.MESES[mes - 1]
            textos, vistos = [], set()
            for plantilla in cfg.get("paginas", []):
                url = plantilla.format(mes=nombre_mes, anio=anio, mm=f"{mes:02d}")
                texto, _ = fuentes.detalle(url, largo=15000)
                if len(texto) > 300:
                    nombre = url.split("/")[2].replace("www.", "")
                    textos.append(f"--- FUENTE: {nombre}\n{texto}")
                    vistos.add(nombre)
            for consulta in cfg.get("buscar", []):
                for it in fuentes.buscar_portales(consulta.format(mes=nombre_mes, anio=anio), 2, cfg.get("wordpress")):
                    if nombre_mes in _slug(it["titulo"]) or nombre_mes in _slug(it["texto"][:600]):
                        textos.append(f"--- FUENTE: {it['fuente']}\nTítulo: {it['titulo']}\n{it['texto'][:6000]}")
                        vistos.add(it["fuente"])
            oficiales = tuple(cfg.get("oficiales") or ())  # organismos (ej.: Comisión Arbitral): su fecha alcanza sola
            if len(vistos) < minimo and CONFIABLE not in vistos and "lanacion.com.ar" not in vistos and not vistos & set(oficiales):
                util.avisar(f"Vencimientos de {nombre_mes}", f"solo encontré {len(vistos)} fuente(s); queda la agenda anterior")
                continue
            try:
                r = gemini.gemini(_prompt("vencimientos.md"), f"MES: {nombre_mes} {anio}\n\nFUENTES:\n" + "\n\n".join(textos), temperatura=0.1)
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar(f"No pude armar los vencimientos de {nombre_mes}", str(e))
                continue
            def confirmados(lista, campos, confiables=(CONFIABLE,)):
                salida = []
                for x in lista if isinstance(lista, list) else []:
                    if not isinstance(x, dict) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(x.get("fecha", ""))):
                        continue
                    n = len({str(f) for f in (x.get("fuentes") or [])})
                    de_ignacio = any(c in [str(f) for f in (x.get("fuentes") or [])] for c in confiables)
                    if (n >= minimo or de_ignacio) and not x.get("estimado") and str(x["fecha"]).startswith(clave):
                        salida.append({c: str(x.get(c) or "")[:160] for c in campos} | {"fuentes": n})
                return sorted(salida, key=lambda x: x["fecha"])
            venc = confirmados(r.get("vencimientos"), ("fecha", "concepto", "detalle"), (CONFIABLE,) + oficiales)
            # feriados: La Nación alcanza sola (pedido de Ramiro); los vencimientos siguen pidiendo 2 fuentes o Ignacio
            fer = confirmados(r.get("feriados"), ("fecha", "nombre", "tipo", "norma"), (CONFIABLE, "lanacion.com.ar"))
            util.log(f"Vencimientos {clave}: {len(venc)} confirmados, {len(fer)} feriados ({len(vistos)} fuentes)")
            self.vencimientos_info.append(f"{nombre_mes} {anio}: {len(venc)} vencimientos y {len(fer)} feriados confirmados por {minimo}+ fuentes ({', '.join(sorted(vistos))})")
            if self.activo and venc:
                self.db.upsert("vencimientos", [{"mes": clave, "items": venc, "feriados": fer, "fuentes": sorted(vistos),
                                                 "actualizado": util.ahora().isoformat()}], "mes")
                self.vencimientos_cambio = True

    def armar_fila(self, grupo, items, nota, control, usados):
        base = _slug_sin_anio_falso(_slug(nota.get("slug") or nota.get("titulo")), nota)
        slug, k = base, 2
        while slug in usados:
            slug, k = f"{base}-{k}", k + 1
        usados.add(slug)
        # Solo frena la nota lo grave (montos, fechas, normas, alcance...). Lo menor se publica y queda anotado.
        # Vale también para lo que viene de Ignacio: si el problema grave lo agregó la redacción, hay que mirarlo.
        altas, bajas = _clasificar(control, nota.get("dudas"))
        ok = not altas
        if ok and bajas:
            self.observaciones.append((nota.get("titulo", ""), "; ".join(b["dato"] for b in bajas)[:400]))
        oficial = any(it["tipo"] == "oficial" for it in items)
        return {
            "slug": slug, "fecha": util.ahora().date().isoformat(), "seccion": grupo.get("seccion") if grupo.get("seccion") in ("sueldos", "impuestos", "profesion") else "profesion",
            "antetitulo": str(nota.get("antetitulo", ""))[:120], "titulo": str(nota.get("titulo", ""))[:160],
            "dato": (str(nota["dato"])[:40] if nota.get("dato") else None), "encorto": str(nota.get("encorto", ""))[:600],
            "clave": (str(nota["clave"])[:80] if nota.get("clave") else None),
            "cuerpo": _bloques_ok(nota.get("cuerpo")), "fuente": str(nota.get("fuente", ""))[:300],
            "fuentes": [{"nombre": it["fuente"], "url": it["url"], "titulo": it["titulo"]} for it in items],
            "verificada": oficial and ok, "estado": "publicada" if ok else "revision", "tema": grupo.get("tema"),
            "actualiza": grupo.get("actualiza"),
            "convenio": grupo.get("convenio") if grupo.get("convenio") in self.convenios else None,
            "seo_titulo": str(nota.get("seo_titulo") or "")[:70] or None,
            "descripcion_seo": str(nota.get("descripcion_seo") or "")[:170] or None,
            "preguntas": [{"p": str(q.get("p", ""))[:200], "r": str(q.get("r", ""))[:500]} for q in (nota.get("preguntas") or [])
                          if isinstance(q, dict) and q.get("p") and q.get("r")][:5], "motivo_revision": _motivo(altas) if not ok else None,
        }

    def correr(self):
        util.log("Modo:", "ACTIVO (publica)" if self.activo else "ENSAYO (no publica nada)")
        if self.activo:
            self.sembrar()
        recientes = self.notas_recientes()
        previos = self.radar_previo()
        nuevos = [it for it in self.leer_fuentes() if it["url"] not in previos]
        # las páginas sin fecha (ARBA, portadas HTML) muestran notas viejas: se descartan las que ya pasaron por el radar alguna vez
        sin_fecha = [it["url"] for it in nuevos if not it.get("fecha")]
        if sin_fecha and self.db:
            vistas = set()
            for i in range(0, len(sin_fecha), 40):
                lote = ",".join('"' + u.replace('"', '') + '"' for u in sin_fecha[i:i + 40])
                try:
                    vistas |= {f["url"] for f in self.db.select("radar", {"select": "url", "url": f"in.({lote})"})}
                except gemini.SinTiempo:
                    raise
                except Exception:  # noqa
                    pass
            if vistas:
                util.log(f"{len(vistas)} notas sin fecha ya vistas antes: no se vuelven a procesar")
                nuevos = [it for it in nuevos if it["url"] not in vistas]
        conocidas = {f["fuente"] for f in previos.values()} | self.fuentes_conocidas()
        base = [it for it in nuevos if it["fuente"] not in conocidas and not it.get("fecha")]
        if base:
            util.log(f"{len(base)} notas viejas sin fecha de fuentes nuevas: quedan como vistas, no se publican")
            if self.activo and self.db:
                self.db.upsert("radar", [{"url": it["url"], "fuente": it["fuente"], "tipo": it["tipo"], "titulo": it["titulo"][:300],
                                          "usado": True, "tema": "ya existente al empezar"} for it in base], "url")
            nuevos = [it for it in nuevos if it not in base]
        # novedades vistas en vueltas anteriores que siguen esperando una segunda fuente
        esperando = [{"titulo": f["titulo"], "url": f["url"], "fecha": f.get("fecha"), "texto": f.get("texto") or "",
                      "fuente": f["fuente"], "tipo": f["tipo"]} for f in previos.values() if not f.get("usado")]
        if self.rapido:
            esperando = [f for f in esperando if f.get("tipo") == "oficial"]
        items = nuevos + esperando
        util.log(f"{len(nuevos)} novedades nuevas y {len(esperando)} esperando segunda fuente")
        if self.activo and self.db and nuevos:
            self.db.upsert("radar", [{"url": it["url"], "fuente": it["fuente"], "tipo": it["tipo"], "titulo": it["titulo"][:300],
                                      "texto": (it.get("texto") or "")[:4000], "fecha": it.get("fecha")} for it in nuevos], "url")
        if not items:
            self.tareas_finales()
            return
        try:
            grupos = self.agrupar(items, recientes)
        except gemini.SinTiempo:
            raise
        except Exception as e:  # noqa  (las novedades quedan en el radar y se procesan en la próxima vuelta)
            util.avisar("No pude agrupar las novedades (quedan para la próxima vuelta)", str(e))
            grupos = []
        usados_slug = {n["slug"] for n in recientes}
        hechas = 0
        for g in grupos:
            miembros = [items[i] for i in g.get("items", []) if isinstance(i, int) and 0 <= i < len(items)]
            if not miembros:
                continue
            urls = [m["url"] for m in miembros]
            if not g.get("profesion") or g.get("repetido"):
                self.descartes.append((g.get("tema"), "no es de la profesión" if not g.get("profesion") else "ya publicado"))
                self.marcar(urls, g.get("tema"), None)
                continue
            oficial = any(m["tipo"] == "oficial" for m in miembros)
            portales = {m["fuente"] for m in miembros if m["tipo"] != "oficial"}
            if not oficial and not portales:
                continue
            # Las notas propias de un medio (investigaciones, encuestas, opinión) no se replican:
            # solo novedades normativas u oficiales, o temas que ya publicaron varios portales.
            # (pedido de Ramiro: con un solo blog no se replican; si la sacan dos o más blogs distintos se arma pero queda en revisión)
            propia_varios = False
            if g.get("clase") == "propia" and not oficial:
                if len(portales) >= 2:
                    propia_varios = True
                else:
                    self.descartes.append((g.get("tema"), "nota propia de un blog (no sale de una norma, actualización ni novedad oficial): no se replica"))
                    self.marcar(urls, g.get("tema"), None)
                    continue
            # Regla de fuentes: se publica si hay fuente oficial, si lo trae Ignacio Online, si lo publicaron
            # al menos 2 portales, o si la nota del portal cita la fuente oficial y la podemos leer para chequear.
            # Los blogs de "apoyo" (generalistas) nunca arrancan una nota solos: solo confirman un tema
            # que ya trae una fuente oficial o un blog contable principal.
            principales = {m["fuente"] for m in miembros if m["tipo"] == "portal"}
            if not oficial and not principales:
                # blogs de apoyo solos: alcanza si coinciden dos distintos, o si uno cita la fuente oficial y se puede chequear
                apoyos = {m["fuente"] for m in miembros if m["tipo"] == "apoyo"}
                if len(apoyos) >= 2:
                    self.observaciones.append((g.get("tema") or "", f"Lo confirman dos blogs de apoyo ({', '.join(sorted(apoyos))})"))
                else:
                    citada = None
                    for m in [x for x in miembros if x["tipo"] == "apoyo"][:2]:
                        try:
                            citada = fuentes.fuente_oficial_citada(m["url"])
                        except Exception:  # noqa
                            citada = None
                        if citada and not citada.get("pdf"):
                            break
                        citada = None
                    if not citada:
                        self.esperando.append((g.get("tema"), f"solo en un blog de apoyo ({', '.join(sorted(portales))}) y sin fuente oficial para chequear: espera otro blog o la fuente oficial"))
                        continue
                    miembros = miembros + [citada]
                    oficial = True
                    self.observaciones.append((g.get("tema") or "", f"Un blog de apoyo; se chequeó con la fuente oficial que cita: {citada['url']}"))
            de_confianza = portales & self.confiables
            if not oficial and de_confianza:
                # un blog de confianza alcanza; si cita la fuente oficial y se puede leer, se suma para chequear los datos
                try:
                    m0 = next(x for x in miembros if x["fuente"] in de_confianza)
                    citada = fuentes.fuente_oficial_citada(m0["url"])
                except Exception:  # noqa
                    citada = None
                if citada and not citada.get("pdf"):
                    miembros = miembros + [citada]
                    oficial = True
            if not oficial and not de_confianza and len(portales) < int(self.cfg.get("portales_minimos", 2)):
                citada = None
                for m in [x for x in miembros if x["tipo"] == "portal"][:2]:
                    try:
                        citada = fuentes.fuente_oficial_citada(m["url"])
                    except Exception:  # noqa
                        citada = None
                    if citada and not citada.get("pdf"):
                        break
                    citada = None
                if not citada:
                    self.esperando.append((g.get("tema"), f"solo en {', '.join(sorted(portales))} y sin fuente oficial para chequear: espera un segundo portal"))
                    continue
                miembros = miembros + [citada]
                oficial = True
                self.observaciones.append((g.get("tema") or "", f"Un solo portal; se chequeó con la fuente oficial que cita: {citada['url']}"))
            if hechas >= self.cfg.get("max_notas_por_vuelta", 6):
                self.esperando.append((g.get("tema"), "queda para la próxima vuelta"))
                continue
            try:
                nota, control = self.redactar(g, miembros, recientes)
                fila = self.armar_fila(g, miembros, nota, control, usados_slug)
                if propia_varios:
                    puntos = [f"Es una nota propia de {', '.join(sorted(portales))} (no sale de una norma ni de una novedad oficial). "
                              "La armamos porque la publicaron dos o más blogs: decidí si la publicamos"]
                    previo = fila.get("motivo_revision") or ""
                    if previo.startswith("🔴"):
                        puntos += [re.sub(r"^\d+\)\s*", "", x) for x in previo.split("\n")[1:] if x.strip()]
                    fila["estado"], fila["verificada"] = "revision", False
                    fila["motivo_revision"] = (f"🔴 {len(puntos)} {'dato' if len(puntos) == 1 else 'datos'} para chequear antes de publicar\n"
                                               + "\n".join(f"{i}) {t}" for i, t in enumerate(puntos, 1)))[:1500]
            except gemini.SinTiempo:
                self.esperando.append((g.get("tema"), "sin tiempo en esta vuelta: queda para la próxima"))
                continue
            except Exception as e:  # noqa
                util.avisar(f"No pude escribir «{g.get('tema')}»", str(e))
                continue
            hechas += 1
            (self.publicadas if fila["estado"] == "publicada" else self.revision).append(fila)
            try:
                self.datos_por_nota(fila, miembros)
            except gemini.SinTiempo:
                pass
            if self.activo and self.db:
                self.db.upsert("notas", [fila], "slug")
                self.marcar(urls, g.get("tema"), fila["slug"])
                for mi in miembros:
                    if mi["fuente"] in self.confiables:
                        base_txt, _ = fuentes.detalle(mi["url"], largo=6000)
                        if base_txt:
                            self.db.update("radar", {"url": f"eq.{mi['url']}"}, {"texto": base_txt[:6000]})
            if g.get("escala") and fila.get("convenio"):
                try:
                    self.actualizar_convenio(g, fila["slug"] if fila["estado"] == "publicada" else None)
                except gemini.SinTiempo:
                    raise
                except Exception as e:  # noqa
                    util.avisar(f"No pude actualizar el convenio {fila['convenio']}", str(e))
        self.tareas_finales()

    def tareas_finales(self):
        if self.rapido:  # la vuelta rápida solo publica novedades; el resto lo hace la vuelta completa
            return self.cierre()
        """Guías, escalas, vencimientos y vigilancia, en ese orden. Si se acaba el tiempo, lo que falta queda
        para la próxima vuelta y la vuelta cierra igual (publica la web, manda el mail y deja el resumen)."""
        try:
            # la vigilancia va primero: no usa Gemini y si un blog de confianza borró o corrigió algo, nuestra nota sale ya
            for nombre, tarea in [("vigilancia de los blogs de confianza", self.vigilar_ignacio), ("datos al día", self.actualizar_respuestas), ("guías", self.escribir_guias),
                                  ("escalas oficiales", self.revisar_escalas_oficiales), ("vencimientos", self.actualizar_vencimientos)]:
                try:
                    gemini._queda()
                    tarea()
                except gemini.SinTiempo:
                    self.observaciones.append(("⏱️ Sin tiempo", f"{nombre} y lo que sigue quedan para la próxima vuelta"))
                    util.log(f"Sin tiempo: {nombre} y lo que sigue quedan para la próxima vuelta")
                    break
                except gemini.SinTiempo:
                    raise
                except Exception as e:  # noqa
                    util.avisar(f"Falló el paso de {nombre} (sigue el resto)", str(e))
        finally:
            self.cierre()

    # ---------- datos del día (páginas respuesta) ----------
    def _temas_y_previos(self):
        if not hasattr(self, "_resp_cache"):
            temas = json.load(open(util.RAIZ / "respuestas" / "temas.json", encoding="utf-8"))
            previos = {r["slug"]: r for r in self.db.select("respuestas", {"select": "*"})} if self.db else {}
            for f in (util.RAIZ / "respuestas" / "inicial").glob("*.json"):  # punto de partida si todavía no hay dato guardado
                r = json.load(open(f, encoding="utf-8"))
                previos.setdefault(r["slug"], r)
            try:
                ipc = json.load(open(util.RAIZ / "respuestas" / "ipc.json", encoding="utf-8")).get("fechas", [])
            except Exception:  # noqa
                ipc = []
            self._resp_cache = (temas, previos, ipc)
            self.pedidos_datos = 0
        return self._resp_cache

    @staticmethod
    def _dia(v):
        try:
            return util.ahora().date().fromisoformat(str(v)[:10])
        except Exception:  # noqa
            return None

    def _toca(self, t, prev, ipc):
        """Motivo para rechequear hoy un dato (o None). Ciclo: semanal en espera; ventana diaria solo
        alrededor de la fecha esperada y mientras no haya cambiado; rechequeo único al día siguiente de un cambio."""
        hoy = util.ahora().date()
        rev, camb = self._dia(prev.get("revisado")), self._dia(prev.get("cambiado"))
        if not prev:
            return "primera carga"
        if rev == hoy:
            return None
        if camb and rev and (hoy - camb).days in (1, 2) and rev <= camb:
            return "rechequeo después del cambio"
        c = t.get("ciclo") or {}
        tipo = c.get("tipo")
        if tipo == "movilidad":
            fechas = [self._dia(x) for x in ipc]
            for m in (hoy.replace(day=1) - timedelta(days=1), hoy):  # mes sin fecha oficial cargada: se estima el 13
                if not any(x and (x.year, x.month) == (m.year, m.month) for x in fechas):
                    fechas.append(m.replace(day=13))
            for d in [x for x in fechas if x]:
                if 4 <= (hoy - d).days <= 7 and (not camb or camb < d):
                    return "fecha esperada (después del IPC del INDEC)"
                if (hoy - d).days == 8 and (not camb or camb < d):
                    self.alertas.append(f"Dato «{t['titulo']}»: pasó la fecha esperada (IPC del {d:%d/%m}) y todavía no se confirmó el cambio")
        for v in c.get("ventanas") or []:
            ini, fin = v.split("/")
            i = hoy.replace(month=int(ini[:2]), day=int(ini[3:]))
            f = hoy.replace(month=int(fin[:2]), day=int(fin[3:]))
            if i > f:  # ventana que cruza el año (ej.: 26/12 al 10/02)
                i = i.replace(year=hoy.year - 1) if hoy <= f else i
                f = f if hoy <= f else f.replace(year=hoy.year + 1)
            if i <= hoy <= f and (not camb or camb < i) and (not rev or (hoy - rev).days >= 2):
                return "ventana de actualización"
        if c.get("diario_desde") and self._dia(c["diario_desde"]) and self._dia(c["diario_desde"]) <= hoy \
                and (not camb or camb < self._dia(c["diario_desde"])) and (not rev or (hoy - rev).days >= 2):
            return "se espera un acuerdo nuevo"
        if not rev or (hoy - rev).days >= 7 * int(c.get("semanas", 1)):
            return "chequeo semanal"
        return None

    def _chequear(self, t, prev, textos, usadas, motivo):
        hoy = util.ahora().date().isoformat()
        pedido = (f"FECHA DE HOY: {hoy}\nTEMA: {t['titulo']}\nPREGUNTA: {t['pregunta']}\nQUÉ HAY QUE INFORMAR: {t['pide']}\n"
                  f"FORMATO ESTRUCTURADO: {t.get('estructura') or 'null'}\n\n"
                  f"DATO ANTERIOR: {json.dumps(prev.get('datos') or {}, ensure_ascii=False)}\n\nFUENTES:\n" + "\n\n".join(textos))
        self.pedidos_datos += 1
        r = gemini.gemini(_prompt("respuesta.md"), pedido, temperatura=0.1)
        nombres = {u["nombre"] for u in usadas}
        confirman = [c for c in (r.get("confirman") or []) if c in nombres]
        fuerte = any(c.startswith("Fuente oficial") or c == CONFIABLE for c in confirman) or len(set(confirman)) >= 2
        if not r.get("ok") or r.get("dudas") or not fuerte or not r.get("valor"):
            self.datos_obs.append((t["titulo"], f"Sin confirmar ({motivo}); queda el anterior: "
                                       + "; ".join(map(str, r.get("dudas") or ["no lo confirmaron 2 fuentes"]))[:300]))
            return False
        ahora = util.ahora().isoformat()
        cambio = not prev or (prev.get("datos") or {}).get("valor") != r.get("valor")
        hist = list(prev.get("historial") or [])
        if cambio:
            hist = ([{"fecha": hoy, "valor": r["valor"], "norma": r.get("norma")}] + hist)[:24]
        fila = {"slug": t["slug"], "titulo": t["titulo"], "datos": r,
                "fuentes": [u for u in usadas if u["nombre"] in confirman][:6], "revisado": ahora,
                "cambiado": ahora if cambio else (prev.get("cambiado") or ahora), "historial": hist}
        if self.activo:
            self.db.upsert("respuestas", [fila], "slug")
            self.vencimientos_cambio = True
        self._resp_cache[1][t["slug"]] = fila
        self.vencimientos_info.append(f"Dato del día «{t['titulo']}» ({motivo}): {'CAMBIÓ a ' if cambio else 'sin cambios, '}{r['valor']} (confirman: {', '.join(confirman)})")
        return True

    def datos_por_nota(self, fila, miembros):
        """La nota nueva sobre un tema actualiza su dato del día con las mismas fuentes (1 pedido, solo ese día)."""
        if not self.db or fila.get("estado") != "publicada":
            return
        try:
            temas, previos, _ = self._temas_y_previos()
        except Exception:  # noqa
            return
        texto = (fila.get("titulo", "") + " " + fila.get("encorto", "")).lower()
        hoy = util.ahora().date()
        for t in temas:
            if not any(c.lower() in texto for c in t.get("claves", [])):
                continue
            prev = previos.get(t["slug"]) or {}
            camb = self._dia(prev.get("cambiado"))
            if self._dia(prev.get("revisado")) == hoy or (camb and (hoy - camb).days < 5):
                continue  # ya se revisó hoy o el ciclo ya cerró con un cambio reciente
            textos = [f"[{m['fuente']}] {m['titulo']} {m['url']}\n{(m.get('texto') or '')[:6000]}" for m in miembros]
            usadas = [{"nombre": ("Fuente oficial (" + m["url"].split("/")[2].replace("www.", "") + ")") if m["tipo"] == "oficial" else m["fuente"],
                       "url": m["url"], "titulo": m["titulo"]} for m in miembros]
            textos = [x.replace(f"[{m['fuente']}]", f"[{u['nombre']}]", 1) for x, m, u in zip(textos, miembros, usadas)]
            try:
                self._chequear(t, prev, textos, usadas, "nota nueva: " + fila.get("titulo", "")[:80])
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar(f"No pude actualizar el dato «{t['titulo']}» con la nota", str(e))

    def actualizar_respuestas(self):
        """Chequeos programados de los datos del día, solo en días hábiles de 9 a 20 y como mucho 2 por vuelta."""
        if not self.db:
            return
        try:
            temas, previos, ipc = self._temas_y_previos()
        except gemini.SinTiempo:
            raise
        except Exception as e:  # noqa
            util.avisar("No pude leer los datos del día (¿falta correr esquema.sql en Supabase?)", str(e))
            return
        ahora = util.ahora()
        primera = any(t["slug"] not in previos for t in temas)
        if not primera and (ahora.weekday() >= 5 or not 9 <= ahora.hour < 20):
            return
        hechos = 0
        for t in temas:
            if hechos >= int(self.cfg.get("respuestas_por_vuelta", 2)):
                break
            prev = previos.get(t["slug"]) or {}
            motivo = self._toca(t, prev, ipc)
            if not motivo:
                continue
            textos, usadas = [], []
            for u in t.get("oficial") or []:
                try:
                    tx, _ = fuentes.detalle(u, largo=8000)
                except gemini.SinTiempo:
                    raise
                except Exception:  # noqa
                    tx = ""
                if len(tx) > 200:
                    nombre = "Fuente oficial (" + u.split("/")[2].replace("www.", "") + ")"
                    textos.append(f"[{nombre}] {u}\n{tx}"); usadas.append({"nombre": nombre, "url": u, "oficial": True})
            for it in fuentes.buscar_portales(t["busqueda"], por_portal=2):
                textos.append(f"[{it['fuente']}] {it['titulo']} {it['url']}\n{it['texto'][:5000]}")
                usadas.append({"nombre": it["fuente"], "url": it["url"], "titulo": it["titulo"]})
            hechos += 1
            if not textos:
                self.datos_obs.append((t["titulo"], f"No encontré fuentes para rechequear ({motivo})"))
                continue
            try:
                self._chequear(t, prev, textos, usadas, motivo)
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar(f"No pude rechequear «{t['titulo']}»", str(e))

    def cierre(self):
        if self.activo:
            if self.publicadas or self.convenios_act or self.vencimientos_cambio:
                self.republicar_web()
            mail.avisar(self.publicadas + self.revision, self.cfg.get("sitio_url", ""), self.cfg.get("mail_aviso"), self.convenios_act, self.convenios_rev,
                        self.alertas, self.observaciones)
        self.informe()

    # ---------- guías ----------
    def escribir_guias(self):
        """Escribe de a poco las guías del catálogo que todavía no existen (máximo guias_por_dia)."""
        try:
            catalogo = json.loads((util.RAIZ / "guias" / "catalogo.json").read_text(encoding="utf-8"))
        except gemini.SinTiempo:
            raise
        except Exception:  # noqa
            return
        por_dia = int(self.cfg.get("guias_por_dia", 2))
        existentes, hoy = set(), util.ahora().date().isoformat()
        if self.db:
            try:
                filas = self.db.select("notas", {"select": "slug,fecha,actualizado", "tipo": "eq.guia", "limit": "1000"})
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar("No pude leer las guías (¿falta correr esquema.sql en Supabase?)", str(e))
                return
            # "rehacer" en el catálogo: la guía se vuelve a escribir si es anterior a esa fecha (misma dirección)
            rehacer = {"guia-" + g["slug"]: g["rehacer"] for g in catalogo if g.get("rehacer")}
            # «rehacer_anual»: fechas MM-DD de cada año (antes del pico de búsquedas). La guía se reescribe si es anterior
            # a la última de esas fechas que ya pasó (misma dirección: suma posicionamiento año tras año).
            hoy_d = util.ahora().date()
            for g in catalogo:
                fechas = []
                for md in g.get("rehacer_anual") or []:
                    try:
                        f_ = hoy_d.replace(month=int(md[:2]), day=int(md[3:]))
                    except ValueError:
                        continue
                    fechas.append(f_ if f_ <= hoy_d else f_.replace(year=f_.year - 1))
                if fechas:
                    tope = max(fechas).isoformat()
                    rehacer["guia-" + g["slug"]] = max(rehacer.get("guia-" + g["slug"], ""), tope)
            self.guias_a_rehacer = {f["slug"] for f in filas} & set(rehacer)
            existentes = {f["slug"] for f in filas
                          if not (f["slug"] in rehacer and str(f.get("actualizado") or f.get("fecha") or "")[:10] < rehacer[f["slug"]])}
            por_dia -= sum(1 for f in filas if str(f["fecha"]) == hoy)
        pendientes = [g for g in catalogo if "guia-" + g["slug"] not in existentes]
        self.guias_info = (f"{len(existentes)} escritas (publicadas o para revisar), {len(pendientes)} pendientes; "
                           f"cupo que queda hoy: {max(0, por_dia)} (guias_por_dia en config.json)")
        util.log("Guías:", self.guias_info)
        for g in pendientes[:max(0, min(por_dia, int(self.cfg.get("guias_por_vuelta", 3))))]:
            try:
                self.escribir_guia(g)
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar(f"No pude escribir la guía «{g['titulo']}»", str(e))

    def escribir_guia(self, g):
        items = fuentes.buscar_portales(g["buscar"])
        claves = [_slug(c).replace("-", " ") for c in g.get("claves") or []]
        trata = lambda txt: any(re.search(rf"(?<![a-z0-9]){re.escape(c)}(?![a-z0-9])", _slug(txt).replace("-", " ")) for c in claves)
        if claves:
            # la búsqueda de los portales trae notas de otros temas (ej. "iva" aparece dentro de "operativa"):
            # solo quedan las que hablan del tema en el título o lo nombran varias veces en el texto
            items = [it for it in items if trata(it["titulo"]) or sum(1 for _ in re.finditer(
                rf"(?<![a-z0-9]){re.escape(claves[0])}(?![a-z0-9])", _slug(it["texto"]).replace("-", " "))) >= 3]
        textos = []
        for ref in g.get("oficial") or []:
            t = fuentes.texto_oficial(ref)
            if t:
                textos.append(f"--- FUENTE OFICIAL: {ref['url']}\n{t}")
        textos += [f"--- FUENTE: {it['fuente']} (portal)\nTítulo: {it['titulo']}\nTexto: {it['texto']}" for it in items]
        if not textos:
            util.avisar("Guía sin fuentes", f"«{g['titulo']}»: los portales no devolvieron material; queda para otra vuelta.")
            return
        pedido = f"TEMA DE LA GUÍA: {g['titulo']}\nSECCIÓN: {g['seccion']}\n\nFUENTES:\n" + "\n\n".join(textos)
        nota = gemini.gemini(_prompt("guia.md"), pedido, temperatura=0.4)
        if str(nota.get("titulo", "")).strip().upper() == "SIN MATERIAL":
            util.avisar("Guía sin material del tema", f"«{g['titulo']}»: las fuentes de hoy no hablan del tema; queda para otra vuelta.")
            return
        control = gemini.gemini(_prompt("verificar.md"), "NOTA:\n" + json.dumps(nota, ensure_ascii=False) + "\n\nFUENTES:\n" + "\n\n".join(textos), temperatura=0.1)
        nota["slug"] = "guia-" + g["slug"]
        oficiales = [{"nombre": "Norma oficial", "url": r["url"], "titulo": g["titulo"]} for r in g.get("oficial") or []]
        fila = self.armar_fila({"seccion": g["seccion"], "tema": "guía: " + g["titulo"]}, items + [dict(x, tipo="oficial", fuente=x["nombre"]) for x in oficiales], nota, control, set())
        fila["slug"], fila["tipo"] = "guia-" + g["slug"], "guia"
        if claves and not trata(f"{nota.get('titulo', '')} {nota.get('encorto', '')}"):
            fila["estado"], fila["verificada"] = "revision", False
            fila["motivo_revision"] = (f"🔴 1 dato para chequear antes de publicar\n1) La guía salió sobre otro tema: se pidió «{g['titulo']}» "
                                       f"y el texto no lo trata. Borrala o reescribila — no publicar así.")
        fila["fuentes"] = [{"nombre": it["fuente"], "url": it["url"], "titulo": it["titulo"]} for it in items] + oficiales
        if fila["slug"] in getattr(self, "guias_a_rehacer", set()) and fila["estado"] != "publicada":
            # reescritura de una guía que ya está publicada: si la nueva no pasó el control, queda la anterior (no se pierde la página)
            util.avisar("Guía para rehacer: la versión nueva no pasó el control", f"«{g['titulo']}»: sigue la anterior; se reintenta en otra vuelta. "
                        + str(fila.get("motivo_revision") or "")[:600])
            return
        self.guias.append(fila)
        (self.publicadas if fila["estado"] == "publicada" else self.revision).append(fila)
        if self.activo and self.db:
            self.db.upsert("notas", [fila], "slug")

    def vigilar_ignacio(self):
        """Revisa las notas de los blogs de confianza que usamos en los últimos días. Si la borraron o cambiaron algún
        número, nuestra nota sale de la portada y queda en revisión con el motivo claro; si solo cambió la redacción, avisa."""
        if not self.db:
            return
        import difflib
        desde = (util.ahora() - timedelta(days=int(self.cfg.get("dias_vigilancia", 4)))).isoformat()
        lista = ",".join('"' + f.replace('"', "") + '"' for f in sorted(self.confiables))
        try:
            filas = self.db.select("radar", {"select": "url,titulo,texto,nota,fuente", "fuente": f"in.({lista})", "usado": "eq.true",
                                             "nota": "not.is.null", "visto": f"gte.{desde}", "limit": "300"})
        except gemini.SinTiempo:
            raise
        except Exception as e:  # noqa
            util.log("No pude leer el radar para vigilar los blogs de confianza:", util.ocultar(str(e)))
            return
        def a_revision(slug, texto):
            if not self.activo:
                return
            try:
                self.db.update("notas", {"slug": f"eq.{slug}"}, {"estado": "revision", "motivo_revision": texto[:1500]})
                self.vencimientos_cambio = True  # fuerza que el sitio se vuelva a armar sin la nota
            except Exception as e:  # noqa
                util.log("No pude pasar a revisión", slug, util.ocultar(str(e)))
        for f in filas:
            antes = f.get("texto") or ""
            quien = f.get("fuente") or "El blog"
            if antes.startswith("__BORRADA__") or len(antes) < 300:
                continue
            codigo = fuentes.estado(f["url"])
            if codigo in (404, 410):
                self.alertas.append({"titulo": f["titulo"], "nota": f["nota"], "url": f["url"], "que": f"{quien} BORRÓ la publicación (nuestra nota pasó a revisión)"})
                a_revision(f["nota"], f"🔴 1 dato para chequear antes de publicar\n1) {quien} borró la publicación en la que se basa esta nota: confirmá si la novedad sigue vigente; si no, borrá la nota — {f['url']}")
                if self.activo:
                    self.db.update("radar", {"url": f"eq.{f['url']}"}, {"texto": "__BORRADA__" + antes[:5000]})
                continue
            ahora, _ = fuentes.detalle(f["url"], largo=6000)
            if not ahora:
                continue
            norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
            a_, b_ = norm(antes), norm(ahora)
            parecido = difflib.SequenceMatcher(None, a_, b_, autojunk=False).ratio()
            na, nb = set(re.findall(r"\d[\d.,%]*", a_)), set(re.findall(r"\d[\d.,%]*", b_))
            negacion = a_.count("no remunerativ") != b_.count("no remunerativ")
            if a_ != b_ and (parecido < float(self.cfg.get("umbral_edicion", 0.99)) or na != nb or negacion):
                grave = na != nb or negacion
                self.alertas.append({"titulo": f["titulo"], "nota": f["nota"], "url": f["url"],
                                     "que": f"{quien} EDITÓ la publicación" + (" (cambió algún número)" if na != nb else "") + (" (cambió remunerativo/no remunerativo)" if negacion else "")
                                     + f" · coincide {parecido:.1%}" + (" · nuestra nota pasó a revisión" if grave else "")})
                if grave:
                    det = []
                    if na - nb:
                        det.append("ya no dice: " + ", ".join(sorted(na - nb)[:6]))
                    if nb - na:
                        det.append("ahora dice: " + ", ".join(sorted(nb - na)[:6]))
                    if negacion:
                        det.append("cambió lo de remunerativo / no remunerativo")
                    a_revision(f["nota"], f"🔴 1 dato para chequear antes de publicar\n1) {quien} corrigió la publicación en la que se basa esta nota ({'; '.join(det)}): revisá esos datos en nuestra nota — {f['url']}")
                if self.activo:
                    self.db.update("radar", {"url": f"eq.{f['url']}"}, {"texto": ahora[:6000]})

    def marcar(self, urls, tema, slug):
        if self.activo and self.db and urls:
            for u in urls:
                self.db.update("radar", {"url": f"eq.{u}"}, {"usado": True, "tema": tema, "nota": slug})

    def republicar_web(self):
        repo, token = os.getenv("GITHUB_REPOSITORY"), util.secreto("GITHUB_TOKEN")
        if not repo or not token:
            return
        r = util.pedir("POST", f"https://api.github.com/repos/{repo}/actions/workflows/web.yml/dispatches",
                       headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                       json={"ref": os.getenv("GITHUB_REF_NAME", "main")}, intentos=2, timeout=30)
        util.log("Web: pedido de republicación", getattr(r, "status_code", "?"))

    def informe(self):
        md = [f"# Fábrica de notas · {'ACTIVO' if self.activo else 'ENSAYO (no se publicó nada)'}\n"]
        def nota_md(n):
            cuerpo = []
            for b in n["cuerpo"]:
                if "h" in b:
                    cuerpo.append(f"**{b['h']}**")
                elif "p" in b:
                    cuerpo.append(b["p"])
                elif "tabla" in b:
                    t = b["tabla"]
                    cuerpo.append("| " + " | ".join(t[0]) + " |\n|" + "---|" * len(t[0]) + "\n" +
                                  "\n".join("| " + " | ".join(f) + " |" for f in t[1:]))
            fuentes_txt = ", ".join(f"[{f['nombre']}]({f['url']})" for f in n["fuentes"])
            return (f"### {n['titulo']}\n*{n['antetitulo']}* · sección {n['seccion']}"
                    + (f" · actualiza `{n['actualiza']}`" if n.get("actualiza") else "") + "\n\n"
                    f"> **En corto:** {n['encorto']}\n\n" + "\n\n".join(cuerpo) +
                    f"\n\n*Fuente:* {n['fuente']} · *Leído en:* {fuentes_txt}\n"
                    + (f"\n**Motivo de revisión:** {n['motivo_revision']}\n" if n.get("motivo_revision") else "") + "\n---\n")
        md.append(f"## ✅ Se publicarían solas ({len(self.publicadas)})\n" if not self.activo else f"## ✅ Publicadas ({len(self.publicadas)})\n")
        md += [nota_md(n) for n in self.publicadas] or ["Ninguna.\n"]
        md.append(f"## 🟡 Para revisar ({len(self.revision)})\n")
        md += [nota_md(n) for n in self.revision] or ["Ninguna.\n"]
        md.append(f"## 📊 Convenios actualizados ({len(self.convenios_act)})\n" + "".join(f"- {c['nombre']}: {c['periodo']}\n" for c in self.convenios_act))
        md.append(f"## 🟡 Convenios para revisar ({len(self.convenios_rev)})\n" + "".join(f"- {c['nombre']}: {c['periodo']} — {c['motivo']}\n" for c in self.convenios_rev))
        for c in self.convenios_act + self.convenios_rev:
            t = (c["datos"].get("escala") or {}).get("tabla") or []
            if t:
                md.append(f"**Escala {c['nombre']} {c['periodo']}**\n\n| " + " | ".join(t[0]) + " |\n|" + "---|" * len(t[0]) + "\n" + "\n".join("| " + " | ".join(f) + " |" for f in t[1:]) + "\n")
        md.append(f"## 🚨 Blogs de confianza que editaron o borraron ({len(self.alertas)})\n" + "".join(f"- {a['que']}: [{a['titulo']}]({a['url']}) → nuestra nota `{a['nota']}`\n" for a in self.alertas))
        md.append(f"## 📊 Datos del día sin confirmar ({len(self.datos_obs)})\n" + ("".join(f"- {t}: {o}\n" for t, o in self.datos_obs) or "Ninguno.\n"))
        md.append(f"## 📝 Publicadas con observaciones menores, no hace falta revisar ({len(self.observaciones)})\n" + "".join(f"- {t}: {o}\n" for t, o in self.observaciones))
        md.append(f"**Pedidos a Gemini en esta vuelta:** {gemini.PEDIDOS[0]} (datos del día: {getattr(self, 'pedidos_datos', 0)})\n")
        md.append("## 📅 Vencimientos y datos del día\n" + ("\n".join(f"- {x}" for x in self.vencimientos_info) or "Sin cambios (ya actualizados hoy).") + "\n")
        md.append(f"## 📘 Guías\n{self.guias_info or 'Sin datos.'}\n")
        md.append(f"## ⏳ Esperando segunda fuente ({len(self.esperando)})\n" + "".join(f"- {t} ({d})\n" for t, d in self.esperando))
        md.append(f"## 🚫 Descartadas ({len(self.descartes)})\n" + "".join(f"- {t}: {d}\n" for t, d in self.descartes))
        util.resumen("\n".join(md))


def main():
    db = None
    if util.secreto("SUPABASE_URL") and util.secreto("SUPABASE_SECRET_KEY"):
        from .db import DB
        db = DB()
    Fabrica(db).correr()


if __name__ == "__main__":
    main()
