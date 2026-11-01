/* Ramacontable · calculadora de aguinaldo (SAC). Ley 23.041 y Decreto 1078/84. */
(function () {
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const DIA = 86400000;

  function semestre(clave) {
    const [anio, s] = clave.split('-').map(Number);
    const desde = new Date(Date.UTC(anio, s === 1 ? 0 : 6, 1));
    const hasta = new Date(Date.UTC(anio, s === 1 ? 5 : 11, s === 1 ? 30 : 31));
    const meses = [];
    for (let i = 0; i < 6; i++) meses.push(`${MESES[(s === 1 ? 0 : 6) + i]} ${anio}`);
    return { anio, s, desde, hasta, dias: Math.round((hasta - desde) / DIA) + 1, meses, vence: s === 1 ? `30 de junio de ${anio}` : `18 de diciembre de ${anio}` };
  }
  function numero(txt) {
    const t = String(txt || '').trim().replace(/\$|\s/g, '');
    if (!t) return 0;
    // formato argentino: 1.234.567,89 ; también acepta 1234567.89
    const n = /,\d{1,2}$/.test(t) || (t.includes('.') && t.includes(',')) ? Number(t.replace(/\./g, '').replace(',', '.'))
      : (/^\d{1,3}(\.\d{3})+$/.test(t) ? Number(t.replace(/\./g, '')) : Number(t.replace(',', '.')));
    return isFinite(n) ? n : NaN;
  }
  const r2 = n => Math.round(n * 100) / 100;
  const fecha = d => d ? new Date(d + 'T00:00:00Z') : null;

  // Cálculo puro (se exporta para probarlo)
  function calcular({ semestre: clave, montos, ingreso, egreso, sinGoce = 0, tope = 0 }) {
    const S = semestre(clave);
    if (!montos.length || montos.some(m => isNaN(m) || m < 0)) throw new Error('Revisá los montos: tienen que ser números positivos.');
    const mejor = Math.max(...montos);
    if (!(mejor > 0)) throw new Error('Cargá al menos un mes con remuneración.');
    const mesMejor = montos.indexOf(mejor);
    let desde = S.desde, hasta = S.hasta;
    const fi = fecha(ingreso), fe = fecha(egreso);
    if (fi && fi > S.hasta) throw new Error('La fecha de ingreso es posterior al semestre.');
    if (fe && fe < S.desde) throw new Error('La fecha de egreso es anterior al semestre.');
    if (fi && fi > desde) desde = fi;
    if (fe && fe < hasta) hasta = fe;
    if (hasta < desde) throw new Error('La fecha de egreso es anterior a la de ingreso.');
    const enPeriodo = Math.round((hasta - desde) / DIA) + 1;
    const sg = Math.max(0, Math.floor(Number(sinGoce) || 0));
    if (sg > enPeriodo) throw new Error('Los días sin goce superan los días del período.');
    const dias = enPeriodo - sg;
    const completo = dias === S.dias;
    const sac = r2(mejor / 2 * dias / S.dias);
    const topeSac = tope > 0 ? r2(tope / 2 * dias / S.dias) : 0;
    const base = topeSac ? Math.min(sac, topeSac) : sac;
    const desc = [
      { n: 'Jubilación (SIPA)', p: 11 },
      { n: 'Ley 19.032 (PAMI)', p: 3 },
      { n: 'Obra social', p: 3 },
    ].map(d => ({ ...d, monto: r2(base * d.p / 100) }));
    const totalDesc = r2(desc.reduce((s, d) => s + d.monto, 0));
    return { S, mejor, mesMejor, desde, hasta, enPeriodo, sinGoce: sg, dias, completo, sac, topeSac, base, topeAplicado: topeSac > 0 && sac > topeSac,
      desc, totalDesc, neto: r2(sac - totalDesc), egresoEnSemestre: !!(fe && fe <= S.hasta) };
  }

  // ---------- interfaz ----------
  const fmt = n => '$ ' + n.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fd = d => d.toLocaleDateString('es-AR', { timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric' });
  const form = document.getElementById('calc-sac');
  if (!form) { window.RCAguinaldo = { calcular, numero, semestre }; return; }
  const cajaMeses = document.getElementById('meses');
  const salida = document.getElementById('resultado-sac');
  const err = document.getElementById('err-sac');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function pintarMeses() {
    const S = semestre(form.semestre.value);
    const previos = [...cajaMeses.querySelectorAll('input')].map(i => i.value);
    cajaMeses.innerHTML = S.meses.map((m, i) => `<label>${esc(m.charAt(0).toUpperCase() + m.slice(1))}<input name="m${i}" inputmode="decimal" placeholder="0,00" value="${esc(previos[i] || '')}"></label>`).join('');
  }
  form.semestre.addEventListener('change', pintarMeses);
  pintarMeses();

  form.addEventListener('submit', ev => {
    ev.preventDefault(); err.textContent = '';
    try {
      const montos = [...cajaMeses.querySelectorAll('input')].map(i => numero(i.value));
      const r = calcular({ semestre: form.semestre.value, montos, ingreso: form.ingreso.value, egreso: form.egreso.value, sinGoce: form.sinGoce.value, tope: numero(form.tope.value) });
      const jornal = form.tipo.value === 'jornal';
      const pasos = [
        [`Mejor remuneración del semestre: <b>${fmt(r.mejor)}</b> (${esc(r.S.meses[r.mesMejor])}).`,
          jornal ? 'En jornalizados se toma el mes en que más se cobró, sumando todos los jornales y adicionales remunerativos de ese mes.' : 'Se toma la mayor remuneración mensual devengada en el semestre, por todo concepto remunerativo.', 'Ley 23.041, art. 1'],
        [`Días computables: <b>${r.dias}</b> de ${r.S.dias}` + (r.completo ? ' (semestre completo).' : ` (del ${fd(r.desde)} al ${fd(r.hasta)}${r.sinGoce ? `, menos ${r.sinGoce} días sin goce` : ''}).`),
          r.completo ? 'Trabajó todo el semestre, así que corresponde el aguinaldo completo.' : 'Como no trabajó todo el semestre, el aguinaldo se paga en proporción al tiempo trabajado.', 'Decreto 1078/84, art. 2'],
        [`Aguinaldo bruto: ${fmt(r.mejor)} ÷ 2` + (r.completo ? '' : ` × ${r.dias} ÷ ${r.S.dias}`) + ` = <b>${fmt(r.sac)}</b>.`,
          'El aguinaldo equivale a la mitad de la mejor remuneración del semestre' + (r.completo ? '.' : ', proporcional a los días trabajados.'), 'Ley 23.041, art. 1'],
        [`Base para aportes: <b>${fmt(r.base)}</b>` + (r.topeAplicado ? ` (se aplica el tope del SAC: ${fmt(r.topeSac)}).` : '.'),
          'Los aportes se calculan sobre el aguinaldo, con un tope propio equivalente al 50% de la base imponible máxima mensual (proporcional si el semestre no está completo).', 'Ley 24.241'],
      ];
      salida.innerHTML = `
        <div class="res-top"><div><span>Aguinaldo bruto</span><b>${fmt(r.sac)}</b></div><div><span>Descuentos</span><b>− ${fmt(r.totalDesc)}</b></div><div class="neto"><span>Neto estimado</span><b>${fmt(r.neto)}</b></div></div>
        <h3>Cálculo paso a paso</h3>
        <ol class="pasos-sac">${pasos.map(p => `<li><p>${p[0]}</p><span class="porque">Por qué: ${esc(p[1])}</span><span class="norma">${esc(p[2])}</span></li>`).join('')}</ol>
        <table class="tabla-desc"><thead><tr><th>Descuento</th><th>%</th><th>Importe</th></tr></thead><tbody>
        ${r.desc.map(d => `<tr><td>${esc(d.n)}</td><td>${d.p}%</td><td>${fmt(d.monto)}</td></tr>`).join('')}
        <tr class="tot"><td>Total</td><td>17%</td><td>${fmt(r.totalDesc)}</td></tr></tbody></table>
        <p class="nota-chica">No incluye cuota sindical, otros descuentos de convenio ni retención de Ganancias.</p>
        <p class="fecha-pago">${r.egresoEnSemestre ? 'Como el trabajador egresa en el semestre, el aguinaldo proporcional se paga junto con la liquidación final.' : `Vencimiento de pago: <b>${esc(r.S.vence)}</b>.`}</p>`;
      salida.hidden = false;
      salida.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) { err.textContent = e.message; salida.hidden = true; }
  });
  window.RCAguinaldo = { calcular, numero, semestre };
})();
