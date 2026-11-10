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

FUENTES_EXTRA = [{"nombre": "ARBA", "tipo": "oficial", "url": "https://web.arba.gov.ar/noticias"}, {"nombre": "Tributum", "tipo": "portal", "url": "https://tributum.news/feed/"}, {"nombre": "Estudio Vilaplana", "tipo": "portal", "url": "https://www.estudiovilaplana.com.ar/feed/"}, {"nombre": "iProfesional Impuestos", "tipo": "apoyo", "url": "https://www.iprofesional.com/rss/impuestos.xml", "filtro": ["arca", "afip", "anses", "monotribut", "ganancias", "iva", "bienes personales", "ingresos brutos", "arba", "agip", "impuesto", "boletin oficial", "resolucion general", "decreto", "convenio", "paritaria", "escala", "salari", "sueldo", "aguinaldo", "indemniz", "aportes", "contribuciones", "seguridad social", "art ", "feriado", "vencimiento", "bcra", "comunicacion a", "reforma laboral"]}, {"nombre": "Calcular Sueldo", "tipo": "apoyo", "url": "https://calcularsueldo.com.ar/feed/", "filtro": ["arca", "afip", "anses", "monotribut", "ganancias", "iva", "bienes personales", "ingresos brutos", "arba", "agip", "impuesto", "boletin oficial", "resolucion general", "decreto", "convenio", "paritaria", "escala", "salari", "sueldo", "aguinaldo", "indemniz", "aportes", "contribuciones", "seguridad social", "art ", "feriado", "vencimiento", "bcra", "comunicacion a", "reforma laboral"]}, {"nombre": "Econoblog", "tipo": "apoyo", "url": "https://www.econoblog.com.ar/feed/", "filtro": ["arca", "afip", "anses", "monotribut", "ganancias", "iva", "bienes personales", "ingresos brutos", "arba", "agip", "impuesto", "boletin oficial", "resolucion general", "decreto", "convenio", "paritaria", "escala", "salari", "sueldo", "aguinaldo", "indemniz", "aportes", "contribuciones", "seguridad social", "art ", "feriado", "vencimiento", "bcra", "comunicacion a", "reforma laboral"]}]

CONFIABLE = "Ignacio Online"  # lo que publica Ignacio se toma como correcto (pedido de Ramiro); se vigila si después lo edita o borra


def _prompt(nombre):
    return (util.RAIZ / "prompts" / nombre).read_text(encoding="utf-8")


def _slug(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80] or "nota"


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


class Fabrica:
    def __init__(self, db=None):
        self.cfg = util.config()
        self.activo = self.cfg.get("modo") == "activo"
        self.db = db
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
        lista = [f for f in lista if "boletinoficial.gob.ar" not in f.get("url", "") or self.cfg.get("leer_boletin")]  # no responde a GitHub; Tributum trae el sumario
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
        ok = bool(control.get("ok")) and not nuevo.get("dudas") and not control.get("agrega_ejemplos")
        if not ok and any(CONFIABLE in t for t in textos):
            self.observaciones.append((f"Escala {c['nombre']}", "; ".join(list(control.get("problemas") or []) + list(nuevo.get("dudas") or []))[:400]))
            ok = True
        motivo = "; ".join(list(control.get("problemas") or []) + [f"Duda: {d}" for d in (nuevo.get("dudas") or [])])[:600]
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
                url = plantilla.format(mes=nombre_mes, anio=anio)
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
            if len(vistos) < minimo and CONFIABLE not in vistos:
                util.avisar(f"Vencimientos de {nombre_mes}", f"solo encontré {len(vistos)} fuente(s); queda la agenda anterior")
                continue
            try:
                r = gemini.gemini(_prompt("vencimientos.md"), f"MES: {nombre_mes} {anio}\n\nFUENTES:\n" + "\n\n".join(textos), temperatura=0.1)
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar(f"No pude armar los vencimientos de {nombre_mes}", str(e))
                continue
            def confirmados(lista, campos):
                salida = []
                for x in lista if isinstance(lista, list) else []:
                    if not isinstance(x, dict) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(x.get("fecha", ""))):
                        continue
                    n = len({str(f) for f in (x.get("fuentes") or [])})
                    de_ignacio = CONFIABLE in [str(f) for f in (x.get("fuentes") or [])]
                    if (n >= minimo or de_ignacio) and not x.get("estimado") and str(x["fecha"]).startswith(clave):
                        salida.append({c: str(x.get(c) or "")[:160] for c in campos} | {"fuentes": n})
                return sorted(salida, key=lambda x: x["fecha"])
            venc = confirmados(r.get("vencimientos"), ("fecha", "concepto", "detalle"))
            fer = confirmados(r.get("feriados"), ("fecha", "nombre", "tipo", "norma"))
            util.log(f"Vencimientos {clave}: {len(venc)} confirmados, {len(fer)} feriados ({len(vistos)} fuentes)")
            self.vencimientos_info.append(f"{nombre_mes} {anio}: {len(venc)} vencimientos y {len(fer)} feriados confirmados por {minimo}+ fuentes ({', '.join(sorted(vistos))})")
            if self.activo and venc:
                self.db.upsert("vencimientos", [{"mes": clave, "items": venc, "feriados": fer, "fuentes": sorted(vistos),
                                                 "actualizado": util.ahora().isoformat()}], "mes")
                self.vencimientos_cambio = True

    def armar_fila(self, grupo, items, nota, control, usados):
        base = _slug(nota.get("slug") or nota.get("titulo"))
        slug, k = base, 2
        while slug in usados:
            slug, k = f"{base}-{k}", k + 1
        usados.add(slug)
        problemas = list(control.get("problemas") or []) + [f"Duda: {d}" for d in (nota.get("dudas") or [])]
        if control.get("agrega_ejemplos"):
            problemas.append("Agrega ejemplos prácticos que no están en las fuentes.")
        ok = bool(control.get("ok")) and not nota.get("dudas") and not control.get("agrega_ejemplos")
        if not ok and any(it.get("fuente") == CONFIABLE for it in items):
            # viene de Ignacio: se publica igual y las observaciones quedan en el mail para mirarlas
            self.observaciones.append((nota.get("titulo", ""), "; ".join(problemas)[:400]))
            ok = True
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
                          if isinstance(q, dict) and q.get("p") and q.get("r")][:5], "motivo_revision": "; ".join(problemas)[:600] if not ok else None,
        }

    def correr(self):
        util.log("Modo:", "ACTIVO (publica)" if self.activo else "ENSAYO (no publica nada)")
        if self.activo:
            self.sembrar()
        recientes = self.notas_recientes()
        previos = self.radar_previo()
        nuevos = [it for it in self.leer_fuentes() if it["url"] not in previos]
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
            if g.get("clase") == "propia" and not oficial and len(portales) < int(self.cfg.get("portales_para_nota_propia", 3)):
                self.descartes.append((g.get("tema"), "nota propia de un portal (investigación u opinión): no se replica"))
                self.marcar(urls, g.get("tema"), None)
                continue
            # Regla de fuentes: se publica si hay fuente oficial, si lo trae Ignacio Online, si lo publicaron
            # al menos 2 portales, o si la nota del portal cita la fuente oficial y la podemos leer para chequear.
            # Los blogs de "apoyo" (generalistas) nunca arrancan una nota solos: solo confirman un tema
            # que ya trae una fuente oficial o un blog contable principal.
            principales = {m["fuente"] for m in miembros if m["tipo"] == "portal"}
            if not oficial and not principales:
                self.esperando.append((g.get("tema"), f"solo en blogs de apoyo ({', '.join(sorted(portales))}): espera un blog contable o la fuente oficial"))
                continue
            if not oficial and CONFIABLE not in portales and len(portales) < int(self.cfg.get("portales_minimos", 2)):
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
                    if mi["fuente"] == CONFIABLE:
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
        """Guías, escalas, vencimientos y vigilancia, en ese orden. Si se acaba el tiempo, lo que falta queda
        para la próxima vuelta y la vuelta cierra igual (publica la web, manda el mail y deja el resumen)."""
        try:
            for nombre, tarea in [("datos al día", self.actualizar_respuestas), ("guías", self.escribir_guias), ("escalas oficiales", self.revisar_escalas_oficiales),
                                  ("vencimientos", self.actualizar_vencimientos), ("vigilancia de Ignacio", self.vigilar_ignacio)]:
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
                filas = self.db.select("notas", {"select": "slug,fecha", "tipo": "eq.guia", "limit": "1000"})
            except gemini.SinTiempo:
                raise
            except Exception as e:  # noqa
                util.avisar("No pude leer las guías (¿falta correr esquema.sql en Supabase?)", str(e))
                return
            existentes = {f["slug"] for f in filas}
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
        control = gemini.gemini(_prompt("verificar.md"), "NOTA:\n" + json.dumps(nota, ensure_ascii=False) + "\n\nFUENTES:\n" + "\n\n".join(textos), temperatura=0.1)
        nota["slug"] = "guia-" + g["slug"]
        oficiales = [{"nombre": "Norma oficial", "url": r["url"], "titulo": g["titulo"]} for r in g.get("oficial") or []]
        fila = self.armar_fila({"seccion": g["seccion"], "tema": "guía: " + g["titulo"]}, items + [dict(x, tipo="oficial", fuente=x["nombre"]) for x in oficiales], nota, control, set())
        fila["slug"], fila["tipo"] = "guia-" + g["slug"], "guia"
        fila["fuentes"] = [{"nombre": it["fuente"], "url": it["url"], "titulo": it["titulo"]} for it in items] + oficiales
        self.guias.append(fila)
        (self.publicadas if fila["estado"] == "publicada" else self.revision).append(fila)
        if self.activo and self.db:
            self.db.upsert("notas", [fila], "slug")

    def vigilar_ignacio(self):
        """Revisa las notas de Ignacio que usamos en los últimos días: avisa si las editó o las borró."""
        if not self.db:
            return
        import difflib
        desde = (util.ahora() - timedelta(days=int(self.cfg.get("dias_vigilancia", 4)))).isoformat()
        try:
            filas = self.db.select("radar", {"select": "url,titulo,texto,nota", "fuente": f"eq.{CONFIABLE}", "usado": "eq.true",
                                             "nota": "not.is.null", "visto": f"gte.{desde}", "limit": "200"})
        except gemini.SinTiempo:
            raise
        except Exception as e:  # noqa
            util.log("No pude leer el radar para vigilar a Ignacio:", util.ocultar(str(e)))
            return
        for f in filas:
            antes = f.get("texto") or ""
            if antes.startswith("__BORRADA__") or len(antes) < 300:
                continue
            codigo = fuentes.estado(f["url"])
            if codigo in (404, 410):
                self.alertas.append({"titulo": f["titulo"], "nota": f["nota"], "url": f["url"], "que": "Ignacio BORRÓ la publicación"})
                if self.activo:
                    self.db.update("radar", {"url": f"eq.{f['url']}"}, {"texto": "__BORRADA__" + antes[:5000]})
                continue
            ahora, _ = fuentes.detalle(f["url"], largo=6000)
            if not ahora:
                continue
            norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
            a_, b_ = norm(antes), norm(ahora)
            parecido = difflib.SequenceMatcher(None, a_, b_, autojunk=False).ratio()
            numeros = set(re.findall(r"\d[\d.,%]*", a_)) != set(re.findall(r"\d[\d.,%]*", b_))
            negacion = a_.count("no remunerativ") != b_.count("no remunerativ")
            if a_ != b_ and (parecido < float(self.cfg.get("umbral_edicion", 0.99)) or numeros or negacion):
                self.alertas.append({"titulo": f["titulo"], "nota": f["nota"], "url": f["url"],
                                     "que": "Ignacio EDITÓ la publicación" + (" (cambió algún número)" if numeros else "") + (" (cambió remunerativo/no remunerativo)" if negacion else "") + f" · coincide {parecido:.1%}"})
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
        md.append(f"## 🚨 Ignacio editó o borró ({len(self.alertas)})\n" + "".join(f"- {a['que']}: [{a['titulo']}]({a['url']}) → nuestra nota `{a['nota']}`\n" for a in self.alertas))
        md.append(f"## 📊 Datos del día sin confirmar ({len(self.datos_obs)})\n" + ("".join(f"- {t}: {o}\n" for t, o in self.datos_obs) or "Ninguno.\n"))
        md.append(f"## 📝 Publicadas con observaciones por venir de Ignacio ({len(self.observaciones)})\n" + "".join(f"- {t}: {o}\n" for t, o in self.observaciones))
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
