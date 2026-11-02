"""Aviso por mail de cada nota publicada (Gmail con contraseña de aplicación)."""
import smtplib
from email.mime.text import MIMEText
from html import escape

from . import util


def avisar(notas, sitio, destino, conv_ok=(), conv_rev=(), alertas=(), observaciones=()):
    usuario, clave = util.secreto("SMTP_USER"), util.secreto("SMTP_PASS")
    if not notas and not conv_ok and not conv_rev and not alertas:
        return
    if not usuario or not clave:
        util.log("Sin SMTP_USER/SMTP_PASS: no mando el mail de aviso.")
        return
    filas = []
    for n in notas:
        if n["estado"] == "publicada":
            ver = f"{sitio}nota-{n['slug']}.html?admin=1"
            estado = "Publicada"
        else:
            ver = f"{sitio}nota.html?n={n['slug']}"
            estado = "Para revisar (no publicada)"
        filas.append(
            f"<tr><td style='padding:12px 0;border-bottom:1px solid #ddd'>"
            f"<div style='font:12px sans-serif;color:#A8844F;text-transform:uppercase'>{escape(estado)} · {escape(n.get('antetitulo', ''))}</div>"
            f"<div style='font:bold 17px Georgia,serif;color:#13271F;margin:4px 0'>{escape(n['titulo'])}</div>"
            f"<div style='font:14px sans-serif;color:#444'>{escape(n.get('encorto', ''))}</div>"
            + (f"<div style='font:13px sans-serif;color:#8C1D18;margin-top:4px'>Motivo: {escape(n.get('motivo_revision', ''))}</div>" if n["estado"] != "publicada" else "")
            + f"<div style='margin-top:8px'><a href='{ver}' style='background:#A8844F;color:#fff;padding:7px 12px;text-decoration:none;font:bold 13px sans-serif;border-radius:3px'>Ver, editar o borrar</a></div>"
            f"</td></tr>")
    for c in list(conv_ok) + list(conv_rev):
        rev = c in conv_rev
        filas.append(f"<tr><td style='padding:12px 0;border-bottom:1px solid #ddd'>"
                     f"<div style='font:12px sans-serif;color:#A8844F;text-transform:uppercase'>{'Escala para revisar' if rev else 'Escala actualizada'}</div>"
                     f"<div style='font:bold 17px Georgia,serif;color:#13271F;margin:4px 0'>{escape(c['nombre'])}: {escape(c['periodo'])}</div>"
                     + (f"<div style='font:13px sans-serif;color:#8C1D18'>Motivo: {escape(c['motivo'])}</div>" if rev else "")
                     + f"<div style='margin-top:8px'><a href='{sitio}escala-{c['slug']}.html?admin=1' style='background:#A8844F;color:#fff;padding:7px 12px;text-decoration:none;font:bold 13px sans-serif;border-radius:3px'>Ver convenio</a></div></td></tr>")
    for a in alertas:
        filas.insert(0, f"<tr><td style='padding:12px 0;border-bottom:1px solid #ddd'>"
                     f"<div style='font:bold 12px sans-serif;color:#8C1D18;text-transform:uppercase'>🚨 {escape(a['que'])}</div>"
                     f"<div style='font:bold 16px Georgia,serif;color:#13271F;margin:4px 0'>{escape(a['titulo'])}</div>"
                     f"<div style='margin-top:8px'><a href='{a['url']}' style='color:#A8844F'>Ver publicación de Ignacio</a> · "
                     f"<a href='{sitio}nota-{a['nota']}.html?admin=1' style='color:#A8844F'>Revisar nuestra nota</a></div></td></tr>")
    for t, o in observaciones:
        filas.append(f"<tr><td style='padding:8px 0;font:13px sans-serif;color:#555'>Publicada aunque el verificador observó (fuente Ignacio) · <b>{escape(t)}</b>: {escape(o)}</td></tr>")
    if alertas:
        asunto = f"Ramacontable: Ignacio editó o borró {len(alertas)} publicación(es) que usamos"
    elif not notas:
        asunto = "Ramacontable: escalas de convenios actualizadas"
    elif len(notas) == 1 and notas[0]["estado"] == "publicada":
        asunto = f"Se publicó: {notas[0]['titulo']}"
    else:
        asunto = f"Ramacontable: {len(notas)} notas nuevas"
    cuerpo = (f"<div style='max-width:620px'><h2 style='font-family:Georgia,serif;color:#13271F'>ramacontable</h2>"
              f"<table style='width:100%;border-collapse:collapse'>{''.join(filas)}</table>"
              f"<p style='font:12px sans-serif;color:#777'>Para editar o borrar, entrá al portal con tu cuenta de Google de administrador.</p></div>")
    msg = MIMEText(cuerpo, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario, destino
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(usuario, clave)
            s.send_message(msg)
        util.log("Mail de aviso enviado a", destino)
    except Exception as e:  # noqa
        util.avisar("No se pudo mandar el mail", str(e))
