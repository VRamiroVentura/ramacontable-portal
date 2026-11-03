"""Plano 3D de La Plata: el trazado real (OpenStreetMap) visto con una cámara
inclinada que vuela, marca lugares y se acerca.

Cómo funciona (todo gratis, en GitHub, sin placa de video):
- Baja una vez las calles, plazas, agua y edificios del casco desde OpenStreetMap
  y los guarda en datos/laplata/osm_casco.json.gz (para no volver a pedirlos).
- En cada cuadro dibuja desde arriba solo la zona que ve la cámara, con la
  resolución justa, y la inclina en perspectiva. Las sombras de manzanas y
  edificios dan el efecto de maqueta.
- Encima pone pines y carteles proyectados en 3D, y resalta calles o plazas.

Uso:
    python fabrica/plano3d.py --muestra            # video de ~10 s en out/plano3d/
    python fabrica/plano3d.py --muestra --paleta noche

Desde otro módulo (para el montaje):
    from plano3d import Plano
    plano = Plano.cargar()
    plano.video(ruta_mp4, tomas, segundos)
"""
import argparse
import gzip
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = os.getcwd()
CACHE = os.path.join(RAIZ, "datos", "laplata", "osm_casco.json.gz")
SALIDA = os.path.join(RAIZ, "out", "plano3d")
CAJA = (-34.962, -58.002, -34.880, -57.905)  # sur, oeste, norte, este (casco y alrededores)
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
UA = {"User-Agent": "shorts-fabrica/1.0 (https://github.com/VRamiroVentura/shorts-fabrica)"}
ANCHO, ALTO, FPS = 1080, 1920, 30
FOCAL = 1500.0

# Paletas propias. "tilo": La Plata es la ciudad de los tilos y los jacarandás.
PALETAS = {
    "tilo": {
        "manzana": (228, 224, 210), "manzana_sombra": (196, 190, 172), "calle": (250, 248, 241),
        "avenida": (246, 214, 150), "avenida_borde": (214, 172, 96), "diagonal": (232, 122, 92),
        "diagonal_borde": (196, 88, 62), "borde": (205, 199, 182),
        "verde": (122, 178, 96), "verde_borde": (84, 140, 66), "arbol": (78, 132, 62), "arbol_luz": (150, 196, 112),
        "verde_oscuro": (128, 160, 112), "agua": (112, 170, 200), "edificio": (238, 233, 220),
        "edificio_lado": (205, 196, 176), "edif_sombra": (172, 165, 146), "niebla": (236, 238, 232),
        "resalte": (123, 84, 168), "resalte_claro": (189, 165, 220), "tinta": (40, 38, 46),
        "cartel": (255, 255, 255), "titulo_fondo": (123, 84, 168), "titulo_texto": (255, 255, 255),
        "credito": (90, 86, 96),
    },
    "noche": {
        "manzana": (38, 44, 58), "manzana_sombra": (26, 30, 40), "calle": (92, 104, 128),
        "avenida": (150, 176, 214), "avenida_borde": (96, 118, 156), "diagonal": (72, 206, 190),
        "diagonal_borde": (40, 150, 138), "borde": (30, 34, 46),
        "verde": (70, 150, 92), "verde_borde": (46, 110, 66), "arbol": (40, 104, 62), "arbol_luz": (100, 178, 112),
        "verde_oscuro": (40, 66, 56), "agua": (40, 92, 132), "edificio": (60, 68, 86),
        "edificio_lado": (46, 52, 68), "edif_sombra": (20, 24, 32), "niebla": (30, 34, 46),
        "resalte": (232, 176, 72), "resalte_claro": (250, 214, 140), "tinta": (20, 22, 30),
        "cartel": (248, 246, 240), "titulo_fondo": (232, 176, 72), "titulo_texto": (24, 26, 34),
        "credito": (170, 178, 196),
    },
}
ANCHO_CALLE = {  # metros aproximados de calzada + veredas
    "motorway": 30, "trunk": 30, "primary": 26, "secondary": 24, "tertiary": 20,
    "unclassified": 14, "residential": 14, "living_street": 10, "pedestrian": 9,
}


# ------------------------------------------------------------------ utilidades
def normal(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def fuente(tam, negrita=True):
    for ruta in ([os.path.join(RAIZ, "assets", "fuentes", "Poppins-Bold.ttf")] if negrita else []) + [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if negrita else
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(ruta, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def suave(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ datos OSM
CONSULTA_BASE = """
[out:json][timeout:180];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|pedestrian)$"]({s},{o},{n},{e});
  way["leisure"~"^(park|garden|pitch|stadium)$"]({s},{o},{n},{e});
  way["natural"~"^(water|wood)$"]({s},{o},{n},{e});
  way["landuse"~"^(grass|forest)$"]({s},{o},{n},{e});
  way["amenity"="place_of_worship"]({s},{o},{n},{e});
);
out geom;
"""
CONSULTA_EDIFICIOS = """
[out:json][timeout:240];
way["building"]({s},{o},{n},{e});
out geom;
"""


def _overpass(consulta, minimo):
    for url in OVERPASS:
        for intento in range(2):
            try:
                r = requests.post(url, data={"data": consulta}, headers=UA, timeout=300)
                if r.status_code == 200:
                    els = r.json().get("elements", [])
                    if len(els) >= minimo:
                        return els
                print(f"  aviso: {url} respondió {r.status_code}")
            except (requests.RequestException, ValueError) as ex:
                print(f"  aviso: {url} falló ({ex})")
            time.sleep(15 * (intento + 1))
    return []


def bajar_osm(caja=CAJA):
    s, o, n, e = caja
    base = _overpass(CONSULTA_BASE.format(s=s, o=o, n=n, e=e), 100)
    if not base:
        return []
    edificios = _overpass(CONSULTA_EDIFICIOS.format(s=s, o=o, n=n, e=e), 1)
    if not edificios:
        print("  aviso: sin edificios esta vez (OpenStreetMap tardó); el plano sale igual.")
    return base + edificios


def cargar_elementos():
    if os.path.exists(CACHE):
        with gzip.open(CACHE, "rt", encoding="utf-8") as f:
            return json.load(f)
    els = bajar_osm()
    if not els:
        raise RuntimeError("No pude bajar el plano de OpenStreetMap. Probá de nuevo en un rato.")
    chicos = []
    for el in els:  # guardamos solo lo que usamos, con 6 decimales
        g = [[round(p["lat"], 6), round(p["lon"], 6)] for p in el.get("geometry", []) if p]
        if len(g) >= 2:
            t = el.get("tags", {})
            chicos.append({"t": {k: t[k] for k in ("highway", "leisure", "natural", "landuse", "building",
                                                   "building:levels", "height", "amenity", "name", "ref")
                                 if k in t}, "g": g})
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with gzip.open(CACHE, "wt", encoding="utf-8") as f:
        json.dump(chicos, f, separators=(",", ":"))
    return chicos


# ------------------------------------------------------------------ el plano
class Plano:
    def __init__(self, elementos, paleta="tilo"):
        self.pal = PALETAS.get(paleta, PALETAS["tilo"])
        lats = [p[0] for el in elementos for p in el["g"]]
        lons = [p[1] for el in elementos for p in el["g"]]
        self.lat0, self.lon0 = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
        self.kx = 111320 * math.cos(math.radians(self.lat0))
        self.ky = 110540
        self.verdes, self.agua, self.calles, self.edificios = [], [], [], []
        self.por_nombre = {}
        for el in elementos:
            t = el["t"]
            pts = np.array([self.metros(lat, lon) for lat, lon in el["g"]], dtype=float)
            caja = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
            item = {"t": t, "p": pts, "c": caja}
            nombre = normal(t.get("name"))
            if nombre:
                self.por_nombre.setdefault(nombre, []).append(item)
            if "highway" in t:
                item["w"] = ANCHO_CALLE.get(t["highway"], 14)
                if "diagonal" in nombre:
                    item["clase"] = "diagonal"
                    item["w"] = max(item["w"], 22)
                elif t["highway"] in ("motorway", "trunk", "primary", "secondary") or nombre.startswith(("avenida", "av ", "av. ")):
                    item["clase"] = "avenida"
                    item["w"] = max(item["w"], 24)
                else:
                    item["clase"] = "calle"
                self.calles.append(item)
            elif t.get("natural") == "water":
                self.agua.append(item)
            elif t.get("leisure") or t.get("natural") == "wood" or t.get("landuse"):
                self.verdes.append(item)
            elif "building" in t or t.get("amenity") == "place_of_worship":
                alto = 9.0
                try:
                    alto = float(t.get("height") or 3.2 * float(t.get("building:levels")))
                except (TypeError, ValueError):
                    pass
                item["h"] = min(max(alto, 4.0), 120.0)
                self.edificios.append(item)
        self.calles.sort(key=lambda it: ({"calle": 0, "avenida": 1, "diagonal": 2}[it["clase"]], it["w"]))
        for it in self.verdes:
            it["arboles"] = arboles_en(it["p"])
        self.ids_verdes = {id(it) for it in self.verdes}
        self.giro = self._giro_grilla()

    @classmethod
    def cargar(cls, paleta="tilo"):
        return cls(cargar_elementos(), paleta)

    # coordenadas: x hacia el este, y hacia el norte, en metros
    def metros(self, lat, lon):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def _giro_grilla(self):
        hist = np.zeros(90)
        for it in self.calles:
            d = np.diff(it["p"], axis=0)
            largo = np.hypot(d[:, 0], d[:, 1])
            ang = (np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 90).astype(int) % 90
            np.add.at(hist, ang, largo)
        return float(np.argmax(hist))

    def buscar(self, *nombres):
        """Centro (x, y) y elementos del primer nombre que aparezca en el plano."""
        for n in nombres:
            n = normal(n)
            hallados = self.por_nombre.get(n) or [it for k, v in self.por_nombre.items() if n in k for it in v]
            if hallados:
                areas = [h for h in hallados if "highway" not in h["t"]] or hallados
                pts = np.vstack([h["p"] for h in areas])
                return (float(pts[:, 0].mean()), float(pts[:, 1].mean())), areas
        return None, []

    def calles_numero(self, *numeros):
        """Calles o avenidas cuyo nombre o ref es ese número (ej. 51, 53, 1)."""
        pat = re.compile(r"(^|\D)(" + "|".join(str(n) for n in numeros) + r")(\D|$)")
        return [it for it in self.calles
                if pat.search(normal(it["t"].get("name"))) or pat.search(normal(it["t"].get("ref")))]

    def esquina(self, a, b):
        """Punto donde se cruzan las calles a y b (por ejemplo 7 y 50). None si no se cruzan."""
        sa, sb = self.calles_numero(a), self.calles_numero(b)
        mejores = []
        for ia in sa:
            for p1, p2 in zip(ia["p"], ia["p"][1:]):
                for ib in sb:
                    for q1, q2 in zip(ib["p"], ib["p"][1:]):
                        r, s = p2 - p1, q2 - q1
                        den = r[0] * s[1] - r[1] * s[0]
                        if abs(den) < 1e-9:
                            continue
                        t = ((q1[0] - p1[0]) * s[1] - (q1[1] - p1[1]) * s[0]) / den
                        u = ((q1[0] - p1[0]) * r[1] - (q1[1] - p1[1]) * r[0]) / den
                        if -0.02 <= t <= 1.02 and -0.02 <= u <= 1.02:
                            x = p1 + t * r
                            mejores.append((float(np.hypot(*x)), (float(x[0]), float(x[1]))))
        return min(mejores)[1] if mejores else None

    # -------------------------------------------------------------- cámara
    def camara(self, objetivo, distancia, inclinacion, rumbo):
        """objetivo (x, y) en metros; inclinación en grados desde el piso; rumbo en grados."""
        fi, th = math.radians(inclinacion), math.radians(rumbo)
        f = np.array([math.cos(fi) * math.cos(th), math.cos(fi) * math.sin(th), -math.sin(fi)])
        pos = np.array([objetivo[0], objetivo[1], 0.0]) - f * distancia
        r = np.cross(f, [0, 0, 1.0])
        r /= np.linalg.norm(r)
        u = np.cross(r, f)
        return {"pos": pos, "f": f, "r": r, "u": u}

    def a_pantalla(self, cam, x, y, z=0.0):
        v = np.array([x, y, z]) - cam["pos"]
        prof = v @ cam["f"]
        if prof <= 1:
            return None
        return (ANCHO / 2 + FOCAL * (v @ cam["r"]) / prof, ALTO / 2 - FOCAL * (v @ cam["u"]) / prof, prof)

    def a_piso(self, cam, sx, sy):
        d = cam["f"] + ((sx - ANCHO / 2) / FOCAL) * cam["r"] - ((sy - ALTO / 2) / FOCAL) * cam["u"]
        if d[2] >= -1e-4:
            return None
        k = -cam["pos"][2] / d[2]
        return cam["pos"][:2] + k * d[:2]

    # -------------------------------------------------------------- dibujo
    def _dibujar_arriba(self, x0, y0, x1, y1, esc, resaltes):
        """Dibuja la zona [x0,x1]x[y0,y1] vista desde arriba, a 'esc' píxeles por metro."""
        pal = self.pal
        w, h = max(2, int((x1 - x0) * esc)), max(2, int((y1 - y0) * esc))
        im = Image.new("RGB", (w, h), pal["manzana"])
        d = ImageDraw.Draw(im)

        def px(p):
            return [((a - x0) * esc, (y1 - b) * esc) for a, b in p]

        def visible(it, margen=0):
            c = it["c"]
            return not (c[2] < x0 - margen or c[0] > x1 + margen or c[3] < y0 - margen or c[1] > y1 + margen)

        for it in self.verdes:
            if visible(it) and len(it["p"]) >= 3:
                d.polygon(px(it["p"]), fill=pal["verde"], outline=pal["verde_borde"])
        for it in self.agua:
            if visible(it) and len(it["p"]) >= 3:
                d.polygon(px(it["p"]), fill=pal["agua"])
        calles = [it for it in self.calles if visible(it, 40)]
        # sombra de manzana: así cada manzana parece una placa levantada
        sombra = max(1, int(5 * esc))
        for it in calles:
            pts = [(a + sombra, b + sombra) for a, b in px(it["p"])]
            d.line(pts, fill=pal["manzana_sombra"], width=max(1, int((it["w"] + 4) * esc)), joint="curve")
        bordes = {"calle": pal["borde"], "avenida": pal["avenida_borde"], "diagonal": pal["diagonal_borde"]}
        rellenos = {"calle": pal["calle"], "avenida": pal["avenida"], "diagonal": pal["diagonal"]}
        for it in calles:  # ya vienen ordenadas: calles, avenidas y arriba las diagonales
            ancho = max(1, int(it["w"] * esc))
            borde = max(ancho + 2, int((it["w"] + 3) * esc))
            if it["clase"] != "calle" and esc < 0.35:  # de lejos se engrosan para que se vean
                ancho, borde = max(ancho, 3), max(borde, 5)
            d.line(px(it["p"]), fill=bordes[it["clase"]], width=borde, joint="curve")
            d.line(px(it["p"]), fill=rellenos[it["clase"]], width=ancho, joint="curve")
        for it in resaltes.get("calles", []):
            if visible(it, 40):
                d.line(px(it["p"]), fill=pal["resalte"], width=max(4, int((it["w"] + 4) * esc)), joint="curve")
        # árboles en plazas y parques (de cerca)
        if esc >= 0.22:
            r = max(1.5, 4.2 * esc)
            for it in self.verdes:
                if not visible(it, 20):
                    continue
                for (a, b) in it["arboles"]:
                    x, y = (a - x0) * esc, (y1 - b) * esc
                    d.ellipse([x - r + r * 0.5, y - r + r * 0.5, x + r + r * 0.5, y + r + r * 0.5], fill=pal["verde_borde"])
                    d.ellipse([x - r, y - r, x + r, y + r], fill=pal["arbol"])
                    d.ellipse([x - r * 0.55, y - r * 0.75, x + r * 0.15, y - r * 0.05], fill=pal["arbol_luz"])
        # plaza o lugar marcado: sigue verde y lleva un borde violeta grueso
        for it in resaltes.get("areas", []):
            if visible(it) and len(it["p"]) >= 3:
                pts = px(it["p"])
                if id(it) in self.ids_verdes:
                    d.line(pts + pts[:1], fill=pal["resalte"], width=max(5, int(9 * esc)), joint="curve")
                else:
                    d.polygon(pts, fill=pal["resalte_claro"], outline=pal["resalte"])
        # edificios: sombra hacia el sudeste + "pared" + techo corrido según la altura
        edif = [it for it in self.edificios if visible(it, 60)]
        if esc >= 0.18:
            for it in edif:
                s = it["h"] * 0.55 * esc
                d.polygon([(a + s, b + s * 0.8) for a, b in px(it["p"])], fill=pal["edif_sombra"])
            for it in edif:
                d.polygon(px(it["p"]), fill=pal["edificio_lado"])
                s = it["h"] * 0.12 * esc
                d.polygon([(a - s * 0.3, b - s) for a, b in px(it["p"])], fill=pal["edificio"])
        return im

    def cuadro(self, toma, resaltes=None, pines=(), titulo=None, credito=True):
        resaltes = resaltes or {}
        cam = self.camara(toma["objetivo"], toma["distancia"], toma["inclinacion"], toma["rumbo"])
        # dónde corta el piso en la pantalla (lo de más arriba es "cielo" con niebla)
        corte = 0
        while corte < ALTO and self.a_piso(cam, ANCHO / 2, corte) is None:
            corte += 8
        y_arriba = min(ALTO - 2, corte + 4)
        esquinas = [(0, y_arriba), (ANCHO, y_arriba), (ANCHO, ALTO), (0, ALTO)]
        piso = [self.a_piso(cam, sx, sy) for sx, sy in esquinas]
        if any(p is None for p in piso):
            return Image.new("RGB", (ANCHO, ALTO), self.pal["niebla"])
        piso = np.array(piso)
        x0, y0 = piso[:, 0].min() - 30, piso[:, 1].min() - 30
        x1, y1 = piso[:, 0].max() + 30, piso[:, 1].max() + 30
        # resolución: la del borde de abajo (lo más cercano) con un poco de margen, con tope
        cerca = np.linalg.norm(piso[2] - piso[3])
        esc = min(1.25 * ANCHO / max(cerca, 1), 4200 / max(x1 - x0, y1 - y0))
        arriba = self._dibujar_arriba(x0, y0, x1, y1, esc, resaltes)
        # homografía pantalla -> imagen de arriba
        dst = [((p[0] - x0) * esc, (y1 - p[1]) * esc) for p in piso]
        A, b = [], []
        for (sx, sy), (u, v) in zip(esquinas, dst):
            A.append([sx, sy, 1, 0, 0, 0, -u * sx, -u * sy]); b.append(u)
            A.append([0, 0, 0, sx, sy, 1, -v * sx, -v * sy]); b.append(v)
        coef = np.linalg.solve(np.array(A, float), np.array(b, float))
        im = arriba.transform((ANCHO, ALTO), Image.PERSPECTIVE, tuple(coef), Image.BICUBIC,
                              fillcolor=self.pal["niebla"])
        # niebla de lejos: da profundidad
        niebla = Image.new("RGB", (ANCHO, ALTO), self.pal["niebla"])
        mascara = Image.new("L", (1, ALTO))
        for yy in range(ALTO):
            k = 1 - min(max((yy - corte) / max(1, ALTO * 0.45), 0), 1)
            mascara.putpixel((0, yy), int(255 * (k ** 1.6)) if yy >= corte else 255)
        im = Image.composite(niebla, im, mascara.resize((ANCHO, ALTO)))
        d = ImageDraw.Draw(im)
        for pin in pines:
            self._pin(d, cam, pin)
        if titulo:
            self._titulo(d, titulo)
        if credito:
            f = fuente(24, negrita=False)
            t = "Plano real · © OpenStreetMap contributors"
            d.text((ANCHO - d.textlength(t, font=f) - 30, ALTO - 60), t, font=f, fill=self.pal["credito"])
        return im

    def _pin(self, d, cam, pin):
        pal = self.pal
        alfa = pin.get("alfa", 1.0)
        if alfa <= 0.02:
            return
        base = self.a_pantalla(cam, pin["xy"][0], pin["xy"][1])
        if not base:
            return
        bx, by, prof = base
        largo = 150 * min(1.0, alfa * 1.3)
        top = (bx, by - largo)
        d.ellipse([bx - 16, by - 7, bx + 16, by + 7], fill=pal["resalte_claro"])
        d.line([base[:2], top], fill=pal["resalte"], width=6)
        d.ellipse([top[0] - 15, top[1] - 15, top[0] + 15, top[1] + 15], fill=pal["resalte"],
                  outline=pal["cartel"], width=4)
        texto = pin.get("texto", "")
        if texto and alfa > 0.4:
            f = fuente(46)
            w = d.textlength(texto, font=f)
            x = min(max(top[0] - w / 2 - 28, 30), ANCHO - w - 86)
            y = top[1] - 110
            d.rounded_rectangle([x, y, x + w + 56, y + 80], radius=22, fill=pal["cartel"],
                                outline=pal["resalte"], width=5)
            d.text((x + 28, y + 12), texto, font=f, fill=pal["tinta"])

    def _titulo(self, d, texto):
        pal = self.pal
        f = fuente(64)
        lineas, linea = [], ""
        for p in texto.split():
            if d.textlength((linea + " " + p).strip(), font=f) > ANCHO - 200:
                lineas.append(linea)
                linea = p
            else:
                linea = (linea + " " + p).strip()
        lineas.append(linea)
        alto = 40 + 80 * len(lineas)
        d.rounded_rectangle([60, 170, ANCHO - 60, 170 + alto], radius=32, fill=pal["titulo_fondo"])
        for i, l in enumerate(lineas):
            d.text((100, 190 + 80 * i), l, font=f, fill=pal["titulo_texto"])

    # -------------------------------------------------------------- video
    def video(self, ruta, tomas, segundos, resaltes=None, pines_por_t=None, titulo_por_t=None, gif=None):
        """tomas: lista de (t_segundos, {objetivo, distancia, inclinacion, rumbo}). Interpola suave."""
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        n = int(segundos * FPS)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{ANCHO}x{ALTO}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "medium", "-movflags", "+faststart", ruta]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        fotos = []
        try:
            for i in range(n):
                t = i / FPS
                toma = interpolar(tomas, t)
                pines = pines_por_t(t) if pines_por_t else []
                titulo = titulo_por_t(t) if titulo_por_t else None
                im = self.cuadro(toma, resaltes, pines, titulo)
                proc.stdin.write(im.tobytes())
                if gif and i % 3 == 0:
                    fotos.append(im.resize((270, 480), Image.LANCZOS).quantize(colors=128))
                if i % FPS == 0:
                    print(f"  segundo {int(t)} de {int(segundos)}")
        finally:
            proc.stdin.close()
            proc.wait()
        if gif and fotos:
            fotos[0].save(gif, save_all=True, append_images=fotos[1:], duration=100, loop=0)
        return ruta


def arboles_en(poligono, paso=16.0, maximo=500):
    """Puntos de árboles dentro de una plaza (grilla con un poco de desorden, siempre igual)."""
    p = np.asarray(poligono)
    if len(p) < 3:
        return []
    x0, y0 = p[:, 0].min(), p[:, 1].min()
    x1, y1 = p[:, 0].max(), p[:, 1].max()
    if (x1 - x0) * (y1 - y0) < 600:
        return []
    rng = np.random.default_rng(int(abs(x0 * 7 + y0 * 13)) % (2 ** 32))
    xs, ys = np.meshgrid(np.arange(x0 + paso / 2, x1, paso), np.arange(y0 + paso / 2, y1, paso))
    pts = np.column_stack([xs.ravel(), ys.ravel()]) + rng.uniform(-paso * 0.3, paso * 0.3, (xs.size, 2))
    dentro = np.zeros(len(pts), bool)
    j = len(p) - 1
    for i in range(len(p)):  # punto en polígono (rayo)
        xi, yi, xj, yj = p[i, 0], p[i, 1], p[j, 0], p[j, 1]
        cruza = ((yi > pts[:, 1]) != (yj > pts[:, 1])) & (
            pts[:, 0] < (xj - xi) * (pts[:, 1] - yi) / (yj - yi + 1e-12) + xi)
        dentro ^= cruza
        j = i
    pts = pts[dentro]
    if len(pts) > maximo:
        pts = pts[rng.choice(len(pts), maximo, replace=False)]
    return [tuple(x) for x in pts]


def interpolar(tomas, t):
    tomas = sorted(tomas, key=lambda x: x[0])
    if t <= tomas[0][0]:
        return dict(tomas[0][1])
    for (ta, a), (tb, b) in zip(tomas, tomas[1:]):
        if ta <= t <= tb:
            k = suave((t - ta) / max(tb - ta, 1e-6))
            return {
                "objetivo": (a["objetivo"][0] + (b["objetivo"][0] - a["objetivo"][0]) * k,
                             a["objetivo"][1] + (b["objetivo"][1] - a["objetivo"][1]) * k),
                "distancia": math.exp(math.log(a["distancia"]) + (math.log(b["distancia"]) - math.log(a["distancia"])) * k),
                "inclinacion": a["inclinacion"] + (b["inclinacion"] - a["inclinacion"]) * k,
                "rumbo": a["rumbo"] + (b["rumbo"] - a["rumbo"]) * k,
            }
    return dict(tomas[-1][1])


# ------------------------------------------------------------------ escena "mapa" del montaje
_PLANOS = {}


def plano_cacheado(paleta="tilo"):
    if _PLANOS.get("_error"):  # si ya falló en este video, no lo reintenta en cada escena
        raise RuntimeError(_PLANOS["_error"])
    if paleta not in _PLANOS:
        try:
            _PLANOS[paleta] = Plano.cargar(paleta)
        except Exception as e:
            _PLANOS["_error"] = str(e)
            raise
    return _PLANOS[paleta]


def _numeros(valor):
    salida = []
    for x in (valor or []):
        m = re.search(r"\d+", str(x))
        if m:
            salida.append(int(m.group()))
    return salida


def clip_escena(mapa, segundos, destino, paleta="tilo"):
    """Arma el clip de una escena con mapa. mapa = {"lugar": "Plaza Moreno"} o {"esquina": [7, 50]},
    y opcional "calles": [51, 53] (se resaltan), "texto" (cartel) y "vista": "cerca" o "general".
    Si no encuentra el lugar, levanta un error y el montaje usa un clip como siempre."""
    plano = plano_cacheado(paleta)
    objetivo, areas = None, []
    if mapa.get("esquina"):
        nums = _numeros(mapa["esquina"])
        if len(nums) >= 2:
            objetivo = plano.esquina(nums[0], nums[1])
    if not objetivo and mapa.get("lugar"):
        objetivo, areas = plano.buscar(mapa["lugar"])
    vista = mapa.get("vista", "cerca")
    calles = plano.calles_numero(*_numeros(mapa.get("calles"))) if mapa.get("calles") else []
    if not objetivo:
        if vista == "general" and calles:
            centro, _ = plano.buscar("Plaza Moreno")
            objetivo = centro or (0.0, 0.0)
        else:
            raise ValueError(f"no encontré en el plano: {mapa}")
    rumbo = plano.giro + 45
    if vista == "general":
        tomas = [(0.0, {"objetivo": objetivo, "distancia": 6500, "inclinacion": 60, "rumbo": rumbo - 6}),
                 (segundos, {"objetivo": objetivo, "distancia": 4300, "inclinacion": 56, "rumbo": rumbo + 4})]
    else:
        tomas = [(0.0, {"objetivo": objetivo, "distancia": 2600, "inclinacion": 56, "rumbo": rumbo - 10}),
                 (segundos, {"objetivo": objetivo, "distancia": 720, "inclinacion": 48, "rumbo": rumbo + 14})]
    texto = (mapa.get("texto") or mapa.get("lugar") or "")
    if not texto and mapa.get("esquina"):
        n = _numeros(mapa["esquina"])
        texto = f"{n[0]} y {n[1]}" if len(n) >= 2 else ""
    texto = str(texto)[:24]

    def pines(t):
        if vista == "general" and not mapa.get("lugar") and not mapa.get("esquina"):
            return []
        return [{"xy": objetivo, "texto": texto, "alfa": min(1.0, max(0.0, (t - 0.3) / 0.5))}]

    resaltes = {"calles": calles, "areas": areas if mapa.get("lugar") else []}
    plano.video(str(destino), tomas, segundos, resaltes, pines, None)
    return destino


# ------------------------------------------------------------------ muestra
def muestra(paleta="tilo", segundos=10.0):
    plano = Plano.cargar(paleta)
    centro_pm, area_pm = plano.buscar("Plaza Moreno")
    if not centro_pm:
        print("  aviso: no encontré Plaza Moreno en el plano; uso el centro del mapa.")
        centro_pm, area_pm = (0.0, 0.0), []
    centro_cat, _ = plano.buscar("Catedral de La Plata", "Catedral Inmaculada Concepcion", "Catedral")
    eje = plano.calles_numero(51, 53)
    rumbo = plano.giro + 45  # la grilla queda en diagonal, como la ven todos
    tomas = [
        (0.0, {"objetivo": centro_pm, "distancia": 7200, "inclinacion": 62, "rumbo": rumbo - 8}),
        (3.0, {"objetivo": centro_pm, "distancia": 5200, "inclinacion": 58, "rumbo": rumbo}),
        (6.5, {"objetivo": centro_pm, "distancia": 1500, "inclinacion": 52, "rumbo": rumbo + 12}),
        (segundos, {"objetivo": centro_cat or centro_pm, "distancia": 650, "inclinacion": 47, "rumbo": rumbo + 30}),
    ]

    def pines(t):
        salida = []
        if t >= 3.4:
            salida.append({"xy": centro_pm, "texto": "Plaza Moreno", "alfa": min(1, (t - 3.4) / 0.6) if t < 7.2 else max(0, 1 - (t - 7.2) / 0.5)})
        if centro_cat and t >= 7.4:
            salida.append({"xy": centro_cat, "texto": "Catedral", "alfa": min(1, (t - 7.4) / 0.6)})
        return salida

    def titulo(t):
        return "La Plata, a escala real" if t < 3.0 else None

    resaltes = {"calles": eje, "areas": area_pm}
    os.makedirs(SALIDA, exist_ok=True)
    ruta = os.path.join(SALIDA, f"muestra_plano3d_{paleta}.mp4")
    gif = os.path.join(SALIDA, f"muestra_plano3d_{paleta}.gif")
    t0 = time.time()
    plano.video(ruta, tomas, segundos, resaltes, pines, titulo, gif=gif)
    # 4 cuadros sueltos para mirar rápido
    for k, t in enumerate((0.5, 3.5, 6.5, segundos - 0.2), 1):
        plano.cuadro(interpolar(tomas, t), resaltes, pines(t), titulo(t)).save(
            os.path.join(SALIDA, f"cuadro_{k}_{paleta}.jpg"), quality=88)
    info = {"paleta": paleta, "segundos_render": round(time.time() - t0),
            "encontro_plaza_moreno": bool(area_pm), "encontro_catedral": bool(centro_cat),
            "calles_51_53": len(eje), "edificios": len(plano.edificios), "calles": len(plano.calles),
            "giro_grilla": plano.giro}
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return ruta, info


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", action="store_true")
    ap.add_argument("--paleta", default="tilo", choices=list(PALETAS))
    ap.add_argument("--segundos", type=float, default=10.0)
    a = ap.parse_args(argv)
    if a.muestra:
        ruta, info = muestra(a.paleta, a.segundos)
        md = ["## Muestra del plano 3D de La Plata", "",
              f"- Paleta: **{info['paleta']}**",
              f"- Plaza Moreno encontrada: {'sí' if info['encontro_plaza_moreno'] else 'no'}",
              f"- Catedral encontrada: {'sí' if info['encontro_catedral'] else 'no'}",
              f"- Tramos de 51 y 53 resaltados: {info['calles_51_53']}",
              f"- Edificios en el plano: {info['edificios']} · calles: {info['calles']}",
              f"- Tardó {info['segundos_render']} s en armarse", "",
              "El video, el GIF y 4 cuadros están en los artefactos (plano3d)."]
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write("\n".join(md) + "\n")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
