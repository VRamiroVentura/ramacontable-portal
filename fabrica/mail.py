"""Aviso por mail de cada nota publicada (Gmail con contraseña de aplicación)."""
import smtplib
from email.mime.text import MIMEText
from html import escape

from . import util


def avisar(notas, sitio, destino):
    usuario, clave = util.secreto("SMTP_USER"), util.secreto("SMTP_PASS")
    if not notas:
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
    asunto = (f"Se publicó: {notas[0]['titulo']}" if len(notas) == 1 and notas[0]["estado"] == "publicada"
              else f"Ramacontable: {len(notas)} notas nuevas")
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
