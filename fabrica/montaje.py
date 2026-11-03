"""Arma el video final: voz, clips de fondo que cambian cada ~2 segundos, subtítulos grandes palabra por
palabra, el gancho escrito desde el segundo 0, barra de progreso y música suave opcional."""
import json
import random
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from . import broll, util, voz

W, H, FPS = 1080, 1920, 30
AMARILLO_ASS = "&H0000D4FF&"   # (255, 212, 0) en formato BGR de ASS
BLANCO_ASS = "&H00FFFFFF&"
CORTE = 2.3                    # cada cuánto cambia el clip de fondo (segundos, aprox.)
SUB_Y = 1160                   # centro de los subtítulos (zona segura de Reels/TikTok/Shorts)


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("Falló " + " ".join(cmd[:4]) + ": " + r.stderr[-900:])
    return r.stdout


def _t(seg):
    seg = max(0.0, seg)
    h, m = int(seg // 3600), int(seg % 3600 // 60)
    return f"{h}:{m:02d}:{seg % 60:05.2f}"


def _fuente_subs():
    fonts = util.RAIZ / "fonts"
    for archivo, nombre in (("Poppins-ExtraBold.ttf", "Poppins ExtraBold"), ("Poppins-Black.ttf", "Poppins Black"),
                            ("Poppins-Bold.ttf", "Poppins")):
        if (fonts / archivo).exists():
            return nombre
    return "Poppins"


def _esc(t):
    return re.sub(r"[{}\\]", "", str(t))


# ---------------------------------------------------------------- subtítulos
def _bloques(palabras, max_palabras=3, max_letras=15):
    """Agrupa de a 2 o 3 palabras, corta en la puntuación y nunca mezcla dos escenas."""
    bloques, actual = [], []
    for p in palabras:
        if actual and p[3] != actual[-1][3]:
            bloques.append(actual)
            actual = []
        actual.append(p)
        txt = " ".join(x[2] for x in actual)
        if len(actual) >= max_palabras or len(txt) >= max_letras or re.search(r"[.,;:?!…]$", p[2]):
            bloques.append(actual)
            actual = []
    if actual:
        bloques.append(actual)
    return bloques


def subtitulos(palabras, gancho, serie, usuario, dur_gancho, dur_total, destino):
    fuente = _fuente_subs()
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{fuente},112,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,1.5,0,1,9,4,5,70,70,0,1
Style: Gancho,{fuente},84,&H00111111,&H00111111,&H0000D4FF,&H0000D4FF,1,0,0,0,100,100,0.5,0,3,22,0,8,110,110,330,1
Style: Serie,{fuente},42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,2,0,1,4,2,8,60,60,150,1
Style: Marca,{fuente},36,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,1,0,1,4,2,2,60,60,64,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    eventos = []
    for bloque in _bloques(palabras):
        for i, w in enumerate(bloque):
            ini = w[0]
            fin = bloque[i + 1][0] if i + 1 < len(bloque) else w[1] + 0.25
            partes = []
            for j, x in enumerate(bloque):
                txt = _esc(x[2]).upper()
                if j == i:
                    partes.append("{\\c" + AMARILLO_ASS + "\\fscx108\\fscy108}" + txt + "{\\c" + BLANCO_ASS +
                                  "\\fscx100\\fscy100}")
                else:
                    partes.append(txt)
            pop = "{\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)}" if i == 0 else ""
            eventos.append([ini, fin, "{\\pos(%d,%d)}" % (W // 2, SUB_Y) + pop + " ".join(partes)])
    eventos.sort(key=lambda e: e[0])
    for k in range(len(eventos) - 1):  # nunca dos a la vez y sin parpadeos
        sig = eventos[k + 1][0]
        if eventos[k][1] > sig or sig - eventos[k][1] < 0.4:
            eventos[k][1] = sig
    lineas = [f"Dialogue: 2,{_t(s)},{_t(e)},Sub,,0,0,0,,{txt}" for s, e, txt in eventos if e - s > 0.02]
    if gancho:
        lineas.append(f"Dialogue: 3,{_t(0)},{_t(dur_gancho)},Gancho,,0,0,0,,"
                      "{\\fad(0,150)}" + _esc(gancho).upper())
    if serie:
        lineas.append(f"Dialogue: 1,{_t(dur_gancho)},{_t(dur_total)},Serie,,0,0,0,,"
                      "{\\fad(200,0)}" + _esc(serie).upper())
    if usuario:
        lineas.append(f"Dialogue: 1,{_t(0)},{_t(dur_total)},Marca,,0,0,0,,{_esc(usuario)}")
    destino.write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- fondo
# Comodines: escenas de plata y trámites que acompañan casi cualquier frase de finanzas sin desentonar.
COMODINES = ["hands counting money", "hand holding smartphone", "typing on laptop keyboard",
             "calculator and paperwork", "card payment terminal", "wallet with cash",
             "signing documents", "us dollar bills"]

PUNTUAR = """Sos editor de videos cortos para una cuenta argentina de plata, impuestos, historias y curiosidades.
Te paso las escenas (lo que se dice) con opciones de video de fondo, y al final unos COMODINES.
Mirá la imagen de cada opción y poné un puntaje:
3 = muestra justo lo que se dice: la acción, el objeto o el lugar.
2 = no muestra justo lo que se dice pero acompaña bien la frase (en temas de plata: pagos, un celular, una compu,
    papeles, trabajo o compras; en historias: la época, el lugar o el tipo de objeto).
1 = neutro: no molesta pero no aporta.
0 = tiene texto agregado encima (títulos, letras grandes, marcas de agua, logos), o no tiene nada que ver
    (un cielo, flores, alguien en la cama, paisajes), o no puede pasar por Argentina:
    carteles en otros idiomas o alfabetos, lugares reconocibles de otros países, billetes que no sean pesos
    argentinos o dólares.
Las opciones marcadas PROPIA son videos grabados en Argentina.
Para los COMODINES puntuá en general: ¿sirven para acompañar un video de plata e impuestos en Argentina?
Las POSTALES son tomas de Argentina para enganchar la vista (paisajes, drones, ciudades, cosas típicas):
3 = hermosa y claramente argentina (Buenos Aires, Patagonia, Iguazú, glaciares, cordillera, mar, mate, asado);
2 = linda y puede pasar por Argentina; 0 = fea, borrosa, de otro país o con texto, títulos o marcas de agua encima.
Respondé solo con JSON: {"escenas": [{"escena": 1, "puntajes": [3, 0, 2]}], "comodines": [2, 0, 3], "postales": [3, 0]}"""


def _imagen(c, ruta):
    import base64
    mini = broll.miniatura(c, ruta)
    if not mini:
        return None
    return {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(Path(mini).read_bytes()).decode()}}


def _puntuar_con_ia(escenas, candidatos, comodines, trabajo, postales=()):
    """La IA mira una imagen de cada opción y la puntúa de 0 a 3.
    Si falla, se usa un puntaje por defecto (2 para lo que pasó el filtro)."""
    from . import escritor
    defecto = ([[2] * len(c) for c in candidatos], [2] * len(comodines), [2] * len(postales))
    partes, hay = [{"text": "ESCENAS Y OPCIONES:"}], False
    for i, (esc, cands) in enumerate(zip(escenas, candidatos), 1):
        partes.append({"text": f'\nESCENA {i}: "{esc["texto"]}"'})
        for k, c in enumerate(cands):
            img = _imagen(c, trabajo / f"mini_{i}_{k}.jpg")
            if img:
                hay = True
                partes += [{"text": f"Opción {k}" + (" (PROPIA)" if c.get("propio") else "") + ":"}, img]
            else:
                partes.append({"text": f"Opción {k}: (sin imagen, poné 1)"})
    partes.append({"text": "\nCOMODINES:"})
    for k, c in enumerate(comodines):
        img = _imagen(c, trabajo / f"mini_comodin_{k}.jpg")
        partes += [{"text": f"Comodín {k}:"}, img] if img else [{"text": f"Comodín {k}: (sin imagen, poné 1)"}]
        hay = hay or bool(img)
    if postales:
        partes.append({"text": "\nPOSTALES:"})
        for k, c in enumerate(postales):
            img = _imagen(c, trabajo / f"mini_postal_{k}.jpg")
            partes += [{"text": f"Postal {k}:"}, img] if img else [{"text": f"Postal {k}: (sin imagen, poné 1)"}]
            hay = hay or bool(img)
    if not hay:
        return defecto
    try:
        r = escritor.gemini(PUNTUAR, partes, temperatura=0.2)
        por_escena = {int(e.get("escena", 0)) - 1: e.get("puntajes", []) for e in r.get("escenas", [])
                      if isinstance(e, dict)}
        puntajes = []
        for i, cands in enumerate(candidatos):
            p = [int(x) if str(x).lstrip("-").isdigit() else 1 for x in por_escena.get(i, [])]
            puntajes.append((p + [1] * len(cands))[:len(cands)])
        pc = [int(x) if str(x).lstrip("-").isdigit() else 1 for x in r.get("comodines", [])]
        pc = (pc + [1] * len(comodines))[:len(comodines)]
        pp = [int(x) if str(x).lstrip("-").isdigit() else 1 for x in r.get("postales", [])]
        pp = (pp + [1] * len(postales))[:len(postales)]
        util.log("Puntajes de los fondos:", puntajes, "comodines:", pc, "postales:", pp)
        return puntajes, pc, pp
    except Exception as e:  # noqa
        util.log("No pude puntuar los fondos con la IA:", util.ocultar(e))
        return defecto


CON_TEXTO = """Te paso fotogramas de los clips de fondo de un video (dos cuadros de cada clip, uno al lado del otro).
Decime qué clips tienen TEXTO AGREGADO ENCIMA del video: títulos, letras grandes, nombres de lugares escritos,
marcas de agua, logos, créditos o subtítulos. No cuenta un cartel chico que es parte natural de la escena
(el letrero de un negocio a lo lejos) ni el texto de una pantalla de celular o de compu.
Respondé solo con JSON: {"con_texto": [números de los clips con texto agregado]} (lista vacía si ninguno)."""


def _con_texto(lista, trabajo, ronda):
    """Devuelve los índices (de `lista`) de los fondos que tienen texto sobreimpreso."""
    from . import escritor
    partes = []
    for k, x in enumerate(lista):
        cuadros = []
        for j, frac in enumerate((0.3, 0.75)):
            f = trabajo / f"control_{ronda}_{k}_{j}.jpg"
            try:
                _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{x['largo'] * frac:.2f}", "-i", str(x["dest"]),
                      "-frames:v", "1", "-vf", "scale=200:-1", str(f)])
                cuadros.append(Image.open(f).convert("RGB"))
            except Exception:  # noqa
                pass
        if not cuadros:
            continue
        hoja = Image.new("RGB", (sum(c.width for c in cuadros) + 8, max(c.height for c in cuadros)), (0, 0, 0))
        xx = 0
        for c in cuadros:
            hoja.paste(c, (xx, 0))
            xx += c.width + 8
        ruta = trabajo / f"control_{ronda}_{k}.jpg"
        hoja.save(ruta, "JPEG", quality=70)
        import base64
        partes += [{"text": f"Clip {k}:"},
                   {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(ruta.read_bytes()).decode()}}]
    if not partes:
        return []
    try:
        r = escritor.gemini(CON_TEXTO, partes, temperatura=0.2)
        idx = [int(v) for v in r.get("con_texto", []) if str(v).lstrip("-").isdigit()]
        if idx:
            util.log("Fondos con texto encima:", idx)
        return idx
    except Exception as e:  # noqa
        util.log("No pude revisar si los fondos tienen texto:", util.ocultar(e))
        return []


RECIENTES = "data/clips_recientes.json"


def clips_recientes():
    return util.leer_json(RECIENTES, []) or []


def anotar_clips(ids, tope=150):
    """Guarda los clips usados, para que los próximos videos prefieran otros."""
    lista = [x for x in clips_recientes() if x not in set(ids)] + list(ids)
    util.guardar_json(RECIENTES, lista[-tope:])


# ---------------------------------------------------------------- La Plata: banco de fotos y plano
def _normal(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return " " + re.sub(r"[^a-z0-9]+", " ", t.lower()).strip() + " "


def _banco_laplata():
    """Fotos del banco (assets/laplata/catalogo.json): [(etiquetas normalizadas, [rutas])]."""
    ruta = util.RAIZ / "assets" / "laplata" / "catalogo.json"
    try:
        cat = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    salida = []
    for tid, t in cat.items():
        etiquetas = [_normal(x) for x in (t.get("palabras") or []) + [t.get("nombre", "")] if len(str(x)) > 3]
        fotos = [util.RAIZ / x["archivo"] for x in t.get("imagenes", [])
                 if (util.RAIZ / x["archivo"]).exists() and "vertical" not in x["archivo"]]
        if etiquetas and fotos:
            salida.append((tid, etiquetas, fotos))
    return salida


def _fotos_del_lugar(banco, esc, usados):
    """Fotos del banco que nombran el lugar que dice esta escena (primero las que no se usaron)."""
    texto = _normal(esc.get("texto", "")) + _normal((esc.get("mapa") or {}).get("lugar", ""))
    salida = []
    for tid, etiquetas, fotos in banco:
        if any(e in texto for e in etiquetas):
            for f in fotos:
                cid = "laplata:" + f.name
                if cid not in usados:
                    salida.append({"id": cid, "link": str(f), "foto": True, "propio": True, "banco_laplata": tid})
    return salida


def _falta(esc, que):
    return {"escena": esc.get("texto", "")[:140], "busqueda": [x for x in (esc.get("broll") or []) if x][:2],
            "se_uso": que}


def _fondos(escenas, tiempos, trabajo, seed, evitar=()):
    """Un clip cada ~2.3 s. Siempre video: primero lo que muestra justo lo que se dice, si no un comodín
    de plata y trámites; nunca algo de otro país ni sin relación. Devuelve (segmentos, de stock, banco, propios)."""
    from . import video
    banco, buscar, clave = broll.proveedor()
    propios = broll.propios()
    # 1) opciones por escena: primero los clips propios, después los del banco (sin los que son de afuera)
    candidatos = []
    for esc, (ini, fin) in zip(escenas, tiempos):
        dur = fin - ini
        if esc.get("grafico"):  # esta escena va con un cartel animado: no hace falta buscar clips
            candidatos.append([])
            continue
        lista = broll.propios_para(propios, esc)
        consultas = [x for x in (esc.get("broll") or []) if x][:2]
        if clave and consultas:
            consultas += [" ".join(x.split()[:2]) for x in consultas if len(x.split()) > 2]
            for c in consultas:
                try:
                    lista += [x for x in buscar(c, clave, set(), cantidad=3, minimo=min(dur, 3))
                              if not broll.de_afuera(x)]
                except Exception as e:  # noqa
                    util.log(f"{banco} falló:", util.ocultar(e))
                if len(lista) >= 4:
                    break
        vistos, unicos = set(), []
        for x in lista:
            if x["id"] not in vistos:
                vistos.add(x["id"])
                unicos.append(x)
        candidatos.append(unicos[:4])
    # comodines: tus clips propios primero, después algunos del banco
    comodines = [c for c in propios][:6]
    if clave:
        for q in random.sample(COMODINES, len(COMODINES)):
            if len(comodines) >= 12:
                break
            try:
                comodines += [x for x in buscar(q, clave, set(), cantidad=2, minimo=3) if not broll.de_afuera(x)]
            except Exception as e:  # noqa
                util.log(f"{banco} falló:", util.ocultar(e))
    ya = {x["id"] for lst in candidatos for x in lst}
    comodines = [c for c in comodines if c["id"] not in ya]
    cfg = util.config()
    tope_postales = int(cfg.get("postales_por_video", 3))
    lindas = broll.postales(buscar, clave) if (clave and tope_postales > 0) else []
    # 2) la IA puntúa
    puntajes, p_comodin, p_postal = _puntuar_con_ia(escenas, candidatos, comodines, trabajo, lindas)
    # 3) armado
    usados, segmentos, de_video, de_propios, n = set(evitar), [], 0, 0, 0  # evitar: clips de la versión anterior
    colocados = []  # cada fondo puesto: para revisar después que no tenga texto encima
    con_ia_de_imagen = bool(util.secreto("CF_ACCOUNT_ID") and util.secreto("CF_API_TOKEN"))

    recientes = set(clips_recientes())  # clips de los últimos videos: van al final de la fila, para no repetir

    def mejores(lista, pts, minimo):
        orden = sorted([(p, k) for k, p in enumerate(pts) if p >= minimo and lista[k]["id"] not in usados],
                       key=lambda x: (-x[0], lista[x[1]]["id"] in recientes, not lista[x[1]].get("propio"), x[1]))
        return [lista[k] for _, k in orden]

    tope_graficos = int(cfg.get("graficos_por_video", 4))
    anterior_grafico = False
    faltas = []  # escenas sin un video que muestre justo lo que se dice: van al reporte como pedido de material

    postales_usadas, anterior_postal = 0, False
    ultima = len(escenas) - 1
    graficos_ok = []
    mapas_ok, anterior_mapa = [], False
    tope_mapas = int(cfg.get("mapas_por_video", 2))
    banco_lp = _banco_laplata() if getattr(_fondos, "la_plata", False) else []
    for i, (esc, (ini, fin)) in enumerate(zip(escenas, tiempos)):
        dur = fin - ini
        # Plan B: si para esta escena no hay ningún video que muestre justo lo que se dice (o los únicos buenos
        # ya salieron en los últimos videos), va el cartel de reserva que propuso la IA. Nunca dos carteles seguidos.
        if not esc.get("grafico") and esc.get("plan_b") and not anterior_grafico and len(graficos_ok) < tope_graficos:
            frescos = any(p >= 3 and c["id"] not in recientes and c["id"] not in usados
                          for c, p in zip(candidatos[i], puntajes[i]))
            if not frescos:
                util.log(f"Escena {i + 1}: sin video que pegue, va el cartel de reserva")
                esc["grafico"] = esc["plan_b"]
                faltas.append(_falta(esc, "un cartel de reserva"))
        # Mapa de La Plata: el plano real con cámara que se acerca al lugar (nunca dos seguidos)
        if esc.get("mapa") and not esc.get("grafico") and not anterior_mapa and len(mapas_ok) < tope_mapas:
            destino = trabajo / f"fondo{n:03d}.mp4"
            try:
                from . import plano3d
                plano3d.clip_escena(esc["mapa"], dur, destino, cfg.get("mapa_paleta", "tilo"))
                segmentos.append(destino)
                colocados.append({"dest": destino, "largo": dur, "i": i, "clip": None, "n": n})
                mapas_ok.append((ini, fin))
                anterior_postal, anterior_grafico, anterior_mapa = False, False, True
                n += 1
                continue
            except Exception as e:  # noqa  (si no encuentra el lugar o falla, la escena va como siempre)
                util.log("No pude armar el mapa, sigo con clips:", util.ocultar(e))
        anterior_mapa = False
        if esc.get("grafico"):
            from . import graficos
            destino = trabajo / f"fondo{n:03d}.mp4"
            try:
                graficos.render(esc["grafico"], dur, destino, getattr(_fondos, "estilo", "oscuro"), seed + i)
                segmentos.append(destino)
                colocados.append({"dest": destino, "largo": dur, "i": i, "clip": None, "n": n})
                graficos_ok.append((ini, fin))
                anterior_postal, anterior_grafico = False, True
                n += 1
                continue
            except Exception as e:  # noqa  (si falla el cartel, la escena va con un clip como siempre)
                util.log("No pude armar el gráfico, uso un clip:", util.ocultar(e))
                esc["grafico"] = None
        anterior_grafico = False
        buenos = mejores(candidatos[i], puntajes[i], 2)          # pegan con la frase
        fotos_lp = _fotos_del_lugar(banco_lp, esc, usados) if banco_lp else []
        if fotos_lp:  # si la escena nombra un lugar del banco de La Plata, va primero su foto real
            util.log(f"Escena {i + 1}: foto del banco de La Plata ({fotos_lp[0]['banco_laplata']})")
            buenos = fotos_lp[:1] + buenos
        exacto = any(p >= 3 for p in puntajes[i])
        # Postal de Argentina: en la intriga (escena 2) y en el cierre siempre que no haya un clip exacto,
        # y en cualquier escena que no tenga nada bueno. Nunca dos seguidas ni más del tope.
        postal = []
        if lindas and postales_usadas < tope_postales and not anterior_postal:
            if (not buenos) or (i in (1, ultima) and not exacto):
                postal = mejores(lindas, p_postal, 2)[:1]
        if postal:
            buenos = postal
        exacto_fresco = any(p >= 3 and c["id"] not in recientes for c, p in zip(candidatos[i], puntajes[i]))
        if not exacto_fresco and i > 0:
            if postal:
                que = "una postal de Argentina"
            elif buenos:
                que = "un clip repetido" if exacto else "un clip aproximado"
            else:
                que = "un clip de relleno"
            faltas.append(_falta(esc, que))
        if not buenos:
            buenos = mejores(comodines, p_comodin, 2)[:1]          # comodín de plata y trámites
        if not buenos:
            buenos = (mejores(candidatos[i], puntajes[i], 1) or mejores(comodines, p_comodin, 1))[:1]
        cortes = max(1, min(round(dur / CORTE), len(buenos))) if buenos else 1
        for largo in [dur / cortes] * cortes:
            destino = trabajo / f"fondo{n:03d}.mp4"
            hecho, puesto = False, None
            while buenos and not hecho:
                c = buenos.pop(0)
                try:
                    if c.get("foto"):
                        broll.clip_de_foto(c["link"], largo, destino, acercar=(n % 2 == 0))
                    else:
                        crudo = broll.bajar(c["link"], trabajo / f"stock_{c['id']}.mp4")
                        broll.recortar(crudo, largo, destino)
                    usados.add(c["id"])
                    hecho, puesto = True, c
                    postales_usadas += 1 if c.get("postal") else 0
                    anterior_postal = bool(c.get("postal"))
                    if c.get("propio"):
                        de_propios += 1
                    else:
                        de_video += 1
                except Exception as e:  # noqa
                    util.log("Clip descartado:", util.ocultar(e))
            if not hecho:  # sin ningún video posible (por ejemplo, sin clave del banco)
                if con_ia_de_imagen:
                    img = trabajo / f"img{i}.png"
                    if not img.exists():
                        video.make_image(esc.get("prompt") or "", "", img, seed + i, esc.get("emoji") or "💡")
                    broll.clip_de_imagen(img, largo, destino, acercar=(n % 2 == 0))
                else:
                    broll.clip_tarjeta(esc.get("emoji") or "💡", largo, destino, acercar=(n % 2 == 0))
            segmentos.append(destino)
            colocados.append({"dest": destino, "largo": largo, "i": i, "clip": puesto, "n": n})
            n += 1

    # 4) control final: ningún fondo con títulos, letras o marcas de agua encima
    def alternativas(i):
        lista = mejores(candidatos[i], puntajes[i], 2) + mejores(comodines, p_comodin, 2)
        if lindas and postales_usadas < tope_postales:
            lista += mejores(lindas, p_postal, 2)
        return lista

    revisar = [k for k, x in enumerate(colocados) if x["clip"] and not x["clip"].get("propio")]
    for ronda in range(2):
        if not revisar:
            break
        con_texto = _con_texto([colocados[k] for k in revisar], trabajo, ronda)
        nuevos = []
        for idx in con_texto:
            if not 0 <= idx < len(revisar):
                continue
            x = colocados[revisar[idx]]
            util.log("Fondo con texto encima, lo cambio:", x["clip"].get("id"))
            hecho = False
            for c in alternativas(x["i"]):
                try:
                    if c.get("foto"):
                        broll.clip_de_foto(c["link"], x["largo"], x["dest"])
                    else:
                        crudo = broll.bajar(c["link"], trabajo / f"stock_{c['id']}.mp4")
                        broll.recortar(crudo, x["largo"], x["dest"])
                    usados.add(c["id"])
                    postales_usadas += 1 if c.get("postal") else 0
                    x["clip"], hecho = c, True
                    nuevos.append(revisar[idx])
                    break
                except Exception as e:  # noqa
                    util.log("Clip descartado:", util.ocultar(e))
            if not hecho:
                broll.clip_tarjeta(escenas[x["i"]].get("emoji") or "💡", x["largo"], x["dest"])
                x["clip"] = None
        revisar = nuevos
    _fondos.ids = [x["clip"]["id"] for x in colocados if x.get("clip") and x["clip"].get("id")]
    _fondos.graficos = graficos_ok
    _fondos.mapas = mapas_ok
    _fondos.faltas = faltas
    return segmentos, de_video, banco, de_propios, postales_usadas


def _musica(cfg):
    ruta = util.RAIZ / cfg.get("musica", "assets/music.mp3")
    if ruta.exists():
        return ruta
    carpeta = util.RAIZ / "assets"
    temas = sorted(list(carpeta.glob("*.mp3")) + list(carpeta.glob("*.m4a"))) if carpeta.exists() else []
    return random.choice(temas) if temas else None


def _portada(segmentos, contenido, destino, trabajo, serie_nombre=""):
    from . import video
    cuadro = trabajo / "cuadro_portada.jpg"
    try:
        _run(["ffmpeg", "-y", "-v", "error", "-ss", "0.4", "-i", str(segmentos[0]), "-frames:v", "1", str(cuadro)])
        im = Image.open(cuadro).convert("RGB")
        lado = min(im.size)
        x, y = (im.width - lado) // 2, (im.height - lado) // 2
        im.crop((x, y, x + lado, y + lado)).save(cuadro)
    except Exception:  # noqa
        video.fallback_card("", cuadro, contenido.get("miniatura", {}).get("emoji", "💡"))
    mini = contenido.get("miniatura", {})
    video.make_thumbnail(cuadro, mini.get("linea1") or contenido["titulo"], mini.get("linea2", ""), destino,
                         arriba=serie_nombre)


# ---------------------------------------------------------------- todo junto
def generar(contenido, serie_nombre, usuario, carpeta, evitar=(), estilo_graficos="oscuro"):
    cfg = util.config()
    salida = Path(carpeta)
    trabajo = salida / "_trabajo"
    trabajo.mkdir(parents=True, exist_ok=True)
    escenas = [{"texto": e["texto_voz"], "pantalla": e.get("texto_pantalla", ""), "emoji": e.get("emoji", ""),
                "prompt": e.get("prompt", ""), "broll": e.get("broll", ""),
                "grafico": e.get("grafico") if cfg.get("graficos", True) else None,
                "plan_b": e.get("grafico_plan_b") if cfg.get("graficos", True) else None,
                "mapa": e.get("mapa") if cfg.get("mapas", True) and isinstance(e.get("mapa"), dict) else None}
               for e in contenido["escenas"]]
    _fondos.estilo = estilo_graficos
    todo = _normal(serie_nombre + " " + " ".join(e["texto"] for e in escenas) + " " + contenido.get("titulo", ""))
    _fondos.la_plata = any(x in todo for x in (" la plata ", " platense", " platenses "))
    seed = random.randint(1, 10_000_000)

    # 1) voz y tiempos
    wav, palabras, tiempos, motor = voz.sintetizar([e["texto"] for e in escenas], trabajo, cfg)
    dur_voz = voz.duracion(wav)
    total = round(tiempos[-1][1], 3)

    # 2) fondos
    _fondos.ids = []
    _fondos.graficos = []
    _fondos.mapas = []
    _fondos.faltas = []
    segmentos, de_pexels, banco, de_propios, de_postales = _fondos(escenas, tiempos, trabajo, seed, evitar)
    (trabajo / "lista.txt").write_text("".join(f"file '{p.resolve()}'\n" for p in segmentos))
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(trabajo / "lista.txt"),
          "-c", "copy", str(trabajo / "fondo.mp4")])

    # 3) subtítulos + gancho
    gancho = (contenido["escenas"][0].get("texto_pantalla") or contenido.get("miniatura", {}).get("linea1") or "")
    dur_gancho = min(max(tiempos[0][1], 2.2), 4.0)
    subtitulos(palabras, gancho, serie_nombre, usuario, dur_gancho, total, trabajo / "subs.ass")

    # 4) mezcla final: fondo oscurecido + subtítulos + barra de progreso + voz (+ música)
    musica = _musica(cfg)
    fonts = util.RAIZ / "fonts"
    tramos = getattr(_fondos, "graficos", []) + getattr(_fondos, "mapas", [])  # carteles y mapas no se oscurecen
    sin_graf = (":enable='not(" + "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in tramos) + ")'") if tramos else ""
    filtro_v = (f"[0:v]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.22:t=fill{sin_graf},"
                f"ass={trabajo / 'subs.ass'}:fontsdir={fonts}[v0];"
                f"color=c=0xFFD400:s={W}x14:r={FPS}[barra];"
                f"[v0][barra]overlay=x='-w+w*t/{total}':y={H - 14}:shortest=1[v]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(trabajo / "fondo.mp4"), "-i", str(wav)]
    if musica:
        vol = float(cfg.get("musica_volumen", 0.08))
        cmd += ["-stream_loop", "-1", "-i", str(musica)]
        filtro_a = (f"[1:a]aresample=44100,apad=pad_dur=0.6[voz];"
                    f"[2:a]aresample=44100,volume={vol},afade=t=out:st={max(0.0, total - 1.5):.2f}:d=1.5[mus];"
                    f"[voz][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                    f"loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        filtro_a = "[1:a]aresample=44100,apad=pad_dur=0.6,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    cmd += ["-filter_complex", filtro_v + ";" + filtro_a, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
            str(salida / "video.mp4")]
    _run(cmd)

    # 5) portada
    _portada(segmentos, contenido, salida / "thumb.jpg", trabajo, serie_nombre)

    meta = {"duracion": round(voz.duracion(salida / "video.mp4"), 2), "voz": motor, "clips": len(segmentos),
            "graficos": len(getattr(_fondos, "graficos", [])), "mapas": len(getattr(_fondos, "mapas", [])),
            "estilo_graficos": getattr(_fondos, "estilo", ""),
            "faltas": getattr(_fondos, "faltas", []),
            "clips_stock": de_pexels, "banco": banco, "clips_propios": de_propios, "postales": de_postales, "musica": musica.name if musica else None, "voz_seg": round(dur_voz, 2),
            "clips_ids": list(getattr(_fondos, "ids", []))}
    (salida / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    util.log("Video:", json.dumps(meta, ensure_ascii=False))
    shutil.rmtree(trabajo, ignore_errors=True)
    return salida / "video.mp4", salida / "thumb.jpg"
