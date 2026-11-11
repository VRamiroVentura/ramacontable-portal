"""Newsletter de los lunes: novedades de la semana y vencimientos de los próximos días.
Se manda a quienes tildaron «Quiero recibir la newsletter» al registrarse (tabla preferencias).
Corre sola desde .github/workflows/newsletter.yml. Con RC_NEWSLETTER_PRUEBA=1 no manda nada: solo arma el mail."""
import os
import smtplib
from datetime import timedelta
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape

from . import util

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def armar(notas, vencimientos, sitio, hoy):
    """Devuelve (asunto, html). notas: publicadas de los últimos 7 días; vencimientos: de hoy a 7 días."""
    fecha = lambda iso: f"{DIAS[__import__('datetime').date.fromisoformat(iso[:10]).weekday()]} {int(iso[8:10])}"
    partes = [f"<div style='font:bold 22px Georgia,serif;color:#13271F'>Ramacontable</div>"
              f"<div style='font:13px sans-serif;color:#777;margin-bottom:18px'>Resumen de la semana · {hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}</div>"]
    if vencimientos:
        filas = "".join(f"<tr><td style='padding:6px 10px 6px 0;font:bold 14px sans-serif;color:#13271F;white-space:nowrap;vertical-align:top'>{escape(fecha(v['fecha']).capitalize())}</td>"
                        f"<td style='padding:6px 0;font:14px sans-serif;color:#333'>{escape(v.get('concepto', ''))}"
                        + (f" <span style='color:#777'>({escape(v['detalle'])})</span>" if v.get("detalle") else "") + "</td></tr>" for v in vencimientos[:25])
        partes.append("<div style='font:bold 16px Georgia,serif;color:#8A6A2E;margin:6px 0'>Vencimientos de esta semana</div>"
                      f"<table style='border-collapse:collapse;margin-bottom:8px'>{filas}</table>"
                      f"<div style='margin-bottom:22px'><a href='{sitio}herramientas.html' style='font:13px sans-serif;color:#8A6A2E'>Ver todos los vencimientos del mes</a></div>")
    if notas:
        items = "".join(f"<div style='padding:10px 0;border-bottom:1px solid #e5e5e5'>"
                        f"<a href='{sitio}nota-{escape(n['slug'])}.html' style='font:bold 16px Georgia,serif;color:#13271F;text-decoration:none'>{escape(n['titulo'])}</a>"
                        f"<div style='font:14px sans-serif;color:#444;margin-top:3px'>{escape((n.get('encorto') or '')[:220])}</div></div>" for n in notas[:12])
        partes.append(f"<div style='font:bold 16px Georgia,serif;color:#8A6A2E;margin:6px 0'>Novedades de la semana</div>{items}")
    partes.append(f"<div style='margin:22px 0 6px'><a href='{sitio}datos-al-dia.html' style='background:#8A6A2E;color:#fff;padding:9px 14px;text-decoration:none;font:bold 14px sans-serif;border-radius:3px'>Datos del día</a> "
                  f"<a href='{sitio}calculadoras.html' style='background:#13271F;color:#fff;padding:9px 14px;text-decoration:none;font:bold 14px sans-serif;border-radius:3px'>Calculadoras y planillas</a></div>"
                  f"<div style='font:12px sans-serif;color:#888;margin-top:22px;border-top:1px solid #ddd;padding-top:10px'>Recibís este mail porque lo pediste al registrarte en Ramacontable. "
                  f"Para dejar de recibirlo, entrá a <a href='{sitio}' style='color:#888'>ramacontable.com.ar</a>, abrí tu perfil y destildá la newsletter. "
                  "Información de carácter general: verificá siempre en las fuentes oficiales.</div>")
    n_v, n_n = len(vencimientos), len(notas)
    asunto = f"Ramacontable: {n_v} vencimiento{'s' if n_v != 1 else ''} esta semana y {n_n} novedad{'es' if n_n != 1 else ''}"
    return asunto, "<div style='max-width:620px;margin:0 auto;padding:10px'>" + "".join(partes) + "</div>"


def correr(db=None):
    cfg = util.config()
    sitio = (cfg.get("sitio_url") or "https://ramacontable.com.ar/").rstrip("/") + "/"
    hoy = util.ahora().date()
    prueba = os.getenv("RC_NEWSLETTER_PRUEBA") == "1"
    if db is None:
        from .db import DB
        db = DB()
    desde, hasta = (hoy - timedelta(days=7)).isoformat(), (hoy + timedelta(days=7)).isoformat()
    notas = db.select("notas", {"select": "slug,titulo,encorto,fecha,tipo", "estado": "eq.publicada", "fecha": f"gte.{desde}", "order": "fecha.desc", "limit": "40"})
    notas = [n for n in notas if n.get("tipo") != "guia"] + [n for n in notas if n.get("tipo") == "guia"]
    venc = []
    for fila in db.select("vencimientos", {"select": "mes,items"}):
        venc += [x for x in (fila.get("items") or []) if hoy.isoformat() <= str(x.get("fecha", "")) <= hasta]
    venc.sort(key=lambda x: (x["fecha"], x.get("concepto", "")))
    if not notas and not venc:
        util.resumen("## Newsletter\nNo hay novedades ni vencimientos esta semana: no se manda.")
        return
    asunto, html = armar(notas, venc, sitio, hoy)
    mails = sorted({(p.get("email") or "").strip().lower() for p in db.select("preferencias", {"select": "email", "newsletter": "eq.true", "limit": "2000"})} - {""})
    usuario, clave = util.secreto("SMTP_USER"), util.secreto("SMTP_PASS")
    if prueba or not usuario or not clave:
        util.resumen(f"## Newsletter (prueba, no se mandó)\n**{asunto}** · {len(mails)} suscriptores\n\n" + ("Faltan SMTP_USER / SMTP_PASS.\n" if not prueba else ""))
        return asunto, html
    if not mails:
        util.resumen("## Newsletter\nTodavía no hay suscriptores: no se manda.")
        return
    enviados, fallas = 0, 0
    tope = int(cfg.get("newsletter_tope_diario", 450))  # Gmail deja mandar unos 500 destinatarios por día
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as s:  # igual que el mail de avisos de la fábrica
        s.starttls()
        s.login(usuario, clave)
        for m in mails[:tope]:  # un mail por persona: nadie ve la dirección de otro
            msg = MIMEText(html, "html", "utf-8")
            msg["Subject"], msg["From"], msg["To"] = asunto, formataddr(("Ramacontable", usuario)), m
            try:
                s.sendmail(usuario, [m], msg.as_string())
                enviados += 1
            except Exception as e:  # noqa
                fallas += 1
                util.log("No pude mandar a un suscriptor:", util.ocultar(str(e))[:120])
    util.resumen(f"## Newsletter\n**{asunto}**\n\nEnviados: {enviados} · con error: {fallas}"
                 + (f" · quedaron sin mandar {len(mails) - tope} por el tope diario de Gmail" if len(mails) > tope else ""))


if __name__ == "__main__":
    correr()
