# Portal Ramacontable

Web del portal (ramacontable.com.ar). Se arma y se publica sola con GitHub Actions.

- `notas/`: una nota por archivo `.json`. Más adelante las va a escribir la fábrica automática.
- `web/`: diseño (estilos.css), lógica (app.js, editor.js) y librerías (vendor/).
- `paginas/`: vencimientos y términos.
- `supabase/esquema.sql`: base de datos (se pega una vez en Supabase → SQL Editor).
- `build.py`: arma la web en la carpeta `sitio/`.

La web se vuelve a publicar con cada cambio y cada 3 horas (para que Google lea los paso a paso nuevos).

Secretos que usa (Settings → Secrets and variables → Actions): `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`.
