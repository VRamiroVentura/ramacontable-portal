/* Ramacontable · lógica de la web (login, perfiles, opiniones, paso a paso y votos) */
(function () {
  const cfg = window.RC_CONFIG || {};
  const sb = (cfg.url && cfg.key && window.supabase) ? window.supabase.createClient(cfg.url, cfg.key) : null;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  let notaId = $('[data-nota]') ? $('[data-nota]').dataset.nota : null;
  if ($('[data-dinamica]')) { notaId = new URLSearchParams(location.search).get('n') || null; $('[data-nota]').dataset.nota = notaId || ''; }
  let usuario = null, perfil = null, reputaciones = {}, misVotos = new Set(), verTodasOp = false;

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
      h('p', {}, 'Con tu cuenta de Google podés subir explicaciones, opinar y votar. No guardamos contraseñas y tu mail no se muestra a nadie.'),
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
  function fechaHora(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' }) + ' ' + d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function accionesPropias(tipo, item) {
    if (!usuario || item.autor !== usuario.id) return null;
    return h('div', { class: 'propias' },
      h('button', { type: 'button', class: 'ico', title: 'Editar', 'aria-label': 'Editar', onclick: () => tipo === 'paso' ? formPaso(item) : editarOpinion(item) }, '✏️'),
      h('button', { type: 'button', class: 'ico borrar', title: 'Borrar', 'aria-label': 'Borrar', onclick: () => borrar(tipo, item) }, '🗑️'));
  }
  function borrar(tipo, item) {
    abrirModal(h('div', {},
      h('h2', {}, tipo === 'paso' ? '¿Borrar tu explicación?' : '¿Borrar tu opinión?'),
      h('p', {}, 'Se borra para siempre, junto con sus votos.'),
      h('div', { class: 'fila-btn' },
        h('button', { class: 'btn sec', onclick: cerrarModal }, 'Cancelar'),
        h('button', { class: 'btn peligro', onclick: async () => {
          const { data, error } = await sb.from(tipo === 'paso' ? 'pasos' : 'opiniones').delete().eq('id', item.id).select('id');
          cerrarModal(); if (error) return aviso(mensajeError(error));
          if (!data || !data.length) return aviso('No se pudo borrar. Avisale al administrador del portal.');
          aviso('Borrado.'); cargarAportes();
        } }, 'Sí, borrar'))));
  }
  function editarOpinion(o) {
    const f = h('form', {},
      h('h2', {}, 'Editar tu opinión'),
      h('textarea', { name: 'texto', rows: 4, maxlength: 1500, required: true }),
      h('p', { class: 'nota-chica' }, 'Se va a mostrar que la editaste y a qué hora.'),
      h('p', { class: 'error' }), h('button', { class: 'btn ancho' }, 'Guardar cambios'));
    f.texto.value = o.texto;
    f.addEventListener('submit', async ev => {
      ev.preventDefault();
      const texto = f.texto.value.trim(); const err = revisarTexto(texto); if (err) { $('.error', f).textContent = err; return; }
      const { data, error } = await sb.from('opiniones').update({ texto }).eq('id', o.id).select('id');
      if (error) { $('.error', f).textContent = mensajeError(error); return; }
      if (!data || !data.length) { $('.error', f).textContent = 'No se pudo guardar el cambio. Avisale al administrador del portal.'; return; }
      cerrarModal(); aviso('Opinión actualizada.'); cargarAportes();
    });
    abrirModal(f);
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
      h('span', { class: 'cuando' }, hace(cuando), p.editado ? h('em', { class: 'editado' }, ` · editado el ${fechaHora(p.editado)}`) : null));
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
    caja.querySelector('.votos button:last-child').classList.add('chico');
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
    const pasos = ps.data || [], opiniones = (os.data || []).sort((a, b) => new Date(b.creado) - new Date(a.creado));
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

    const combinado = !!$('.bloque-com');
    const setN = (k, v) => { const x = $(`[data-n=${k}]`); if (x) x.textContent = v; };
    setN('pasos', pasos.length); setN('opiniones', opiniones.length); setN('total', pasos.length + opiniones.length);
    const NIV = { basico: 'Básico', intermedio: 'Intermedio', avanzado: 'Avanzado' };
    const lp = $('#lista-pasos'); lp.innerHTML = '';
    if (!pasos.length && !combinado) lp.append(h('div', { class: 'vacio-caja' }, h('b', {}, 'Todavía nadie mostró cómo se aplica'), 'Sé el primero: ganás reputación y ayudás a colegas y estudiantes.'));
    pasos.forEach(p => {
      const cont = h('div', { class: 'contenido-paso' });
      cont.innerHTML = window.RCEditor ? RCEditor.limpiar(p.contenido) : '';
      cont.querySelectorAll('table').forEach(t => { const w = h('div', { class: 'tabla-scroll' }); t.replaceWith(w); w.append(t); });
      cont.querySelectorAll('img').forEach(i => { i.loading = 'lazy'; i.alt = i.alt || 'Imagen de la explicación'; i.title = 'Tocá para ampliar'; i.addEventListener('click', () => ampliar(i.src)); });
      lp.append(h('div', { class: 'aporte' },
        accionesPropias('paso', p),
        autorBloque(p, p.creado),
        combinado ? h('span', { class: 'nivel expl' }, 'Explicación') : null,
        h('span', { class: 'nivel' }, NIV[p.nivel]),
        h('h4', {}, p.titulo),
        cont,
        h('div', { class: 'dato porque-caja' }, h('b', {}, '¿Por qué se hace así? '), p.porque),
        p.texto_pdf ? h('details', { class: 'texto-pdf' }, h('summary', {}, 'Ver el texto del PDF'), h('div', {}, p.texto_pdf)) : null,
        botonesVoto('paso', p, votosDe('paso', p.id), nombres)));
    });
    const lo = $('#lista-opiniones'); lo.innerHTML = '';
    if (!opiniones.length && !(combinado && pasos.length)) lo.append(h('p', { class: 'ayuda' }, combinado ? 'Todavía no hay comentarios. ¡Sé el primero!' : 'Todavía no hay opiniones.'));
    const hijos = {}; opiniones.filter(o => o.responde).forEach(o => { (hijos[o.responde] = hijos[o.responde] || []).push(o); });
    const tops = opiniones.filter(o => !o.responde);
    // las preguntas sin responder quedan arriba, para que los colegas las vean primero
    tops.sort((a, b) => ((b.tipo === 'pregunta' && !hijos[b.id]) - (a.tipo === 'pregunta' && !hijos[a.id])) || new Date(b.creado) - new Date(a.creado));
    tops.forEach((o, i) => {
      const resp = (hijos[o.id] || []).sort((a, b) => new Date(a.creado) - new Date(b.creado));
      const caja = h('div', { class: 'aporte' + (o.tipo === 'pregunta' ? ' es-pregunta' : ''), hidden: i >= 2 && !verTodasOp },
        accionesPropias('opinion', o), autorBloque(o, o.creado),
        o.tipo === 'pregunta' ? h('span', { class: 'nivel preg' }, resp.length ? 'Pregunta · respondida' : 'Pregunta · sin responder') : null,
        h('p', {}, o.texto), botonesVoto('opinion', o, votosDe('opinion', o.id), nombres));
      if (resp.length) caja.append(h('div', { class: 'respuestas' }, ...resp.map(x => h('div', { class: 'aporte resp' }, accionesPropias('opinion', x), autorBloque(x, x.creado), h('p', {}, x.texto), botonesVoto('opinion', x, votosDe('opinion', x.id), nombres)))));
      const br = h('button', { type: 'button', class: 'btn sec chico' }, o.tipo === 'pregunta' ? 'Responder' : 'Responder');
      br.addEventListener('click', () => {
        if (!exigirSesion()) return;
        br.hidden = true;
        const f = h('form', { class: 'form-op form-resp' }, h('textarea', { name: 'texto', rows: 2, maxlength: 1500, required: true, placeholder: 'Tu respuesta…' }), h('button', { class: 'btn' }, 'Publicar respuesta'));
        f.addEventListener('submit', async ev => {
          ev.preventDefault();
          const texto = f.texto.value.trim(); const err = revisarTexto(texto); if (err) return aviso(err);
          const { error } = await sb.from('opiniones').insert({ nota: notaId, texto, tipo: 'respuesta', responde: o.id });
          if (error) return aviso(mensajeError(error));
          cargarAportes();
        });
        caja.append(f); f.texto.focus();
      });
      caja.append(br);
      lo.append(caja);
    });
    const vm = $('#ver-mas-op');
    if (vm) { vm.hidden = tops.length <= 2 || verTodasOp; vm.textContent = `Ver más ${combinado ? 'comentarios' : 'opiniones'} (${tops.length - 2})`; }
  }

  function ampliar(src) {
    abrirModal(h('div', { class: 'ampliada' }, h('p', { class: 'nota-chica' }, 'Podés hacer zoom con los dedos o con Ctrl + rueda del mouse.'), h('img', { src, alt: 'Página ampliada' })));
    modal.querySelector('.ventana').classList.add('ventana-ancha');
  }

  function formPaso(existente, inicial) {
    if (!exigirSesion()) return;
    const ed = window.RCEditor; ed.configurar(cfg.url);
    let imgs = 0, textoPdf = existente && existente.texto_pdf || '';
    const editor = h('div', { class: 'editor', contenteditable: 'true', 'data-vacio': 'Pegá acá tu liquidación o explicación (desde Excel o Word, mantiene el formato) o escribila directamente.' });
    if (inicial) editor.innerText = inicial;
    const estado = h('div', { class: 'estado', 'aria-live': 'polite', hidden: true });
    let procesando = false;
    const mostrar = (txt, tipo) => {
      estado.hidden = !txt; estado.className = 'estado ' + (tipo || ''); estado.textContent = txt || '';
      if (txt) estado.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };
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
      if (imgs >= 15) throw new Error('Máximo 15 imágenes por explicación.');
      const blob = await ed.aJpg(c);
      const ruta = `${usuario.id}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.jpg`;
      const { error } = await sb.storage.from('pasos').upload(ruta, blob, { contentType: 'image/jpeg', upsert: false });
      if (error) throw error;
      imgs++;
      return sb.storage.from('pasos').getPublicUrl(ruta).data.publicUrl;
    };
    const conAviso = async (txt, fn) => {
      mostrar('⏳ ' + txt, 'cargando'); procesando = true;
      try { await fn(); mostrar('✅ Listo, ya está en tu explicación. Revisalo abajo antes de publicar.', 'ok'); }
      catch (e) { mostrar('⚠️ ' + ((e && e.message && !/Failed|fetch|import/i.test(e.message)) ? e.message : 'No se pudo procesar el archivo. Probá exportarlo de nuevo a PDF o copiá y pegá el contenido.'), 'error'); }
      finally { procesando = false; }
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
      if (archivo.size > 15 * 1024 * 1024) { mostrar('⚠️ El archivo es muy grande (máximo 15 MB).', 'error'); return; }
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
      mostrar('⚠️ Formato no admitido. Usá Excel (.xlsx), Word (.docx), PDF o una imagen. Los .xls, .xlsm y .doc no se aceptan por seguridad: abrilos, copiá y pegá.', 'error');
    };
    const selector = h('input', { type: 'file', accept: '.xlsx,.docx,.pdf,.png,.jpg,.jpeg,.webp', hidden: true, onchange: () => { if (selector.files[0]) procesarArchivo(selector.files[0]); selector.value = ''; } });
    const selPdf = h('input', { type: 'file', accept: '.pdf', hidden: true, onchange: () => { if (selPdf.files[0]) procesarArchivo(selPdf.files[0]); selPdf.value = ''; } });
    const f = h('form', {},
      h('h2', {}, existente ? 'Editar tu explicación' : 'Explicá cómo se aplica'),
      existente ? h('p', { class: 'nota-chica' }, 'Se va a mostrar que lo editaste y a qué hora.') : null,
      h('label', {}, 'Título del caso', h('input', { name: 'titulo', required: true, minlength: 5, maxlength: 140, placeholder: 'Ej.: Vendedor B, 5 años de antigüedad, octubre 2026' })),
      h('label', {}, 'Nivel', h('select', { name: 'nivel' }, h('option', { value: 'basico' }, 'Básico'), h('option', { value: 'intermedio' }, 'Intermedio'), h('option', { value: 'avanzado' }, 'Avanzado'))),
      h('label', {}, 'Tu explicación'),
      h('div', { class: 'subir-pdf' },
        h('button', { type: 'button', class: 'btn', onclick: () => selPdf.click() }, '📄 Subir PDF'),
        h('span', {}, 'Lo más fácil: guardá tu Excel o Word como PDF y subilo. Se ve en la página tal cual.'), selPdf),
      estado,
      h('p', { class: 'nota-chica o-bien' }, 'O bien, pegá abajo desde Excel o Word (mantiene el formato), escribí directamente, o ',
        h('a', { href: '#', onclick: e => { e.preventDefault(); selector.click(); } }, 'elegí un Excel, Word o imagen'), '.', selector),
      editor,
      h('label', {}, '¿Por qué se hace así? (obligatorio)', h('textarea', { name: 'porque', required: true, rows: 3, minlength: 20, maxlength: 2000, placeholder: 'Explicá la lógica: qué norma se aplica y por qué se calcula de esa forma. Así le sirve también a estudiantes.' })),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'sindatos', required: true }), 'Confirmo que no tiene datos reales de personas ni clientes (nombres, CUIL, DNI, sueldos reales).'),
      h('p', { class: 'error' }),
      h('button', { class: 'btn ancho' }, 'Publicar'));
    f.addEventListener('submit', async ev => {
      ev.preventDefault();
      if (procesando) { $('.error', f).textContent = 'Esperá a que termine de procesar el archivo.'; return; }
      const contenido = ed.limpiar(editor.innerHTML);
      const texto = editor.innerText.trim();
      if (texto.length < 10 && !contenido.includes('<img')) { $('.error', f).textContent = 'Falta la explicación: pegá o escribí el contenido.'; return; }
      const fila = { nota: notaId, titulo: f.titulo.value.trim(), nivel: f.nivel.value, contenido, porque: f.porque.value.trim(), sin_datos_reales: f.sindatos.checked, texto_pdf: textoPdf || null };
      const err = revisarTexto([fila.titulo, fila.porque, texto].join(' '));
      if (err) { $('.error', f).textContent = err; return; }
      if (existente) { delete fila.nota; }
      const { data, error } = existente ? await sb.from('pasos').update(fila).eq('id', existente.id).select('id') : await sb.from('pasos').insert(fila).select('id');
      if (error) { $('.error', f).textContent = mensajeError(error); return; }
      if (!data || (Array.isArray(data) && !data.length)) { $('.error', f).textContent = 'No se pudo guardar. Avisale al administrador del portal.'; return; }
      cerrarModal(); aviso(existente ? 'Cambios guardados.' : '¡Publicado! Gracias por aportar.'); cargarAportes();
    });
    if (existente) {
      f.titulo.value = existente.titulo; f.nivel.value = existente.nivel; f.porque.value = existente.porque;
      editor.innerHTML = ed.limpiar(existente.contenido); imgs = (existente.contenido.match(/<img/g) || []).length;
      f.sindatos.checked = true;
      $('button.btn.ancho', f).textContent = 'Guardar cambios';
    }
    abrirModal(f);
  }

  async function contadoresPortada() {
    const marcas = $$('[data-contador]'); if (!marcas.length) return;
    const slugs = marcas.map(m => m.dataset.contador);
    const [ps, os] = sb ? await Promise.all([sb.from('pasos').select('nota').in('nota', slugs), sb.from('opiniones').select('nota').in('nota', slugs)]) : [{ data: [] }, { data: [] }];
    const c = {}; [].concat(ps.data || [], os.data || []).forEach(p => { c[p.nota] = (c[p.nota] || 0) + 1; });
    marcas.forEach(m => { const n = c[m.dataset.contador] || 0; m.textContent = n ? `${n} ${n === 1 ? 'comentario' : 'comentarios'}` : 'Sé el primero en comentar'; });
    $$('#esperando li').forEach(li => { const s = li.querySelector('a').getAttribute('href').replace('nota-', '').replace('.html#aplica', ''); if (c[s]) li.remove(); });
  }
  async function ranking() {
    if (!sb) return;
    await cargarReputaciones();
    const top = Object.values(reputaciones).filter(r => r.positivos > 0).sort((a, b) => b.positivos - a.positivos).slice(0, 5);
    if (top.length < 5) return; // «Destacados de la comunidad» aparece recién con 5 aportantes o más
    const ol = $('#ranking'); if (!ol) return; ol.innerHTML = '';
    top.forEach(r => ol.append(h('li', {}, h('b', {}, r.nombre), ` · ${nivel(r)} · ${r.positivos} pts`)));
    $('#destacados').hidden = false;
  }

  // ---------- notas: versión al día y herramientas del administrador ----------
  let esAdmin = false;
  const SECC = { sueldos: 'Sueldos', impuestos: 'Impuestos', profesion: 'Profesión' };
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const fechaLarga = iso => { const [a, m, d] = String(iso).slice(0, 10).split('-').map(Number); return `${d} de ${MESES[m - 1]} de ${a}`; };
  function bloquesAHtml(cuerpo) {
    const E = window.RCEditor ? RCEditor.esc : (s => s);
    return (cuerpo || []).map(b => {
      if (b.h) return `<h2>${E(b.h)}</h2>`;
      if (b.p) return `<p>${E(b.p)}</p>`;
      if (b.tabla && b.tabla.length) return '<table><thead><tr>' + b.tabla[0].map(c => `<th>${E(c)}</th>`).join('') + '</tr></thead><tbody>' +
        b.tabla.slice(1).map(f => '<tr>' + f.map(c => `<td>${E(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
      if (b.html) return b.html;
      return '';
    }).join('');
  }
  function pintarNota(n) {
    const caja = $('.nota-contenido'); if (!caja) return;
    caja.innerHTML = '';
    if (n.estado === 'borrada' && !esAdmin) { caja.append(h('div', { class: 'vacio-caja' }, h('b', {}, 'Esta nota fue retirada'), 'Ya no está disponible.')); return; }
    const cuerpo = h('div', {}); cuerpo.innerHTML = RCEditor.limpiar(bloquesAHtml(n.cuerpo));
    cuerpo.querySelectorAll('table').forEach(t => { const w = h('div', { class: 'tabla' }); t.replaceWith(w); w.append(t); });
    caja.append(...[
      h('p', { class: 'miga' }, h('a', { href: `${n.seccion}.html` }, SECC[n.seccion] || '')),
      h('p', { class: 'ante' }, n.antetitulo || ''),
      h('h1', {}, n.titulo),
      h('p', { class: 'firma' }, `Redacción Ramacontable · ${fechaLarga(n.fecha)}`),
      n.actualiza ? h('p', { class: 'actualiza' }, 'Esta nota actualiza a: ', h('a', { href: `nota-${n.actualiza}.html` }, 'la nota anterior sobre el tema')) : null,
      h('div', { class: 'encorto' }, h('b', {}, 'En corto'), h('p', {}, n.encorto || '')),
      cuerpo,
      n.fuente ? h('p', { class: 'fuente' }, h('b', {}, 'Fuente: '), n.fuente) : null,
      h('p', { class: 'aviso' }, 'Información de carácter general. Se recomienda verificar siempre en las fuentes oficiales. Cada profesional es responsable de su aplicación. ' +
        (n.verificada ? 'Elaborada con fuentes oficiales.' : 'Pendiente de verificación con fuente oficial.'))].filter(Boolean));
    document.title = `${n.titulo} | Ramacontable`;
  }
  function barraAdmin(n) {
    const caja = $('.nota-contenido'); if (!caja || !esAdmin) return;
    const est = { publicada: 'Publicada', revision: 'Para revisar (no publicada)', borrada: 'Borrada (no se ve)' }[n.estado];
    const barra = h('div', { class: 'barra-admin' },
      h('span', {}, h('b', {}, 'Administrador · '), est, n.editado_por ? ` · editada por ${n.editado_por}` : ''),
      h('div', {},
        n.estado !== 'publicada' ? h('button', { class: 'btn', onclick: () => cambiarEstado(n, 'publicada') }, '✅ Publicar') : null,
        h('button', { class: 'btn sec', onclick: () => editarNota(n) }, '✏️ Editar'),
        n.estado !== 'borrada' ? h('button', { class: 'btn sec', onclick: () => confirmarBorrar(n) }, '🗑️ Borrar') : null));
    if (n.motivo_revision && n.estado === 'revision') {
      // 🔴 = datos que pueden arruinar la nota: se muestran uno por línea, con qué chequear
      const lineas = String(n.motivo_revision).split('\n').filter(Boolean);
      const grave = lineas[0].startsWith('🔴');
      barra.append(h('div', { class: 'motivo' + (grave ? ' motivo-grave' : '') },
        h('b', {}, grave ? lineas[0] : 'Para revisar'),
        h('ul', {}, ...(grave ? lineas.slice(1) : lineas[0].split('; ')).map(t => h('li', {}, t))),
        h('p', { class: 'ayuda' }, 'Si está bien, tocá ✅ Publicar. Si hay que corregir, ✏️ Editar.')));
    }
    caja.prepend(barra);
  }
  async function cambiarEstado(n, estado) {
    const { data, error } = await sb.from('notas').update({ estado }).eq('slug', n.slug).select('*');
    if (error || !data || !data.length) return aviso('No se pudo guardar. ' + (error ? mensajeError(error) : ''));
    const ajuste = String(n.slug).startsWith('ajuste-');
    aviso(ajuste ? (estado === 'publicada' ? 'Ajuste aprobado: la fábrica lo aplica a la guía en su próxima vuelta (no se publica como nota).' : 'Ajuste borrado: no se va a aplicar.')
      : estado === 'publicada' ? 'Nota publicada. Aparece en la portada en la próxima actualización (hasta 1 hora).' : 'Nota borrada.');
    cargarNota();
  }
  function confirmarBorrar(n) {
    abrirModal(h('div', {}, h('h2', {}, '¿Borrar esta nota?'), h('p', {}, 'Deja de verse en el portal. Si te arrepentís, la podés volver a publicar desde Administración.'),
      h('div', { class: 'fila-btn' }, h('button', { class: 'btn sec', onclick: cerrarModal }, 'Cancelar'),
        h('button', { class: 'btn peligro', onclick: () => { cerrarModal(); cambiarEstado(n, 'borrada'); } }, 'Sí, borrar'))));
  }
  function editarNota(n) {
    const editor = h('div', { class: 'editor', contenteditable: 'true' });
    editor.innerHTML = RCEditor.limpiar(bloquesAHtml(n.cuerpo));
    editor.addEventListener('paste', ev => { ev.preventDefault(); document.execCommand('insertHTML', false, RCEditor.desdePegado(ev.clipboardData)); });
    const f = h('form', {},
      h('h2', {}, 'Editar nota'),
      h('label', {}, 'Sección', h('select', { name: 'seccion' }, Object.entries(SECC).map(([k, v]) => h('option', { value: k }, v)))),
      h('label', {}, 'Antetítulo', h('input', { name: 'antetitulo', maxlength: 120 })),
      h('label', {}, 'Título', h('input', { name: 'titulo', required: true, minlength: 5, maxlength: 200 })),
      h('label', {}, 'Dato destacado (opcional)', h('input', { name: 'dato', maxlength: 40 })),
      h('label', {}, 'En corto', h('textarea', { name: 'encorto', rows: 3, maxlength: 600 })),
      h('label', {}, 'Cuerpo de la nota'), editor,
      h('label', {}, 'Fuente', h('input', { name: 'fuente', maxlength: 300 })),
      h('p', { class: 'error' }), h('button', { class: 'btn ancho' }, 'Guardar cambios'));
    ['seccion', 'antetitulo', 'titulo', 'dato', 'encorto', 'fuente'].forEach(k => { f[k].value = n[k] || ''; });
    f.addEventListener('submit', async ev => {
      ev.preventDefault();
      const cambios = { seccion: f.seccion.value, antetitulo: f.antetitulo.value.trim(), titulo: f.titulo.value.trim(), dato: f.dato.value.trim() || null,
        encorto: f.encorto.value.trim(), fuente: f.fuente.value.trim(), cuerpo: [{ html: RCEditor.limpiar(editor.innerHTML) }] };
      const { data, error } = await sb.from('notas').update(cambios).eq('slug', n.slug).select('*');
      if (error || !data || !data.length) { $('.error', f).textContent = 'No se pudo guardar. ' + (error ? mensajeError(error) : ''); return; }
      cerrarModal(); aviso('Nota actualizada. El cambio ya se ve en esta página.'); cargarNota();
    });
    abrirModal(f);
  }
  async function cargarNota() {
    if (!sb || !notaId) return;
    const art = $('[data-nota]');
    const { data } = await sb.from('notas').select('*').eq('slug', notaId).maybeSingle();
    const dinamica = art && art.dataset.dinamica;
    if (!data) {
      if (dinamica) $('.nota-contenido').innerHTML = '<div class="vacio-caja"><b>No encontramos esta nota</b>Puede que se haya retirado.</div>';
      return;
    }
    const construida = new Date(cfg.build || 0);
    if (dinamica || data.estado !== 'publicada' || new Date(data.actualizado) > construida || esAdmin) pintarNota(data);
    barraAdmin(data);
    if (dinamica && (data.estado === 'publicada' || esAdmin)) { $('#opiniones').hidden = false; if ($('#aplica')) $('#aplica').hidden = false; }
  }
  // ---------- contador de visitas (sin cookies: solo cuenta, no identifica a nadie) ----------
  // días en hora de Argentina (igual que el servidor)
  const diaAR = atras => new Date(Date.now() - 3 * 3600000 - atras * 86400000).toISOString().slice(0, 10);
  function contarVisita() {
    try {
      if (!sb || esAdmin || navigator.webdriver || /bot|crawl|spider|slurp|lighthouse|headless|preview/i.test(navigator.userAgent)) return;
      const hoy = diaAR(0);
      let nuevo = false;
      try { nuevo = localStorage.getItem('rc_dia') !== hoy; localStorage.setItem('rc_dia', hoy); } catch (e) { /* navegación privada */ }
      let origen = new URLSearchParams(location.search).get('utm_source') || '';
      if (!origen && document.referrer) {
        const h = new URL(document.referrer).hostname.replace(/^(www|l|lm|m|mobile)\./, '');
        if (h && h !== location.hostname.replace(/^www\./, '')) origen = h;
      }
      sb.rpc('sumar_visita', { p_ruta: location.pathname.replace(/^\//, '') || 'index.html', p_nuevo: nuevo, p_origen: origen.slice(0, 60) }).then(r => { if (r && r.error) console.warn('Contador:', r.error.message); }, () => {});
    } catch (e) { /* el contador nunca rompe la página */ }
  }
  async function estadisticas() {
    const caja = $('#admin-estadisticas'); if (!caja || !esAdmin) return;
    const desde = diaAR(29);
    const [v, o] = await Promise.all([
      sb.from('visitas').select('dia,ruta,vistas,visitantes').gte('dia', desde).limit(10000),
      sb.from('visitas_origen').select('dia,origen,n').gte('dia', desde).limit(5000)]);
    const filas = v.data || [], orig = o.data || [];
    const hoy = diaAR(0), hace7 = diaAR(6);
    const suma = (lista, campo, f = () => true) => lista.filter(f).reduce((s, x) => s + x[campo], 0);
    const porDia = {}; filas.forEach(x => { porDia[x.dia] = (porDia[x.dia] || 0) + x.vistas; });
    const dias = []; for (let i = 29; i >= 0; i--) { const d = diaAR(i); dias.push([d, porDia[d] || 0]); }
    const max = Math.max(1, ...dias.map(d => d[1]));
    const top = (lista, clave, campo) => Object.entries(lista.reduce((m, x) => { m[x[clave]] = (m[x[clave]] || 0) + x[campo]; return m; }, {})).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const E = RCEditor.esc;
    caja.innerHTML = `<h2>Visitas</h2>
      <div class="res-top"><div><span>Hoy</span><b>${suma(filas, 'vistas', x => x.dia === hoy)}</b></div><div><span>Últimos 7 días</span><b>${suma(filas, 'vistas', x => x.dia >= hace7)}</b></div><div class="neto"><span>Últimos 30 días</span><b>${suma(filas, 'vistas')}</b></div></div>
      <p class="ayuda">Visitantes distintos por día (aprox.): hoy ${suma(filas, 'visitantes', x => x.dia === hoy)} · 30 días ${suma(filas, 'visitantes')}. No se cuentan tus visitas de administrador ni los robots.</p>
      <div class="barras">${dias.map(([d, n]) => `<div title="${d.slice(8)}/${d.slice(5, 7)}: ${n}"><i style="height:${Math.round(n / max * 100)}%"></i></div>`).join('')}</div>
      <div class="fila2"><div><h3>Páginas más vistas</h3><table class="tabla-desc"><tbody>${top(filas, 'ruta', 'vistas').map(([r, n]) => `<tr><td><a href="${E(r)}">${E(r.replace('.html', ''))}</a></td><td>${n}</td></tr>`).join('') || '<tr><td>Sin datos todavía</td></tr>'}</tbody></table></div>
      <div><h3>De dónde llegan</h3><table class="tabla-desc"><tbody>${top(orig, 'origen', 'n').map(([r, n]) => `<tr><td>${E(r)}</td><td>${n}</td></tr>`).join('') || '<tr><td>Sin datos todavía (o entraron directo)</td></tr>'}</tbody></table></div></div>`;
  }
  async function panelAdmin() {
    const caja = $('#admin-lista'); if (!caja) return;
    if (!esAdmin) { caja.innerHTML = '<p class="ayuda">Ingresá con tu cuenta de administrador para ver esta página.</p>'; return; }
    const { data } = await sb.from('notas').select('slug,titulo,estado,fecha,seccion,motivo_revision').order('fecha', { ascending: false }).limit(200);
    const filas = (data || []).sort((a, b) => (a.estado === 'revision' ? -1 : 0) - (b.estado === 'revision' ? -1 : 0));
    caja.innerHTML = '';
    const cv = await sb.from('convenios').select('slug,nombre,motivo_propuesta,propuesta').not('propuesta', 'is', null);
    (cv.data || []).forEach(c => caja.append(h('a', { class: 'fila-admin', href: `escala-${c.slug}.html` },
      h('span', { class: 'est est-revision' }, '🟡 Escala para revisar'), h('b', {}, c.nombre), h('small', {}, c.motivo_propuesta || ''))));
    if (!filas.length) { caja.append(h('p', { class: 'ayuda' }, 'Todavía no hay notas en la base.')); return; }
    const EST = { publicada: '✅ Publicada', revision: '🟡 Para revisar', borrada: '🗑️ Borrada' };
    filas.forEach(n => caja.append(h('a', { class: 'fila-admin', href: n.estado === 'publicada' ? `nota-${n.slug}.html` : `nota.html?n=${n.slug}` },
      h('span', { class: 'est est-' + n.estado }, n.estado === 'revision' && String(n.motivo_revision || '').startsWith('🔴') ? '🔴 Revisar datos' : EST[n.estado]), h('b', {}, n.titulo), h('small', {}, `${fechaLarga(n.fecha)} · ${SECC[n.seccion] || ''}`),
      n.estado === 'revision' && n.motivo_revision ? h('small', { class: 'motivo-corto' }, String(n.motivo_revision).split('\n').slice(0, 2).join(' · ')) : null)));
  }

  // ---------- convenios: escala al día y edición del administrador ----------
  const convSlug = $('[data-convenio]') ? $('[data-convenio]').dataset.convenio : null;
  function tablaHtml(t) {
    if (!t || !t.length) return '';
    const E = RCEditor.esc;
    return '<div class="tabla"><table><thead><tr>' + t[0].map(c => `<th>${E(c)}</th>`).join('') + '</tr></thead><tbody>' +
      t.slice(1).map(f => '<tr>' + f.map(c => `<td>${E(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';
  }
  function pintarConvenio(c) {
    const caja = $('.nota-contenido'); if (!caja) return;
    const E = RCEditor.esc, esc = c.escala || {};
    const sec = (t, b) => (b && b.length) ? `<h2>${t}</h2>` + bloquesAHtml(b) : '';
    const escala = (esc.tabla && esc.tabla.length) || esc.aclaraciones
      ? `<p class="periodo"><b>Período:</b> ${E(esc.periodo || '')}${esc.vigencia ? ` · <b>Vigencia:</b> ${E(esc.vigencia)}` : ''}</p>` + tablaHtml(esc.tabla) + (esc.aclaraciones ? `<p class="ayuda">${E(esc.aclaraciones)}</p>` : '')
      : '<div class="vacio-caja"><b>Escala pendiente de carga</b>Se actualiza automáticamente con el próximo acuerdo salarial publicado.</div>';
    const qs = (c.preguntas || []).length ? '<section class="faq"><h2>Preguntas frecuentes</h2>' + c.preguntas.map(q => `<details><summary>${E(q.p)}</summary><p>${E(q.r)}</p></details>`).join('') + '</section>' : '';
    const hist = (c.historial || []).length ? '<h2>Historial de escalas</h2><ul class="historial">' + c.historial.slice().reverse().map(h => `<li><b>${E(h.periodo || '')}</b>${h.nota ? ` · <a href="nota-${E(h.nota)}.html">ver nota</a>` : ''}</li>`).join('') + '</ul>' : '';
    const html = `<p class="miga"><a href="sueldos.html">Sueldos</a> / <a href="convenios.html">Convenios</a></p>
      <p class="ante">${E(c.cct)} | ${E(c.partes)}</p><h1>Escala salarial ${E(c.nombre)}${esc.periodo ? ' ' + E(esc.periodo) : ''}</h1>
      <p class="firma">Redacción Ramacontable · Actualizado ${fechaLarga(String(c.actualizado).slice(0, 10))}</p>
      <div class="encorto"><b>Quiénes están comprendidos</b><p>${E(c.descripcion || '')}</p></div>
      <h2>Escala vigente</h2>${escala}${sec('Qué cambió con el último acuerdo', c.novedades)}${sec('Cómo se calcula', c.calculo)}
      ${sec('Sumas no remunerativas: aportes y contribuciones', c.nr)}${sec('Cómo figura en el recibo', c.recibo)}${qs}${hist}
      ${c.fuente ? `<p class="fuente"><b>Fuente:</b> ${E(c.fuente)}</p>` : ''}
      <p class="aviso">Información de carácter general. Se recomienda verificar siempre en el acuerdo homologado y en las fuentes oficiales. Cada profesional es responsable de su aplicación.</p>`;
    caja.innerHTML = DOMPurify.sanitize(html, { ALLOWED_TAGS: ['p','a','b','strong','i','em','h1','h2','h3','ul','ol','li','div','section','details','summary','table','thead','tbody','tr','th','td','br','small','span'], ALLOWED_ATTR: ['class','href'], ALLOWED_URI_REGEXP: /^(?:https:\/\/|[a-z0-9-]+\.html)/i });
  }
  function editorTabla(t) {
    const tabla = h('table', { class: 'tabla-edit' });
    const filas = (t && t.length) ? t : [['Categoría', 'Básico'], ['', '']];
    filas.forEach((f, i) => { const tr = h('tr', {}); f.forEach(c => tr.append(h(i ? 'td' : 'th', { contenteditable: 'true' }, c))); tabla.append(tr); });
    tabla.addEventListener('paste', ev => {
      const txt = ev.clipboardData.getData('text/plain');
      if (!txt.includes('\t')) return;
      ev.preventDefault();
      const nuevas = txt.replace(/\r/g, '').split('\n').filter(Boolean).map(f => f.split('\t'));
      tabla.innerHTML = '';
      nuevas.forEach((f, i) => { const tr = h('tr', {}); f.forEach(c => tr.append(h(i ? 'td' : 'th', { contenteditable: 'true' }, c.trim()))); tabla.append(tr); });
    });
    return tabla;
  }
  const leerTabla = tabla => [...tabla.querySelectorAll('tr')].map(tr => [...tr.children].map(td => td.textContent.trim())).filter(f => f.some(Boolean));
  function editarConvenio(c) {
    const esc = c.escala || {};
    const tabla = editorTabla(esc.tabla);
    const nov = h('div', { class: 'editor', contenteditable: 'true' }); nov.innerHTML = RCEditor.limpiar(bloquesAHtml(c.novedades));
    const f = h('form', {},
      h('h2', {}, `Editar escala · ${c.nombre}`),
      h('label', {}, 'Período', h('input', { name: 'periodo', maxlength: 80, placeholder: 'Ej.: Noviembre 2026' })),
      h('label', {}, 'Vigencia', h('input', { name: 'vigencia', maxlength: 120 })),
      h('label', {}, 'Escala (podés pegar una tabla copiada de Excel)'),
      h('div', { class: 'tabla-scroll' }, tabla),
      h('div', { class: 'fila-btn', style: 'justify-content:flex-start' },
        h('button', { type: 'button', class: 'btn sec', onclick: () => { const n = tabla.rows[0] ? tabla.rows[0].cells.length : 2; const tr = h('tr', {}); for (let i = 0; i < n; i++) tr.append(h('td', { contenteditable: 'true' }, '')); tabla.append(tr); } }, '+ Fila'),
        h('button', { type: 'button', class: 'btn sec', onclick: () => [...tabla.rows].forEach((tr, i) => tr.append(h(i ? 'td' : 'th', { contenteditable: 'true' }, ''))) }, '+ Columna')),
      h('label', {}, 'Aclaraciones de la escala', h('textarea', { name: 'aclaraciones', rows: 2, maxlength: 800 })),
      h('label', {}, 'Qué cambió con el último acuerdo'), nov,
      h('label', {}, 'Fuente', h('input', { name: 'fuente', maxlength: 300 })),
      h('p', { class: 'error' }), h('button', { class: 'btn ancho' }, 'Guardar'));
    f.periodo.value = esc.periodo || ''; f.vigencia.value = esc.vigencia || ''; f.aclaraciones.value = esc.aclaraciones || ''; f.fuente.value = c.fuente || '';
    f.addEventListener('submit', async ev => {
      ev.preventDefault();
      const cambios = { escala: { periodo: f.periodo.value.trim(), vigencia: f.vigencia.value.trim(), tabla: leerTabla(tabla), aclaraciones: f.aclaraciones.value.trim() },
        novedades: [{ html: RCEditor.limpiar(nov.innerHTML) }], fuente: f.fuente.value.trim() };
      const hist = (c.historial || []).slice();
      if (cambios.escala.periodo && !hist.some(x => x.periodo === cambios.escala.periodo)) hist.push({ periodo: cambios.escala.periodo, fecha: new Date().toISOString().slice(0, 10), nota: null });
      cambios.historial = hist;
      const { data, error } = await sb.from('convenios').update(cambios).eq('slug', c.slug).select('*');
      if (error || !data || !data.length) { $('.error', f).textContent = 'No se pudo guardar. ' + (error ? mensajeError(error) : ''); return; }
      cerrarModal(); aviso('Escala guardada. Ya se ve en esta página.'); cargarConvenio();
    });
    abrirModal(f);
    modal.querySelector('.ventana').classList.add('ventana-ancha');
  }
  async function decidirPropuesta(c, aplicar) {
    const cambios = aplicar ? Object.assign({}, c.propuesta, { propuesta: null, motivo_propuesta: null }) : { propuesta: null, motivo_propuesta: null };
    const { data, error } = await sb.from('convenios').update(cambios).eq('slug', c.slug).select('*');
    if (error || !data || !data.length) return aviso('No se pudo guardar. ' + (error ? mensajeError(error) : ''));
    aviso(aplicar ? 'Actualización aplicada.' : 'Propuesta descartada.'); cargarConvenio();
  }
  async function cargarConvenio() {
    if (!sb || !convSlug) return;
    const { data } = await sb.from('convenios').select('*').eq('slug', convSlug).maybeSingle();
    if (!data) return;
    if (new Date(data.actualizado) > new Date(cfg.build || 0) || esAdmin) pintarConvenio(data);
    if (!esAdmin) return;
    const caja = $('.nota-contenido');
    const barra = h('div', { class: 'barra-admin' },
      h('span', {}, h('b', {}, 'Administrador · '), 'Convenio', data.editado_por ? ` · editado por ${data.editado_por}` : ''),
      h('div', {}, h('button', { class: 'btn sec', onclick: () => editarConvenio(data) }, '✏️ Editar escala')));
    if (data.propuesta) {
      const p = data.propuesta, pe = (p.escala || {});
      barra.append(h('div', { class: 'propuesta' },
        h('p', { class: 'motivo' }, `La fábrica propone actualizar a «${pe.periodo || 'nuevo período'}», pero encontró dudas: ${data.motivo_propuesta || ''}`),
        (() => { const d = h('div', {}); d.innerHTML = RCEditor.limpiar(tablaHtml(pe.tabla)); return d; })(),
        h('div', { class: 'fila-btn' },
          h('button', { class: 'btn sec', onclick: () => decidirPropuesta(data, false) }, 'Descartar'),
          h('button', { class: 'btn', onclick: () => decidirPropuesta(data, true) }, '✅ Aplicar actualización'))));
    }
    caja.prepend(barra);
  }

  // ---------- eventos ----------
  $$('[data-ingresar]').forEach(b => b.addEventListener('click', ingresar));
  $$('[data-tab]').forEach(b => b.addEventListener('click', () => {
    $$('[data-tab]').forEach(x => x.setAttribute('aria-selected', x === b));
    $$('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== b.dataset.tab; });
  }));
  const vmo = $('#ver-mas-op'); if (vmo) vmo.addEventListener('click', () => { verTodasOp = true; $$('#lista-opiniones .aporte').forEach(x => { x.hidden = false; }); vmo.hidden = true; });
  const bp = $('[data-nuevo-paso]'); if (bp) bp.addEventListener('click', () => formPaso());
  const fo = $('#form-opinion');
  if (fo) fo.addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!exigirSesion()) return;
    const texto = fo.texto.value.trim();
    const tipo = fo.tipo ? fo.tipo.value : 'comentario';
    if (tipo === 'explicacion') { formPaso(null, texto); fo.reset(); return; }
    const err = revisarTexto(texto); if (err) return aviso(err);
    const { error } = await sb.from('opiniones').insert(tipo === 'pregunta' ? { nota: notaId, texto, tipo } : { nota: notaId, texto });
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
    if (usuario) { const ra = await sb.rpc('es_admin'); esAdmin = !!ra.data; }
    await cargarReputaciones();
    pintarSesion();
    if (usuario && !perfil) pedirPerfil();
    contadoresPortada(); ranking(); cargarNota(); cargarConvenio(); cargarAportes(); panelAdmin(); estadisticas(); contarVisita();
    if (esAdmin) { const s = $('#sesion'); if (s && !$('#link-admin')) s.prepend(h('a', { id: 'link-admin', class: 'link-admin', href: 'admin.html' }, 'Administración')); }
  }
  iniciar();
})();
