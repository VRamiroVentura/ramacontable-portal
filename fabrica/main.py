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
                except Exception as e:  # noqa
                    util.avisar("No pude guardar los convenios (¿falta correr esquema.sql en Supabase?)", str(e))

    # ---------- pasos ----------
    def leer_fuentes(self):
        items = []
        for f in self.cfg.get("fuentes", []):
            try:
                nuevos = fuentes.leer(f)
                util.log(f"{f['nombre']}: {len(nuevos)} novedades")
                items += nuevos
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

    def actualizar_convenio(self, grupo, nota_slug):
        c = self.convenios.get(grupo.get("convenio"))
        if not c:
            return
        actual = {k: c.get(k) for k in ("nombre", "cct", "escala", "novedades", "calculo", "nr", "recibo", "preguntas", "fuente")}
        pedido = "PÁGINA ACTUAL DEL CONVENIO:\n" + json.dumps(actual, ensure_ascii=False) + "\n\nFUENTES DEL NUEVO ACUERDO:\n" + "\n\n".join(self._textos)
        nuevo = gemini.gemini(_prompt("convenio.md"), pedido, temperatura=0.3)
        control = gemini.gemini(_prompt("verificar.md"), "NOTA:\n" + json.dumps(nuevo, ensure_ascii=False) + "\n\nFUENTES:\n" + "\n\n".join(self._textos), temperatura=0.1)
        esc = nuevo.get("escala") if isinstance(nuevo.get("escala"), dict) else None
        if esc:
            tabla = esc.get("tabla") if isinstance(esc.get("tabla"), list) else []
            esc = {"periodo": str(esc.get("periodo") or "")[:80], "vigencia": str(esc.get("vigencia") or "")[:120],
                   "tabla": [[str(x)[:80] for x in f][:10] for f in tabla[:80] if isinstance(f, list)], "aclaraciones": str(esc.get("aclaraciones") or "")[:800]}
        datos = {"escala": esc or c.get("escala"), "novedades": _bloques_ok(nuevo.get("novedades")), "calculo": _bloques_ok(nuevo.get("calculo")) or c.get("calculo") or [],
                 "nr": _bloques_ok(nuevo.get("nr")) or c.get("nr") or [], "recibo": _bloques_ok(nuevo.get("recibo")) or c.get("recibo") or [],
                 "preguntas": [{"p": str(q.get("p"))[:200], "r": str(q.get("r"))[:500]} for q in (nuevo.get("preguntas") or []) if isinstance(q, dict) and q.get("p") and q.get("r")][:6],
                 "fuente": str(nuevo.get("fuente") or c.get("fuente") or "")[:300]}
        hist = list(c.get("historial") or [])
        per = str(nuevo.get("periodo_historial") or (esc or {}).get("periodo") or grupo.get("tema"))[:80]
        if not any(h.get("periodo") == per for h in hist):
            hist.append({"periodo": per, "fecha": util.ahora().date().isoformat(), "nota": nota_slug})
        ok = bool(control.get("ok")) and not nuevo.get("dudas") and not control.get("agrega_ejemplos")
        motivo = "; ".join(list(control.get("problemas") or []) + [f"Duda: {d}" for d in (nuevo.get("dudas") or [])])[:600]
        registro = {"slug": c["slug"], "nombre": c["nombre"], "periodo": per, "motivo": motivo, "datos": datos}
        (self.convenios_act if ok else self.convenios_rev).append(registro)
        if self.activo and self.db:
            if ok:
                self.db.update("convenios", {"slug": f"eq.{c['slug']}"}, dict(datos, historial=hist, propuesta=None, motivo_propuesta=None))
            else:
                self.db.update("convenios", {"slug": f"eq.{c['slug']}"}, {"propuesta": dict(datos, historial=hist), "motivo_propuesta": motivo})

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
        oficial = any(it["tipo"] == "oficial" for it in items)
        return {
            "slug": slug, "fecha": util.ahora().date().isoformat(), "seccion": grupo.get("seccion") if grupo.get("seccion") in ("sueldos", "impuestos", "profesion", "economia") else "impuestos",
            "antetitulo": str(nota.get("antetitulo", ""))[:120], "titulo": str(nota.get("titulo", ""))[:160],
            "dato": (str(nota["dato"])[:40] if nota.get("dato") else None), "encorto": str(nota.get("encorto", ""))[:600],
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
            self.escribir_guias()
            self.cierre()
            return
        grupos = self.agrupar(items, recientes)
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
            if hechas >= self.cfg.get("max_notas_por_vuelta", 6):
                self.esperando.append((g.get("tema"), "queda para la próxima vuelta"))
                continue
            try:
                nota, control = self.redactar(g, miembros, recientes)
                fila = self.armar_fila(g, miembros, nota, control, usados_slug)
            except Exception as e:  # noqa
                util.avisar(f"No pude escribir «{g.get('tema')}»", str(e))
                continue
            hechas += 1
            (self.publicadas if fila["estado"] == "publicada" else self.revision).append(fila)
            if self.activo and self.db:
                self.db.upsert("notas", [fila], "slug")
                self.marcar(urls, g.get("tema"), fila["slug"])
            if g.get("escala") and fila.get("convenio"):
                try:
                    self.actualizar_convenio(g, fila["slug"] if fila["estado"] == "publicada" else None)
                except Exception as e:  # noqa
                    util.avisar(f"No pude actualizar el convenio {fila['convenio']}", str(e))
        self.escribir_guias()
        self.cierre()

    def cierre(self):
        if self.activo:
            if self.publicadas or self.convenios_act:
                self.republicar_web()
            mail.avisar(self.publicadas + self.revision, self.cfg.get("sitio_url", ""), self.cfg.get("mail_aviso"), self.convenios_act, self.convenios_rev)
        self.informe()

    # ---------- guías ----------
    def escribir_guias(self):
        """Escribe de a poco las guías del catálogo que todavía no existen (máximo guias_por_dia)."""
        try:
            catalogo = json.loads((util.RAIZ / "guias" / "catalogo.json").read_text(encoding="utf-8"))
        except Exception:  # noqa
            return
        por_dia = int(self.cfg.get("guias_por_dia", 2))
        existentes, hoy = set(), util.ahora().date().isoformat()
        if self.db:
            try:
                filas = self.db.select("notas", {"select": "slug,fecha", "tipo": "eq.guia", "limit": "1000"})
            except Exception as e:  # noqa
                util.avisar("No pude leer las guías (¿falta correr esquema.sql en Supabase?)", str(e))
                return
            existentes = {f["slug"] for f in filas}
            por_dia -= sum(1 for f in filas if str(f["fecha"]) == hoy)
        pendientes = [g for g in catalogo if "guia-" + g["slug"] not in existentes]
        for g in pendientes[:max(0, min(por_dia, int(self.cfg.get("guias_por_vuelta", 3))))]:
            try:
                self.escribir_guia(g)
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
            util.log("Guía sin fuentes, queda para otra vuelta:", g["titulo"])
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
