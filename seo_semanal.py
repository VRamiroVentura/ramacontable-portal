"""Informe SEO semanal de Ramacontable (lo corre .github/workflows/seo-semanal.yml los lunes).

1. Revisa el sitio recién armado con auditar.py (títulos, descripciones, enlaces, sitemap, páginas flacas, texto propio...).
2. Mide la velocidad en celular de algunas páginas clave con PageSpeed Insights de Google (gratis, sin clave;
   si Google no responde, el informe sale igual sin esa parte).
3. Compara con la semana anterior (seo/historial.json) y manda un mail con el resumen a mail_aviso de config.json.

Nunca toca el sitio: solo lee y avisa.
"""
import datetime
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

import auditar

RAIZ = os.path.dirname(os.path.abspath(__file__))
HISTORIAL = os.path.join(RAIZ, "seo", "historial.json")
PAGINAS_VELOCIDAD = ["", "aguinaldo.html", "monotributo-explicado-facil.html", "escala-comercio.html"]


def config():
    try:
        return json.load(open(os.path.join(RAIZ, "config.json"), encoding="utf-8"))
    except Exception:
        return {}


def _abrir(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "ramacontable-seo"})
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())
    except ssl.SSLError:
        import certifi
        return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where()))


def velocidad(base):
    """{página: {nota, lcp, cls, inp_real}} con PageSpeed Insights (celular). Lo que falle queda afuera."""
    out = {}
    for p in PAGINAS_VELOCIDAD:
        q = {"url": base + p, "strategy": "mobile", "category": "performance"}
        if os.environ.get("PAGESPEED_KEY"):   # opcional (secreto de GitHub): sin clave Google limita mucho las consultas
            q["key"] = os.environ["PAGESPEED_KEY"]
        url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + urllib.parse.urlencode(q)
        d = None
        for intento in range(3):
            try:
                d = json.load(_abrir(url, 120))
                break
            except Exception as ex:
                detalle = ""
                if hasattr(ex, "read"):
                    try:
                        detalle = ex.read().decode("utf-8", "replace")[:200]
                    except Exception:
                        pass
                print(f"Aviso: PageSpeed no respondió para /{p} (intento {intento + 1}):", ex, detalle)
                time.sleep(20 * (intento + 1))
        if not d:
            continue
        lh = d.get("lighthouseResult") or {}
        aud = lh.get("audits") or {}
        campo = ((d.get("loadingExperience") or {}).get("metrics") or {})
        out[p or "portada"] = {
            "nota": round(((lh.get("categories") or {}).get("performance") or {}).get("score", 0) * 100),
            "lcp": (aud.get("largest-contentful-paint") or {}).get("displayValue", ""),
            "cls": (aud.get("cumulative-layout-shift") or {}).get("displayValue", ""),
            "inp_real": (campo.get("INTERACTION_TO_NEXT_PAINT") or {}).get("category", ""),
        }
    return out


def _en_ventana(hoy_md, desde, hasta):
    return desde <= hoy_md <= hasta if desde <= hasta else (hoy_md >= desde or hoy_md <= hasta)


def calendario_guias():
    """Avisos de guías para actualizar o crear (guias/calendario.json) y reescrituras automáticas de los próximos 15 días."""
    hoy = datetime.date.today()
    md = hoy.strftime("%m-%d")
    out = []
    try:
        cal = json.load(open(os.path.join(RAIZ, "guias", "calendario.json"), encoding="utf-8")).get("avisos") or []
    except Exception:
        cal = []
    activos = [a for a in cal if _en_ventana(md, a["desde"], a["hasta"])]
    if activos:
        out.append("GUÍAS PARA ACTUALIZAR O CREAR (calendario)")
        for a in activos:
            out.append(f"{'✏️' if a['tipo'] == 'actualizar' else '🆕'} {a['guia']} (hasta el {a['hasta'][3:]}/{a['hasta'][:2]}): {a['que']}")
        out.append("")
    try:
        cat = json.load(open(os.path.join(RAIZ, "guias", "catalogo.json"), encoding="utf-8"))
    except Exception:
        cat = []
    prox = []
    for g in cat:
        for f in g.get("rehacer_anual") or []:
            try:
                d = hoy.replace(month=int(f[:2]), day=int(f[3:]))
            except ValueError:
                continue
            if d < hoy:
                d = d.replace(year=d.year + 1)
            if (d - hoy).days <= 15:
                prox.append(f"🔄 «{g['titulo']}»: la fábrica la reescribe desde el {d.day}/{d.month} (si la nueva no pasa el control, queda la anterior).")
    if prox:
        out += ["GUÍAS PROFESIONALES QUE SE ACTUALIZAN SOLAS EN LOS PRÓXIMOS 15 DÍAS"] + prox + [""]
    return out


def severidades(datos):
    s = {"🔴": 0, "🟠": 0, "🟡": 0}
    for cod, n in datos.get("conteo", {}).items():
        s[datos["nombres"][cod][0]] += n
    return s


def flecha(ahora, antes):
    if antes is None:
        return ""
    d = ahora - antes
    return " (igual que la semana pasada)" if d == 0 else (f" ({d:+d} vs. la semana pasada)")


def main():
    cfg = config()
    base = (cfg.get("sitio_url") or "https://ramacontable.com.ar/").rstrip("/") + "/"
    informe, datos = auditar.auditar()
    if not datos:
        print(informe)
        return 0
    sev = severidades(datos)
    vel = velocidad(base) if os.environ.get("RC_SIN_VELOCIDAD") != "1" else {}
    try:
        historial = json.load(open(HISTORIAL, encoding="utf-8"))
    except Exception:
        historial = []
    hoy = datetime.date.today().isoformat()
    previas = [h for h in historial if h.get("fecha") != hoy]
    antes = previas[-1] if previas else {}
    actual = {"fecha": hoy, "paginas": datos["paginas"], "indexables": datos["indexables"], "severidades": sev,
              "conteo": datos["conteo"], "unicidad": datos["unicidad"], "velocidad": vel}

    lineas = [f"Informe SEO semanal de {base} — {hoy}", "",
              f"Páginas: {datos['paginas']} ({datos['indexables']} que Google puede indexar){flecha(datos['indexables'], antes.get('indexables'))}", "",
              "PROBLEMAS",
              f"🔴 Graves: {sev['🔴']}{flecha(sev['🔴'], (antes.get('severidades') or {}).get('🔴'))}",
              f"🟠 Medios: {sev['🟠']}{flecha(sev['🟠'], (antes.get('severidades') or {}).get('🟠'))}",
              f"🟡 Menores: {sev['🟡']}{flecha(sev['🟡'], (antes.get('severidades') or {}).get('🟡'))}", ""]
    nuevos = [c for c in datos["conteo"] if c not in (antes.get("conteo") or {})] if antes else []
    if nuevos:
        lineas.append("NUEVO ESTA SEMANA")
        for c in nuevos:
            icono, nombre = datos["nombres"][c]
            lineas.append(f"{icono} {nombre}: {datos['conteo'][c]}")
            lineas += [f"   - {p}" + (f" — {d}" if d else "") for p, d in datos["detalle"][c][:5]]
        lineas.append("")
    graves = [c for c in datos["conteo"] if datos["nombres"][c][0] in ("🔴", "🟠")]
    if graves:
        lineas.append("PARA REVISAR (graves y medios)")
        for c in sorted(graves, key=lambda c: datos["nombres"][c][0] != "🔴"):
            icono, nombre = datos["nombres"][c]
            lineas.append(f"{icono} {nombre}: {datos['conteo'][c]}")
            lineas += [f"   - {p}" + (f" — {d}" if d else "") for p, d in datos["detalle"][c][:3]]
        lineas.append("")
    if datos["unicidad"]:
        lineas.append("TEXTO PROPIO EN PÁGINAS AUTOMÁTICAS (Google penaliza las casi iguales; la meta es 40% o más)")
        for k, v in datos["unicidad"].items():
            prev = ((antes.get("unicidad") or {}).get(k) or {}).get("promedio")
            lineas.append(f"- {k}: {v['promedio']}% en promedio{flecha(v['promedio'], prev)}, {v['flacas']} de {v['paginas']} por debajo")
        lineas.append("")
    if vel:
        lineas.append("VELOCIDAD EN CELULAR (PageSpeed de Google, nota de 0 a 100: 90 o más es bueno)")
        for p, v in vel.items():
            prev = ((antes.get("velocidad") or {}).get(p) or {}).get("nota")
            lineas.append(f"- {p}: {v['nota']}{flecha(v['nota'], prev)} · carga del contenido principal {v['lcp']} · saltos de diseño {v['cls']}"
                          + (f" · respuesta real de los usuarios: {v['inp_real']}" if v["inp_real"] else ""))
        lineas.append("")
    else:
        lineas += ["Velocidad: PageSpeed no respondió esta semana (se vuelve a intentar el lunes que viene).", ""]
    lineas += calendario_guias()
    lineas += ["El detalle completo está en Actions → «Informe SEO semanal» → la última ejecución.",
               "Para ver clics, impresiones y posiciones: Search Console."]
    texto = "\n".join(lineas)
    print(texto)

    historial = [h for h in historial if h.get("fecha") != hoy] + [actual]
    os.makedirs(os.path.dirname(HISTORIAL), exist_ok=True)
    json.dump(historial[-60:], open(HISTORIAL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write("```\n" + texto + "\n```\n\n" + informe + "\n")

    usuario, clave, destino = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", ""), cfg.get("mail_aviso", "")
    if not (usuario and clave and destino) or os.environ.get("RC_SEO_PRUEBA") == "1":
        print("No mando el mail (modo prueba o faltan SMTP_USER / SMTP_PASS / mail_aviso).")
        return 0
    msg = MIMEText(texto, "plain", "utf-8")
    msg["Subject"] = f"📈 Informe SEO semanal · 🔴 {sev['🔴']} · 🟠 {sev['🟠']} · 🟡 {sev['🟡']}"
    msg["From"], msg["To"] = usuario, destino
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(usuario, clave)
            s.send_message(msg)
        print("Mail enviado.")
    except Exception as ex:
        print("Aviso: no pude mandar el mail:", ex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
