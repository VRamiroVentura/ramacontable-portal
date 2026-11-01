"""Acceso a Supabase con la clave secreta (solo corre en GitHub; nunca va a la web)."""
from . import util


class DB:
    def __init__(self):
        self.url = (util.secreto("SUPABASE_URL") or "").rstrip("/")
        self.key = util.secreto("SUPABASE_SECRET_KEY")
        if not self.url or not self.key:
            raise RuntimeError("Faltan los secretos SUPABASE_URL o SUPABASE_SECRET_KEY")

    def _h(self, extra=None):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def _ok(self, r, que):
        if r is None or r.status_code >= 300:
            raise RuntimeError(f"Supabase ({que}): {getattr(r, 'status_code', '?')} {util.ocultar(getattr(r, 'text', ''))[:300]}")
        return r

    def select(self, tabla, params):
        r = util.pedir("GET", f"{self.url}/rest/v1/{tabla}", headers=self._h(), params=params, timeout=40)
        return self._ok(r, "leer " + tabla).json()

    def upsert(self, tabla, filas, conflicto=None):
        params = {"on_conflict": conflicto} if conflicto else None
        r = util.pedir("POST", f"{self.url}/rest/v1/{tabla}", params=params, json=filas, timeout=40,
                       headers=self._h({"Prefer": "resolution=merge-duplicates,return=minimal"}))
        self._ok(r, "guardar " + tabla)

    def insertar_si_no_existe(self, tabla, filas, conflicto):
        r = util.pedir("POST", f"{self.url}/rest/v1/{tabla}", params={"on_conflict": conflicto}, json=filas, timeout=40,
                       headers=self._h({"Prefer": "resolution=ignore-duplicates,return=minimal"}))
        self._ok(r, "guardar " + tabla)

    def update(self, tabla, filtro, datos):
        r = util.pedir("PATCH", f"{self.url}/rest/v1/{tabla}", params=filtro, json=datos, timeout=40,
                       headers=self._h({"Prefer": "return=minimal"}))
        self._ok(r, "actualizar " + tabla)
