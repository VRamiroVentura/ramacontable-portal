"""Avisa a Bing y otros buscadores (IndexNow) las páginas nuevas o cambiadas. Se corre después de publicar."""
import json, os, urllib.request
d = json.load(open(os.path.join("sitio", "indexnow.json"), encoding="utf-8"))
if not d["urls"]:
    print("IndexNow: nada nuevo para avisar"); raise SystemExit
host = d["urls"][0].split("/")[2]
cuerpo = json.dumps({"host": host, "key": d["key"], "keyLocation": f"https://{host}/{d['key']}.txt", "urlList": d["urls"][:1000]}).encode()
try:
    r = urllib.request.urlopen(urllib.request.Request("https://api.indexnow.org/indexnow", cuerpo,
                               {"Content-Type": "application/json; charset=utf-8"}), timeout=30)
    print("IndexNow:", r.status, len(d["urls"]), "páginas avisadas")
except Exception as ex:
    print("IndexNow no respondió (no frena la publicación):", ex)
