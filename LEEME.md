# Portal Ramacontable

Web del portal y fábrica automática de notas. Todo corre gratis en GitHub Actions.

## Web
- `build.py` arma la web (carpeta `sitio/`) con las notas de Supabase y de `notas/`. Se publica con cada cambio y cada hora.
- `web/`: diseño y lógica. `paginas/`: vencimientos, términos, administración y nota dinámica.
- `supabase/esquema.sql`: base de datos (se pega en Supabase → SQL Editor cada vez que cambia; se puede correr encima).

## Fábrica de notas (`fabrica/`, `prompts/`, `config.json`)
Cada 2 horas de 7 a 23: lee el Boletín Oficial y los portales de referencia, agrupa por tema, redacta con Gemini,
verifica que no haya datos inventados y publica. Lo oficial se publica enseguida; lo de portales, cuando al menos dos lo publicaron.
Si algo no cierra, la nota queda "para revisar" y llega un mail.

- `config.json` → `"modo"`: `"ensayo"` (no publica, muestra el resultado en el resumen de la ejecución) o `"activo"`.
- `prompts/`: instrucciones de agrupado, redacción y verificación.
- Administración: entrando con ramacontable@gmail.com o rventrura95@gmail.com aparecen las opciones de editar, publicar y borrar, y la página `admin.html`.

Secretos: `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, y opcionales `SMTP_USER` / `SMTP_PASS` (mails de aviso).
