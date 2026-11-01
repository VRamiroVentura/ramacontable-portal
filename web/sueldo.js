/* Ramacontable · calculadoras de sueldo por convenio (Comercio y Casas particulares).
   Toma la escala vigente cargada en la página del convenio. Si no hay escala, se carga el básico a mano. */
(function () {
  const norm = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim();
  function numero(txt) {
    const t = String(txt == null ? '' : txt).trim().replace(/\$|\s/g, '');
    if (!t) return 0;
    const n = /,\d{1,2}$/.test(t) || (t.includes('.') && t.includes(',')) ? Number(t.replace(/\./g, '').replace(',', '.'))
      : (/^\d{1,3}(\.\d{3})+$/.test(t) ? Number(t.replace(/\./g, '')) : Number(t.replace(',', '.')));
    return isFinite(n) ? n : NaN;
  }
  const r2 = n => Math.round(n * 100) / 100;
  const fmt = n => '$ ' + n.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const col = (cab, prueba) => cab.findIndex(h => prueba(norm(h)));

  // ---------- cálculos puros (se exportan para probarlos) ----------
  function comercio({ basico, nr = 0, horas = 48, anios = 0, presentismo = true, nrAdicionales = false, osNr = true,
    faecys = 0.5, sindicato = 2 }) {
    if (!(basico > 0)) throw new Error('Elegí una categoría o cargá el sueldo básico.');
    if (!(horas > 0 && horas <= 48)) throw new Error('Las horas semanales tienen que estar entre 1 y 48.');
    if (anios < 0 || anios > 60) throw new Error('Revisá los años de antigüedad.');
    const prop = horas / 48;
    const b = r2(basico * prop), ant = r2(b * anios / 100), pres = presentismo ? r2((b + ant) / 12) : 0;
    const rem = r2(b + ant + pres);
    const nrB = r2(nr * prop), nrAnt = nrAdicionales ? r2(nrB * anios / 100) : 0, nrPres = nrAdicionales && presentismo ? r2((nrB + nrAnt) / 12) : 0;
    const nrTot = r2(nrB + nrAnt + nrPres);
    const desc = [
      { n: 'Jubilación (SIPA)', p: 11, base: rem },
      { n: 'Ley 19.032 (PAMI)', p: 3, base: rem },
      { n: 'Obra social', p: 3, base: osNr ? rem + nrTot : rem },
      { n: 'Aporte FAECYS (art. 100 CCT)', p: faecys, base: rem + nrTot },
      { n: 'Cuota o aporte sindical', p: sindicato, base: rem + nrTot },
    ].filter(d => d.p > 0).map(d => ({ ...d, monto: r2(d.base * d.p / 100) }));
    const totalDesc = r2(desc.reduce((s, d) => s + d.monto, 0));
    return { prop, b, ant, pres, rem, nrB, nrAnt, nrPres, nrTot, desc, totalDesc, bruto: r2(rem + nrTot), neto: r2(rem + nrTot - totalDesc) };
  }

  function casas({ mensual, hora, modo = 'mensual', horasMes = 0, anios = 0, zona = 0 }) {
    let base;
    if (modo === 'hora') {
      if (!(hora > 0)) throw new Error('Elegí una categoría o cargá el valor de la hora.');
      if (!(horasMes > 0 && horasMes <= 300)) throw new Error('Cargá las horas trabajadas en el mes.');
      base = r2(hora * horasMes);
    } else {
      if (!(mensual > 0)) throw new Error('Elegí una categoría o cargá el sueldo mensual.');
      base = r2(mensual);
    }
    if (anios < 0 || anios > 60) throw new Error('Revisá los años de antigüedad.');
    const ant = r2(base * anios / 100), zon = r2(base * (zona || 0) / 100);
    return { base, ant, zon, bruto: r2(base + ant + zon) };
  }
  window.RCSueldo = { comercio, casas, numero };

  // ---------- interfaz ----------
  const form = document.getElementById('calc-sueldo');
  if (!form) return;
  const tipo = form.dataset.calc;
  const E = window.RC_ESCALA || {};
  const salida = document.getElementById('resultado-sueldo'), err = document.getElementById('err-sueldo');
  const sel = form.categoria, aviso = document.getElementById('escala-origen');

  function filas() {
    const t = E.tabla || [];
    if (t.length < 2) return { cab: [], filas: [] };
    return { cab: t[0], filas: t.slice(1).filter(f => f[0]) };
  }
  function pintarCategorias() {
    const { cab, filas: fs } = filas();
    sel.innerHTML = fs.map((f, i) => `<option value="${i}">${esc(f[0])}</option>`).join('') + '<option value="otro">Otra / cargar el importe a mano</option>';
    aviso.innerHTML = fs.length ? `Escala cargada: <b>${esc(E.periodo || '')}</b>. <a href="escala-${esc(E.slug)}.html">Ver la escala completa</a>.`
      : `Todavía no hay una escala cargada en el portal: cargá el importe a mano. <a href="escala-${esc(E.slug || '')}.html">Ver la página del convenio</a>.`;
    if (!fs.length) sel.value = 'otro';
    completar();
  }
  function completar() {
    const { cab, filas: fs } = filas();
    const f = fs[Number(sel.value)];
    if (!f) return;
    if (tipo === 'comercio') {
      const ib = col(cab, h => h.includes('basic')), inr = col(cab, h => h === 'nr' || h.includes('no rem') || h.includes('suma'));
      form.basico.value = ib >= 0 ? f[ib] : (f[1] || '');
      form.nr.value = inr >= 0 ? f[inr] : '';
    } else {
      const sin = form.retiro.value === 'sin';
      const elegir = clave => col(cab, h => h.includes(clave) && (sin ? h.includes('sin') : h.includes('con')));
      let ih = elegir('hora'), im = elegir('mens');
      if (ih < 0) ih = col(cab, h => h.includes('hora'));
      if (im < 0) im = col(cab, h => h.includes('mens'));
      form.mensual.value = im >= 0 ? (f[im] || '') : '';
      form.hora.value = ih >= 0 ? (f[ih] || '') : '';
    }
  }
  sel.addEventListener('change', completar);
  if (form.retiro) form.retiro.addEventListener('change', completar);
  if (form.modo) form.modo.addEventListener('change', () => { form.querySelector('[data-hora]').hidden = form.modo.value !== 'hora'; });

  form.addEventListener('submit', ev => {
    ev.preventDefault(); err.textContent = '';
    try {
      const cat = sel.value === 'otro' ? 'Importe cargado a mano' : sel.options[sel.selectedIndex].text;
      if (tipo === 'comercio') {
        const r = comercio({ basico: numero(form.basico.value), nr: numero(form.nr.value), horas: numero(form.horas.value), anios: numero(form.anios.value),
          presentismo: form.presentismo.checked, nrAdicionales: form.nrAdic.checked, osNr: form.osNr.checked,
          faecys: numero(form.faecys.value), sindicato: numero(form.sindicato.value) });
        const parcial = r.prop < 1 ? ` × ${numero(form.horas.value)} ÷ 48 horas` : '';
        const filasR = [['Sueldo básico' + (parcial ? ' (proporcional a la jornada)' : ''), r.b], ['Antigüedad (' + numero(form.anios.value) + '% del básico)', r.ant]];
        if (r.pres) filasR.push(['Presentismo (1/12 de básico + antigüedad)', r.pres]);
        filasR.push(['<b>Total remunerativo</b>', r.rem]);
        if (r.nrTot) { filasR.push(['Suma no remunerativa' + (parcial ? ' (proporcional)' : ''), r.nrB]); if (r.nrAnt) filasR.push(['Antigüedad sobre la suma NR', r.nrAnt]); if (r.nrPres) filasR.push(['Presentismo sobre la suma NR', r.nrPres]); }
        salida.innerHTML = `
          <div class="res-top"><div><span>Bruto</span><b>${fmt(r.bruto)}</b></div><div><span>Descuentos</span><b>− ${fmt(r.totalDesc)}</b></div><div class="neto"><span>Neto estimado</span><b>${fmt(r.neto)}</b></div></div>
          <h3>Detalle · ${esc(cat)}</h3>
          <table class="tabla-desc"><tbody>${filasR.map(f => `<tr><td>${f[0]}</td><td>${fmt(f[1])}</td></tr>`).join('')}</tbody></table>
          <table class="tabla-desc"><thead><tr><th>Descuento</th><th>%</th><th>Importe</th></tr></thead><tbody>
          ${r.desc.map(d => `<tr><td>${esc(d.n)}</td><td>${d.p}%</td><td>${fmt(d.monto)}</td></tr>`).join('')}
          <tr class="tot"><td>Total</td><td></td><td>${fmt(r.totalDesc)}</td></tr></tbody></table>
          <p class="nota-chica">No incluye horas extras, adicionales particulares (cajero, idioma, etc.), OSECAC, retención de Ganancias ni otros descuentos de la empresa.</p>`;
      } else {
        const r = casas({ mensual: numero(form.mensual.value), hora: numero(form.hora.value), modo: form.modo.value, horasMes: numero(form.horasMes.value),
          anios: numero(form.anios.value), zona: numero(form.zona.value) });
        const filasR = [[form.modo.value === 'hora' ? `Horas trabajadas (${numero(form.horasMes.value)} × ${fmt(numero(form.hora.value))})` : 'Sueldo mensual de la categoría', r.base],
          ['Antigüedad (' + numero(form.anios.value) + '%)', r.ant]];
        if (r.zon) filasR.push(['Zona desfavorable (' + numero(form.zona.value) + '%)', r.zon]);
        salida.innerHTML = `
          <div class="res-top uno"><div class="neto"><span>Sueldo bruto del mes</span><b>${fmt(r.bruto)}</b></div></div>
          <h3>Detalle · ${esc(cat)} · ${form.retiro.value === 'sin' ? 'sin retiro' : 'con retiro'}</h3>
          <table class="tabla-desc"><tbody>${filasR.map(f => `<tr><td>${f[0]}</td><td>${fmt(f[1])}</td></tr>`).join('')}
          <tr class="tot"><td>Total</td><td>${fmt(r.bruto)}</td></tr></tbody></table>
          <p class="nota-chica">Los aportes y contribuciones de casas particulares son importes fijos que dependen de las horas semanales trabajadas: se pagan con el formulario 102 de ARCA según la tabla vigente.</p>`;
      }
      salida.hidden = false;
      salida.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) { err.textContent = e.message; salida.hidden = true; }
  });

  pintarCategorias();
  // Si el administrador actualizó la escala después de la última publicación, se usa la más nueva.
  const cfg = window.RC_CONFIG || {};
  if (cfg.url && cfg.key && E.slug) {
    fetch(`${cfg.url}/rest/v1/convenios?select=escala&slug=eq.${encodeURIComponent(E.slug)}`, { headers: { apikey: cfg.key, Authorization: 'Bearer ' + cfg.key } })
      .then(r => r.ok ? r.json() : []).then(d => {
        const nueva = d && d[0] && d[0].escala;
        if (nueva && nueva.tabla && JSON.stringify(nueva.tabla) !== JSON.stringify(E.tabla)) { Object.assign(E, nueva); pintarCategorias(); }
      }).catch(() => {});
  }
})();
