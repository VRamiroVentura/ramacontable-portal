/* Ramacontable · lógica de la web (login, perfiles, opiniones, paso a paso y votos) */
(function () {
  const cfg = window.RC_CONFIG || {};
  const sb = (cfg.url && cfg.key && window.supabase) ? window.supabase.createClient(cfg.url, cfg.key) : null;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const notaId = $('[data-nota]') ? $('[data-nota]').dataset.nota : null;
  let usuario = null, perfil = null, reputaciones = {}, misVotos = new Set();

  // ---------- utilidades ----------
  function h(tag, attrs = {}, ...hijos) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') el.className = v; else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) el.setAttribute(k, v === true ? '' : v);
    }
    for (const c of hijos.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
    return el;
  }
  function aviso(txt) {
    const t = h('div', { class: 'toast' }, txt); document.body.append(t); setTimeout(() => t.remove(), 4000);
  }
  function mensajeError(err) {
    const m = (err && err.message) || String(err);
    const i = m.indexOf('REGLA:');
    if (i >= 0) return m.slice(i + 6).trim();
    if (m.includes('duplicate key')) return 'Ya votaste esto.';
    if (m.includes('check constraint')) return 'Revisá que todos los campos estén completos y no sean demasiado largos.';
    return 'No se pudo guardar. Probá de nuevo en un rato.';
  }
  // mismo filtro que la base de datos, para avisar antes de enviar
  function revisarTexto(t) {
    if (!t) return null;
    if (/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/i.test(t)) return 'No se pueden publicar direcciones de mail.';
    if (/(^|[^a-z0-9])@[a-z0-9_.]{3,}/i.test(t)) return 'No se pueden publicar usuarios de redes sociales.';
    if (/(whats ?app|wsp|wpp|instagram|telegram|facebook|linkedin|tiktok|wa\.me)/i.test(t)) return 'No se pueden publicar redes sociales ni medios de contacto.';
    if (/\d{10,}/.test(t) || /\b\d{2}-\d{8}-\d\b/.test(t) || /\b\d{2,4}[ -]\d{3,4}[ -]\d{4}\b/.test(t)) return 'No se pueden publicar teléfonos, CUIT, DNI ni cuentas bancarias.';
    const re = /(?:https?:\/\/)?(?:www\.)?((?:[a-z0-9-]+\.)+(?:com|net|org|ar|io|me|ly|info|co|app|xyz|site|online|store|link|gob|gov)(?:\.ar)?)(?![a-z0-9])/gi;
    let m; while ((m = re.exec(t))) {
      const host = m[1].toLowerCase();
      if (!(/\.(gob|gov)\.ar$/.test(host) || ['consejo.org.ar', 'cpba.com.ar', 'facpce.org.ar'].includes(host)))
        return 'Solo se permiten links de organismos oficiales (.gob.ar / .gov.ar) y consejos profesionales.';
    }
    return null;
  }
  function hace(iso) {
    const s = (Date.now() - new Date(iso)) / 1000;
    if (s < 3600) return `hace ${Math.max(1, Math.round(s / 60))} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return new Date(iso).toLocaleDateString('es-AR', { day: 'numeric', month: 'short' });
  }
  function nivel(r) {
    if (!r || !r.aportes) return null;
    if (r.positivos >= 100) return 'Experto';
    if (r.positivos >= 25) return 'Referente';
    if (r.positivos >= 5) return 'Colaborador';
    return 'Aportante';
  }
  function tipoTexto(p) {
    if (!p) return '';
    if (p.tipo === 'recibido') return 'Contador/a';
    if (p.tipo === 'estudiante') return `Estudiante${p.avance != null ? ' · ' + p.avance + '%' : ''}`;
    return '';
  }

  // ---------- modal ----------
  const modal = $('#modal');
  function abrirModal(contenido, cerrable = true) {
    modal.innerHTML = '';
    const v = h('div', { class: 'ventana', role: 'dialog', 'aria-modal': 'true' });
    if (cerrable) v.append(h('button', { class: 'cerrar', 'aria-label': 'Cerrar', onclick: cerrarModal }, '×'));
    v.append(contenido); modal.append(v); modal.hidden = false;
    const f = v.querySelector('input,textarea,select'); if (f) f.focus();
  }
  function cerrarModal() { modal.hidden = true; modal.innerHTML = ''; }
  modal.addEventListener('click', e => { if (e.target === modal && !modal.dataset.fijo) cerrarModal(); });

  // ---------- sesión ----------
  async function ingresar() {
    if (!sb) return aviso('El ingreso todavía no está activo.');
    await sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: location.href.split('#')[0] } });
  }
  function exigirSesion() {
    if (usuario && perfil) return true;
    if (usuario && !perfil) { pedirPerfil(); return false; }
    abrirModal(h('div', {},
      h('h2', {}, 'Ingresá para participar'),
      h('p', {}, 'Con tu cuenta de Google podés subir paso a paso, opinar y votar. No guardamos contraseñas y tu mail no se muestra a nadie.'),
      h('button', { class: 'btn ancho', onclick: ingresar }, 'Ingresar con Google')));
    return false;
  }
  function pintarSesion() {
    const caja = $('#sesion'); caja.innerHTML = '';
    if (!usuario) { caja.append(h('button', { class: 'btn', onclick: ingresar }, 'Ingresar')); return; }
    const r = reputaciones[usuario.id];
    const n = nivel(r);
    caja.append(
      h('span', { class: 'yo' }, perfil ? perfil.nombre : 'Completá tu perfil', h('small', {}, [n, r ? `${r.positivos} pts` : null].filter(Boolean).join(' · '))),
      h('button', { class: 'salir', onclick: async () => { await sb.auth.signOut(); location.reload(); } }, 'Salir'));
  }
  function pedirPerfil() {
    const nombreGoogle = (usuario.user_metadata && (usuario.user_metadata.full_name || usuario.user_metadata.name)) || '';
    const form = h('form', {},
      h('h2', {}, '¡Bienvenido/a a Ramacontable!'),
      h('p', {}, 'Contanos un poco de vos. Esto se muestra junto a tus aportes (tu mail no).'),
      h('label', {}, 'Nombre a mostrar', h('input', { name: 'nombre', required: true, minlength: 2, maxlength: 60, value: nombreGoogle })),
      h('label', {}, '¿Cuál es tu situación?'),
      h('div', { class: 'ops' },
        h('label', { class: 'op' }, h('input', { type: 'radio', name: 'tipo', value: 'recibido', required: true }), 'Soy contador/a recibido/a'),
        h('label', { class: 'op' }, h('input', { type: 'radio', name: 'tipo', value: 'estudiante' }), 'Estoy estudiando la carrera'),
        h('label', { class: 'op' }, h('input', { type: 'radio', name: 'tipo', value: 'otro' }), 'No soy de la profesión')),
      h('label', { id: 'caja-avance', hidden: true }, '¿Qué porcentaje de la carrera tenés aprobado?', h('input', { name: 'avance', type: 'number', min: 0, max: 100, placeholder: 'Ej.: 60' })),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'newsletter', checked: true }), 'Quiero recibir la newsletter de los lunes (resumen semanal y vencimientos)'),
      h('p', { class: 'nota-chica' }, 'Al continuar aceptás los ', h('a', { href: 'terminos.html', target: '_blank' }, 'términos y la política de privacidad'), '.'),
      h('p', { class: 'error', id: 'err-perfil' }),
      h('button', { class: 'btn ancho' }, 'Listo'));
    form.addEventListener('change', () => { $('#caja-avance', form).hidden = form.tipo.value !== 'estudiante'; });
    form.addEventListener('submit', async ev => {
      ev.preventDefault();
      const nombre = form.nombre.value.trim();
      const err = revisarTexto(nombre); if (err) { $('#err-perfil', form).textContent = err; return; }
      const fila = { id: usuario.id, nombre, tipo: form.tipo.value, avance: form.tipo.value === 'estudiante' && form.avance.value !== '' ? Math.min(100, Math.max(0, +form.avance.value)) : null };
      const r1 = await sb.from('perfiles').upsert(fila);
      if (r1.error) { $('#err-perfil', form).textContent = mensajeError(r1.error); return; }
      await sb.from('preferencias').upsert({ id: usuario.id, email: usuario.email, newsletter: form.newsletter.checked, actualizado: new Date().toISOString() });
      perfil = fila; modal.dataset.fijo = ''; cerrarModal(); pintarSesion(); aviso('¡Listo! Ya podés participar.');
    });
    modal.dataset.fijo = '1';
    abrirModal(form, false);
  }

  // ---------- datos ----------
  async function cargarReputaciones() {
    const { data } = await sb.from('reputacion').select('*');
    reputaciones = {}; (data || []).forEach(r => { reputaciones[r.usuario] = r; });
  }
  function autorBloque(p, cuando) {
    const r = reputaciones[p.autor] || {};
    const per = p.perfiles || {};
    const n = nivel(r);
    return h('div', { class: 'autor' },
      h('b', {}, per.nombre || 'Usuario'),
      tipoTexto(per) ? h('span', { class: 'sello' }, tipoTexto(per)) : null,
      n ? h('span', { class: 'sello' }, n) : null,
      r.negativos > r.positivos ? h('span', { class: 'rep-neg' }, `(reputación negativa: ${r.positivos - r.negativos})`) : null,
      h('span', { class: 'cuando' }, hace(cuando)));
  }
  function botonesVoto(objeto, item, votos, nombres) {
    const cuenta = v => votos.filter(x => x.valor === v).length;
    const negs = votos.filter(x => x.valor === 'neg');
    const boton = (valor, texto) => {
      const clave = `${objeto}:${item.id}:${valor}`;
      return h('button', {
        class: misVotos.has(clave) ? 'on' : '', type: 'button',
        onclick: () => votar(objeto, item, valor, clave)
      }, `${texto} ${cuenta(valor) || ''}`.trim());
    };
    const caja = h('div', {},
      h('div', { class: 'votos' },
        boton('like', '👍 Me gusta'),
        objeto === 'paso' ? boton('sirvio', '💡 Me sirvió') : null,
        boton('neg', '👎')));
    if (negs.length) caja.append(h('p', { class: 'nota-chica' }, 'Votos negativos: ',
      ...negs.map((x, i) => [i ? ' · ' : '', `"${x.motivo}" (${nombres[x.autor] || 'usuario'})`])));
    return caja;
  }
  async function votar(objeto, item, valor, clave) {
    if (!exigirSesion()) return;
    if (item.autor === usuario.id) return aviso('No podés votar tus propios aportes.');
    if (misVotos.has(clave)) {
      await sb.from('votos').delete().match({ autor: usuario.id, objeto, objeto_id: item.id, valor });
      return cargarAportes();
    }
    if (valor === 'neg') {
      const f = h('form', {},
        h('h2', {}, 'Voto negativo'),
        h('p', {}, 'Contá el motivo. Lo van a poder leer todos, junto con tu nombre.'),
        h('select', { name: 'tipo' }, ['Respuesta incorrecta', 'Falta de respeto', 'Ofrece servicios / spam', 'Otro'].map(o => h('option', {}, o))),
        h('label', {}, 'Detalle', h('textarea', { name: 'detalle', rows: 2, maxlength: 250, placeholder: 'Ej.: la NR no lleva aportes jubilatorios según el acuerdo' })),
        h('p', { class: 'error' }), h('button', { class: 'btn ancho' }, 'Enviar voto negativo'));
      f.addEventListener('submit', async ev => {
        ev.preventDefault();
        const motivo = (f.tipo.value + (f.detalle.value.trim() ? ': ' + f.detalle.value.trim() : '')).slice(0, 300);
        const { error } = await sb.from('votos').insert({ objeto, objeto_id: item.id, valor, motivo });
        if (error) { $('.error', f).textContent = mensajeError(error); return; }
        cerrarModal(); cargarAportes();
      });
      return abrirModal(f);
    }
    const { error } = await sb.from('votos').insert({ objeto, objeto_id: item.id, valor });
    if (error) return aviso(mensajeError(error));
    cargarAportes();
  }

  async function cargarAportes() {
    if (!sb || !notaId) return;
    const [ps, os] = await Promise.all([
      sb.from('pasos').select('*, perfiles(nombre,tipo,avance)').eq('nota', notaId),
      sb.from('opiniones').select('*, perfiles(nombre,tipo,avance)').eq('nota', notaId).order('creado', { ascending: false }),
    ]);
    const pasos = ps.data || [], opiniones = os.data || [];
    const ids = { paso: pasos.map(p => p.id), opinion: opiniones.map(o => o.id) };
    let votos = [];
    if (ids.paso.length || ids.opinion.length) {
      const q = [];
      if (ids.paso.length) q.push(sb.from('votos').select('*').eq('objeto', 'paso').in('objeto_id', ids.paso));
      if (ids.opinion.length) q.push(sb.from('votos').select('*').eq('objeto', 'opinion').in('objeto_id', ids.opinion));
      (await Promise.all(q)).forEach(r => { votos = votos.concat(r.data || []); });
    }
    await cargarReputaciones();
    const nombres = {}; Object.values(reputaciones).forEach(r => { nombres[r.usuario] = r.nombre; });
    misVotos = new Set(usuario ? votos.filter(v => v.autor === usuario.id).map(v => `${v.objeto}:${v.objeto_id}:${v.valor}`) : []);
    const votosDe = (obj, id) => votos.filter(v => v.objeto === obj && v.objeto_id === id);
    const puntaje = id => votosDe('paso', id).reduce((s, v) => s + (v.valor === 'neg' ? -1 : v.valor === 'sirvio' ? 2 : 1), 0);
    pasos.sort((a, b) => puntaje(b.id) - puntaje(a.id) || new Date(a.creado) - new Date(b.creado));

    $('[data-n=pasos]').textContent = pasos.length;
    $('[data-n=opiniones]').textContent = opiniones.length;
    const NIV = { basico: 'Básico', intermedio: 'Intermedio', avanzado: 'Avanzado' };
    const lp = $('#lista-pasos'); lp.innerHTML = '';
    if (!pasos.length) lp.append(h('div', { class: 'vacio-caja' }, h('b', {}, 'Todavía nadie mostró cómo se aplica'), 'Sé el primero: ganás reputación y ayudás a colegas y estudiantes.'));
    pasos.forEach(p => {
      const cont = h('div', { class: 'contenido-paso' });
      cont.innerHTML = window.RCEditor ? RCEditor.limpiar(p.contenido) : '';
      cont.querySelectorAll('table').forEach(t => { const w = h('div', { class: 'tabla-scroll' }); t.replaceWith(w); w.append(t); });
      cont.querySelectorAll('img').forEach(i => { i.loading = 'lazy'; i.alt = i.alt || 'Imagen del paso a paso'; i.title = 'Tocá para ampliar'; i.addEventListener('click', () => ampliar(i.src)); });
      lp.append(h('div', { class: 'aporte' },
        autorBloque(p, p.creado),
        h('span', { class: 'nivel' }, NIV[p.nivel]),
        h('h4', {}, p.titulo),
        cont,
        h('div', { class: 'dato porque-caja' }, h('b', {}, '¿Por qué se hace así? '), p.porque),
        p.texto_pdf ? h('details', { class: 'texto-pdf' }, h('summary', {}, 'Ver el texto del PDF'), h('div', {}, p.texto_pdf)) : null,
        botonesVoto('paso', p, votosDe('paso', p.id), nombres)));
    });
    const lo = $('#lista-opiniones'); lo.innerHTML = '';
    if (!opiniones.length) lo.append(h('p', { class: 'ayuda' }, 'Todavía no hay opiniones.'));
    opiniones.forEach(o => lo.append(h('div', { class: 'aporte' }, autorBloque(o, o.creado), h('p', {}, o.texto), botonesVoto('opinion', o, votosDe('opinion', o.id), nombres))));
  }

  function ampliar(src) {
    abrirModal(h('div', { class: 'ampliada' }, h('p', { class: 'nota-chica' }, 'Podés hacer zoom con los dedos o con Ctrl + rueda del mouse.'), h('img', { src, alt: 'Página ampliada' })));
    modal.querySelector('.ventana').classList.add('ventana-ancha');
  }

  function formPaso() {
    if (!exigirSesion()) return;
    const ed = window.RCEditor; ed.configurar(cfg.url);
    let imgs = 0, textoPdf = '';
    const editor = h('div', { class: 'editor', contenteditable: 'true', 'data-vacio': 'Pegá acá tu liquidación o explicación (desde Excel o Word, mantiene el formato) o escribila directamente.' });
    const estado = h('p', { class: 'nota-chica', 'aria-live': 'polite' });
    const alFinal = html => { editor.insertAdjacentHTML('beforeend', html + '<p><br></p>'); editor.scrollTop = editor.scrollHeight; };
    const insertar = html => {
      editor.focus();
      const sel = window.getSelection();
      if (!sel.rangeCount || !editor.contains(sel.anchorNode)) return alFinal(html);
      // si se pega una tabla adentro de otra, va después de la tabla de afuera
      let nodo = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentNode, tabla = null;
      while (nodo && nodo !== editor) { if (nodo.nodeName === 'TABLE') tabla = nodo; nodo = nodo.parentNode; }
      if (tabla && /<(table|img)/i.test(html)) { tabla.insertAdjacentHTML('afterend', html + '<p><br></p>'); return; }
      document.execCommand('insertHTML', false, html);
    };
    const subirCanvas = async c => {
      if (imgs >= 15) throw new Error('Máximo 15 imágenes por paso a paso.');
      const blob = await ed.aJpg(c);
      const ruta = `${usuario.id}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.jpg`;
      const { error } = await sb.storage.from('pasos').upload(ruta, blob, { contentType: 'image/jpeg', upsert: false });
      if (error) throw error;
      imgs++;
      return sb.storage.from('pasos').getPublicUrl(ruta).data.publicUrl;
    };
    const conAviso = async (txt, fn) => {
      estado.textContent = txt;
      try { await fn(); estado.textContent = ''; } catch (e) { estado.textContent = (e && e.message && !e.message.includes('Failed')) ? e.message : 'No se pudo procesar. Probá copiando y pegando el contenido.'; }
    };
    editor.addEventListener('paste', ev => {
      ev.preventDefault();
      const dt = ev.clipboardData;
      const img = [...dt.files].find(f => /^image\//.test(f.type));
      if (img && !dt.getData('text/html')) {
        return conAviso('Subiendo la imagen…', async () => { const url = await subirCanvas(await ed.canvasDeArchivo(img)); insertar(ed.limpiar(`<p><img src="${url}"></p>`)); });
      }
      insertar(ed.desdePegado(dt));
    });
    editor.addEventListener('drop', ev => { if (ev.dataTransfer.files.length) { ev.preventDefault(); procesarArchivo(ev.dataTransfer.files[0]); } });
    const procesarArchivo = archivo => {
      const n = archivo.name.toLowerCase();
      if (archivo.size > 15 * 1024 * 1024) { estado.textContent = 'El archivo es muy grande (máximo 15 MB).'; return; }
      if (n.endsWith('.xlsx')) return conAviso('Convirtiendo la planilla…', async () => alFinal(await ed.xlsxAHtml(archivo)));
      if (n.endsWith('.docx')) return conAviso('Convirtiendo el documento…', async () => alFinal(await ed.docxAHtml(archivo)));
      if (n.endsWith('.pdf')) return conAviso('Convirtiendo el PDF en imágenes…', async () => {
        const { canvases, total, texto } = await ed.pdfACanvases(archivo);
        const prob = revisarTexto(texto);
        if (prob) throw new Error('No se puede usar este PDF: ' + prob.charAt(0).toLowerCase() + prob.slice(1) + ' Revisalo, sacá esos datos y volvé a exportarlo.');
        textoPdf = (textoPdf + '\n\n' + texto).trim().slice(0, 60000);
        for (const c of canvases) alFinal(ed.limpiar(`<p><img src="${await subirCanvas(c)}"></p>`));
        if (total > canvases.length) aviso(`Se agregaron las primeras ${canvases.length} páginas de ${total}.`);
      });
      if (/\.(png|jpe?g|webp)$/.test(n)) return conAviso('Subiendo la imagen…', async () => alFinal(ed.limpiar(`<p><img src="${await subirCanvas(await ed.canvasDeArchivo(archivo))}"></p>`)));
      estado.textContent = 'Formato no admitido. Usá Excel (.xlsx), Word (.docx), PDF o una imagen. Los .xls, .xlsm y .doc no se aceptan por seguridad: abrilos, copiá y pegá.';
    };
    const selector = h('input', { type: 'file', accept: '.xlsx,.docx,.pdf,.png,.jpg,.jpeg,.webp', hidden: true, onchange: () => { if (selector.files[0]) procesarArchivo(selector.files[0]); selector.value = ''; } });
    const selPdf = h('input', { type: 'file', accept: '.pdf', hidden: true, onchange: () => { if (selPdf.files[0]) procesarArchivo(selPdf.files[0]); selPdf.value = ''; } });
    const f = h('form', {},
      h('h2', {}, 'Mostrá cómo se aplica'),
      h('label', {}, 'Título del caso', h('input', { name: 'titulo', required: true, minlength: 5, maxlength: 140, placeholder: 'Ej.: Vendedor B, 5 años de antigüedad, octubre 2026' })),
      h('label', {}, 'Nivel', h('select', { name: 'nivel' }, h('option', { value: 'basico' }, 'Básico'), h('option', { value: 'intermedio' }, 'Intermedio'), h('option', { value: 'avanzado' }, 'Avanzado'))),
      h('label', {}, 'Tu paso a paso'),
      h('div', { class: 'subir-pdf' },
        h('button', { type: 'button', class: 'btn', onclick: () => selPdf.click() }, '📄 Subir PDF'),
        h('span', {}, 'Lo más fácil: guardá tu Excel o Word como PDF y subilo. Se ve en la página tal cual.'), selPdf),
      h('p', { class: 'nota-chica o-bien' }, 'O bien, pegá abajo desde Excel o Word (mantiene el formato), escribí directamente, o ',
        h('a', { href: '#', onclick: e => { e.preventDefault(); selector.click(); } }, 'elegí un Excel, Word o imagen'), '.', selector),
      editor,
      estado,
      h('label', {}, '¿Por qué se hace así? (obligatorio)', h('textarea', { name: 'porque', required: true, rows: 3, minlength: 20, maxlength: 2000, placeholder: 'Explicá la lógica: qué norma se aplica y por qué se calcula de esa forma. Así le sirve también a estudiantes.' })),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'sindatos', required: true }), 'Confirmo que no tiene datos reales de personas ni clientes (nombres, CUIL, DNI, sueldos reales).'),
      h('p', { class: 'error' }),
      h('button', { class: 'btn ancho' }, 'Publicar'));
    f.addEventListener('submit', async ev => {
      ev.preventDefault();
      const contenido = ed.limpiar(editor.innerHTML);
      const texto = editor.innerText.trim();
      if (texto.length < 10 && !contenido.includes('<img')) { $('.error', f).textContent = 'Falta el paso a paso: pegá o escribí el contenido.'; return; }
      const fila = { nota: notaId, titulo: f.titulo.value.trim(), nivel: f.nivel.value, contenido, porque: f.porque.value.trim(), sin_datos_reales: f.sindatos.checked, texto_pdf: textoPdf || null };
      const err = revisarTexto([fila.titulo, fila.porque, texto].join(' '));
      if (err) { $('.error', f).textContent = err; return; }
      const { error } = await sb.from('pasos').insert(fila);
      if (error) { $('.error', f).textContent = mensajeError(error); return; }
      cerrarModal(); aviso('¡Publicado! Gracias por aportar.'); cargarAportes();
    });
    abrirModal(f);
  }

  async function contadoresPortada() {
    const marcas = $$('[data-contador]'); if (!marcas.length) return;
    const slugs = marcas.map(m => m.dataset.contador);
    const { data } = sb ? await sb.from('pasos').select('nota').in('nota', slugs) : { data: [] };
    const c = {}; (data || []).forEach(p => { c[p.nota] = (c[p.nota] || 0) + 1; });
    marcas.forEach(m => { const n = c[m.dataset.contador] || 0; m.textContent = n ? `${n} paso a paso` : 'Sin paso a paso aún'; });
    $$('#esperando li').forEach(li => { const s = li.querySelector('a').getAttribute('href').replace('nota-', '').replace('.html#aplica', ''); if (c[s]) li.remove(); });
  }
  async function ranking() {
    if (!sb) return;
    await cargarReputaciones();
    const top = Object.values(reputaciones).filter(r => r.positivos > 0).sort((a, b) => b.positivos - a.positivos).slice(0, 5);
    if (!top.length) return;
    const ol = $('#ranking'); ol.innerHTML = '';
    top.forEach(r => ol.append(h('li', {}, h('b', {}, r.nombre), ` · ${nivel(r)} · ${r.positivos} pts`)));
    $('#destacados').hidden = false;
  }

  // ---------- eventos ----------
  $$('[data-ingresar]').forEach(b => b.addEventListener('click', ingresar));
  $$('[data-tab]').forEach(b => b.addEventListener('click', () => {
    $$('[data-tab]').forEach(x => x.setAttribute('aria-selected', x === b));
    $$('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== b.dataset.tab; });
  }));
  const bp = $('[data-nuevo-paso]'); if (bp) bp.addEventListener('click', formPaso);
  const fo = $('#form-opinion');
  if (fo) fo.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!exigirSesion()) return;
    const texto = fo.texto.value.trim();
    const err = revisarTexto(texto); if (err) return aviso(err);
    const { error } = await sb.from('opiniones').insert({ nota: notaId, texto });
    if (error) return aviso(mensajeError(error));
    fo.reset(); cargarAportes();
  });

  // ---------- arranque ----------
  async function iniciar() {
    if (window.RCEditor) RCEditor.configurar(cfg.url);
    if (!sb) { contadoresPortada(); return; }
    const { data } = await sb.auth.getSession();
    usuario = data.session ? data.session.user : null;
    if (usuario) {
      const r = await sb.from('perfiles').select('*').eq('id', usuario.id).maybeSingle();
      perfil = r.data || null;
    }
    await cargarReputaciones();
    pintarSesion();
    if (usuario && !perfil) pedirPerfil();
    contadoresPortada(); ranking(); cargarAportes();
  }
  iniciar();
})();
