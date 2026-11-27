"""Cliente de Gemini (copiado de shorts-fabrica: busca solo un modelo vigente si uno se retira)."""
import json
import re

from . import util

API = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


def _json_de(texto):
    t = re.sub(r"```(?:json)?", "", texto or "").strip()
    a = t.find("{")
    if a < 0:
        raise ValueError("La IA no devolvió JSON: " + t[:200])
    # se lee el primer objeto JSON completo y se ignora lo que venga después (a veces la IA agrega texto o un segundo objeto)
    return json.JSONDecoder().raw_decode(t[a:])[0]


LISTA = "https://generativelanguage.googleapis.com/v1beta/models"
_DESCARTAR = ("image", "tts", "audio", "live", "embed", "native", "exp", "computer", "robotics", "vision", "omni")
# Motivos por los que Google bloquea el pedido por su contenido (no tiene sentido probar otro modelo)
BLOQUEOS = ("PROHIBITED_CONTENT", "SAFETY", "BLOCKLIST", "SPII", "OTHER", "IMAGE_SAFETY", "RECITATION")
_SEGURIDAD = [{"category": c, "threshold": "BLOCK_ONLY_HIGH"} for c in
              ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT",
               "HARM_CATEGORY_DANGEROUS_CONTENT")]


class Bloqueado(RuntimeError):
    """Google rechazó el pedido por su contenido (pasa con el pedido, no con el modelo)."""
_modelo_ok = None  # el primer modelo que anduvo en esta ejecución se reusa
_modelo_ok_liviano = None
_AGOTADOS = set()   # modelos que en esta vuelta dieron 404 (retirado) o 429 por cupo DIARIO: no se vuelven a probar
_DESCUBIERTOS = None  # lista de modelos vigentes (se pide una sola vez por vuelta)
AGOTADOS_LOG = []
USO = {}  # pedidos que salieron bien, por modelo  # para el informe: qué modelo se quedó sin cupo y cuándo


def _version(nombre):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", nombre)
    return float(m.group(1)) if m else 0.0


def _descubrir(clave):
    """Pide a Google la lista de modelos vigentes y ordena los Flash del más nuevo al más viejo.
    Así, cuando Google retire un modelo, la fábrica encuentra sola el reemplazo."""
    try:
        r = util.pedir("GET", LISTA, headers={"x-goog-api-key": clave}, params={"pageSize": 1000}, timeout=60)
        modelos = r.json().get("models", []) if r is not None and r.status_code == 200 else []
    except Exception as e:  # noqa
        util.log("No pude listar los modelos de Gemini:", util.ocultar(str(e)))
        return []
    nombres = []
    for m in modelos:
        n = m.get("name", "").split("/")[-1]
        if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n
                and not any(x in n for x in _DESCARTAR)):
            nombres.append(n)
    # primero Flash común, después Lite; dentro de cada grupo, estable antes que preview y versión más nueva primero
    nombres.sort(key=lambda n: ("lite" in n, "preview" in n, -_version(n), n))
    return nombres


def _cuerpo(sistema, usuario, temperatura, modelo, con_pensamiento, con_seguridad=True):
    gen = {"responseMimeType": "application/json", "maxOutputTokens": 32768}
    moderno = "latest" in modelo or _version(modelo) >= 3
    if moderno:
        # Gemini 3+: Google recomienda temperatura 1.0 y, si no se aclara, piensa "a fondo" y gasta
        # todo el cupo de salida pensando. Con nivel bajo alcanza para guiones cortos.
        if con_pensamiento:
            gen["thinkingConfig"] = {"thinkingLevel": util.config().get("gemini_pensamiento", "low")}
    else:
        gen["temperature"] = temperatura
    cuerpo = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        # usuario puede ser texto o una lista de partes (texto + imágenes)
        "contents": [{"role": "user", "parts": usuario if isinstance(usuario, list) else [{"text": usuario}]}],
        "generationConfig": gen,
    }
    if con_seguridad:
        cuerpo["safetySettings"] = _SEGURIDAD
    return cuerpo


def _mensaje(r):
    try:
        return r.json()["error"]["message"][:220]
    except Exception:  # noqa
        return (getattr(r, "text", "") or "")[:220]


import time as _time
INICIO = _time.time()
PEDIDOS = [0]  # pedidos a Gemini en esta vuelta (para el resumen)


class SinTiempo(RuntimeError):
    """Se acabó el tiempo de la vuelta: no se arrancan pedidos nuevos para poder guardar y cerrar a tiempo."""


def _queda(segundos=0):
    limite = float(util.config().get("minutos_max_vuelta", 38)) * 60
    if _time.time() - INICIO + segundos > limite:
        raise SinTiempo(f"se llegó al límite de {limite / 60:.0f} minutos de la vuelta")


def gemini(sistema, usuario, temperatura=0.9, liviano=False):
    """Si Google está saturado (503/429 en todos los modelos), espera y reintenta hasta 3 veces antes de rendirse.
    Si la vuelta ya usó su tiempo, no arranca pedidos nuevos (SinTiempo)."""
    import time
    _queda()
    PEDIDOS[0] += 1
    # La IA no sabe qué día es: sin esto marca como «error» normas y fechas del año en curso (ej. «Decreto 1366/2026: el 2026 no transcurrió»)
    hoy = util.ahora().date()
    sistema = (f"FECHA DE HOY: {hoy.day:02d}/{hoy.month:02d}/{hoy.year}. Las normas, fechas y vigencias de {hoy.year} (y de {hoy.year - 1}) son actuales y "
               f"reales: no las marques como error ni las corrijas por el año. Solo marcá una fecha si las fuentes dicen otra.\n\n") + sistema
    for intento in range(3):
        try:
            return _gemini(sistema, usuario, temperatura, liviano)
        except Bloqueado:
            raise
        except RuntimeError as e:
            saturado = " 503 " in str(e) or " 429 " in str(e) or "high demand" in str(e)
            if not saturado or intento == 2:
                raise
            _queda(60 * (intento + 1) + 120)
            util.log(f"Gemini saturado; espero {60 * (intento + 1)} s y reintento")
            time.sleep(60 * (intento + 1))


_ULTIMO = {}  # último pedido a cada modelo (para no pasar el límite por minuto)


def _pausa(modelo):
    """El nivel gratis permite 5 pedidos por minuto en Flash y 15 en Lite: se espera lo justo entre pedidos al mismo modelo.
    Sin esto, el 429 por minuto hacía saltar a otro modelo y gastaba su cupo DIARIO."""
    import time
    hueco = 4.5 if "lite" in modelo else 13
    falta = _ULTIMO.get(modelo, 0) + hueco - time.time()
    if falta > 0:
        time.sleep(falta)
    _ULTIMO[modelo] = time.time()


def _ordenar(modelos, liviano):
    """Flash para redactar y verificar (calidad); Lite primero para tareas livianas (agrupar, datos, vencimientos),
    que tiene mucho más cupo gratis por día. Siempre quedan los dos tipos como respaldo."""
    flash = [m for m in modelos if "lite" not in m][:3]
    lite = [m for m in modelos if "lite" in m][:3]
    return lite + flash if liviano else flash + lite


def _gemini(sistema, usuario, temperatura=0.9, liviano=False):
    global _modelo_ok, _modelo_ok_liviano, _DESCUBIERTOS
    clave = util.secreto("GEMINI_API_KEY")
    if not clave:
        raise RuntimeError("Falta el secreto GEMINI_API_KEY (Settings → Secrets and variables → Actions)")
    cfg = util.config()
    if liviano:
        preferidos = ([_modelo_ok_liviano] if _modelo_ok_liviano else []) + cfg.get("gemini_modelos_livianos", ["gemini-flash-lite-latest"]) \
            + cfg.get("gemini_modelos", ["gemini-flash-latest"])
    else:
        preferidos = ([_modelo_ok] if _modelo_ok else []) + cfg.get("gemini_modelos", ["gemini-flash-latest"])
    probados, errores, descubiertos, bloqueos = set(_AGOTADOS), [], False, 0
    cola = list(preferidos)
    while cola or not descubiertos:
        if not cola:
            descubiertos = True
            if _DESCUBIERTOS is None:
                _DESCUBIERTOS = _descubrir(clave)
            cola = [m for m in _ordenar(_DESCUBIERTOS, liviano) if m not in probados]
            if cola:
                util.log("Busco modelos vigentes de Gemini:", ", ".join(cola))
            continue
        modelo = cola.pop(0)
        if modelo in probados:
            continue
        probados.add(modelo)
        _pausa(modelo)
        texto, fin = "", ""
        # Si el modelo no acepta algún ajuste (pensamiento o filtros), pruebo sin él.
        for ajustes in ((True, True), (False, True), (False, False)):
            try:
                r = util.pedir("POST", API.format(modelo=modelo), headers={"x-goog-api-key": clave},
                               json=_cuerpo(sistema, usuario, temperatura, modelo, *ajustes),
                               intentos=1 if descubiertos else 2, espera=15, timeout=150)
            except Exception as e:  # noqa  (Google no contestó a tiempo: paso al modelo siguiente)
                r = None
                errores.append(f"{modelo}: no respondió ({type(e).__name__})")
                break
            if r is not None and r.status_code == 400 and any(x in _mensaje(r).lower() for x in ("think", "safety")):
                continue
            break
        if r is None:
            continue
        if r.status_code != 200:
            errores.append(f"{modelo}: {getattr(r, 'status_code', '?')} {_mensaje(r)}")
            crudo = str(getattr(r, "text", "") or "")
            if r.status_code == 404 or (r.status_code == 429 and "PerDay" in crudo):
                _AGOTADOS.add(modelo)  # retirado o sin cupo del día: no se gasta otro pedido en él en esta vuelta
                AGOTADOS_LOG.append(f"{modelo} ({'retirado' if r.status_code == 404 else 'sin cupo diario'})")
            continue
        datos = r.json()
        cand = (datos.get("candidates") or [{}])[0]
        en_pedido = (datos.get("promptFeedback") or {}).get("blockReason", "")
        fin = cand.get("finishReason", "") or en_pedido
        donde = "en lo que le mandamos" if en_pedido and not datos.get("candidates") else "en lo que la IA escribió"
        partes = (cand.get("content") or {}).get("parts", [])
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        try:
            resultado = _json_de(texto)
            if liviano:
                _modelo_ok_liviano = modelo
            else:
                if _modelo_ok != modelo:
                    util.log("Modelo de Gemini usado:", modelo)
                _modelo_ok = modelo
            USO[modelo] = USO.get(modelo, 0) + 1
            return resultado
        except Exception as e:  # noqa
            errores.append(f"{modelo}: respuesta sin JSON (motivo: {fin or 'desconocido'}) {str(e)[:80]}")
            if fin in BLOQUEOS:
                bloqueos += 1
                if bloqueos >= 2:  # dos modelos distintos lo rechazan: es el contenido del pedido
                    raise Bloqueado(f"Google bloqueó el pedido por su contenido ({fin}, {donde})")
    raise RuntimeError("Gemini falló con todos los modelos: " + " | ".join(errores))
