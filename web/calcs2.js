/* Ramacontable · calculadoras conectadas a los datos del día: conversor de dólar, categoría del Monotributo,
   intereses de ARCA, actualización de alquiler y embargo de sueldo. Usa datos/datos-del-dia.json y datos/dolares.json. */
(function () {
  const r2 = n => Math.round(n * 100) / 100;
  const fmt = n => '$ ' + Number(n).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (n, d = 2) => Number(n).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fd = s => s ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) : '';
  function numero(txt) {
    const t = String(txt == null ? '' : txt).trim().replace(/\$|\s|%|US/g, '');
    if (!t) return 0;
    const n = /,\d{1,4}$/.test(t) || (t.includes('.') && t.includes(',')) ? Number(t.replace(/\./g, '').replace(',', '.'))
      : (/^\d{1,3}(\.\d{3})+$/.test(t) ? Number(t.replace(/\./g, '')) : Number(t.replace(',', '.')));
    return isFinite(n) ? n : NaN;
  }
  const json = url => fetch(url).then(r => { if (!r.ok) throw new Error('sin datos'); return r.json(); });
  const DATOS = json('datos/datos-del-dia.json').catch(() => ({}));

  // ---------- cálculos puros ----------
  // Decreto 484/87: inembargable hasta 1 SMVM; hasta 2 SMVM, 10% del excedente; más de 2 SMVM, 20% del excedente.
  // Se toma la remuneración BRUTA (art. 2). Cada cuota del SAC se calcula aparte. No rige para cuotas alimentarias (art. 4).
  function embargo(bruto, smvm) {
    if (!(smvm > 0)) throw new Error('Falta el salario mínimo vital y móvil.');
    if (!(bruto >= 0)) throw new Error('Cargá la remuneración bruta.');
    if (bruto <= smvm) return { tramo: 'Hasta 1 salario mínimo: inembargable', pct: 0, excedente: 0, maximo: 0 };
    const excedente = r2(bruto - smvm), pct = bruto <= 2 * smvm ? 10 : 20;
    return { tramo: pct === 10 ? 'Entre 1 y 2 salarios mínimos' : 'Más de 2 salarios mínimos', pct, excedente, maximo: r2(excedente * pct / 100) };
  }
  // varios oficios: el tope es uno solo y se cobra en el orden de llegada
  function repartir(maximo, deudas) {
    let queda = maximo;
    return deudas.map(d => { const toma = r2(Math.min(queda, d)); queda = r2(queda - toma); return toma; });
  }
  function categoriaMono(tabla, ingresos, tipo) {
    if (!(ingresos >= 0)) throw new Error('Cargá lo que facturaste en los últimos 12 meses.');
    const filas = (tabla || []).filter(f => f.ingresos_max > 0).sort((a, b) => a.ingresos_max - b.ingresos_max);
    if (!filas.length) throw new Error('La tabla vigente del Monotributo todavía está en verificación.');
    const f = filas.find(x => ingresos <= x.ingresos_max);
    if (!f) return { excede: true, maxima: filas[filas.length - 1] };
    return { fila: f, cuota: tipo === 'bienes' ? f.cuota_bienes : f.cuota_servicios };
  }
  function interesesArca(monto, vence, paga, tasaMensual) {
    if (!(monto > 0)) throw new Error('Cargá el monto adeudado.');
    if (!vence || !paga || paga <= vence) throw new Error('La fecha de pago tiene que ser posterior al vencimiento.');
    if (!(tasaMensual > 0)) throw new Error('Cargá la tasa mensual de interés resarcitorio.');
    const dias = Math.round((new Date(paga + 'T00:00:00Z') - new Date(vence + 'T00:00:00Z')) / 86400000);
    const interes = r2(monto * tasaMensual / 100 / 30 * dias);
    return { dias, interes, total: r2(monto + interes) };
  }
  window.RCCalcs2 = { embargo, repartir, categoriaMono, interesesArca, numero };

  // ---------- interfaz ----------
  const form = document.getElementById('calc2');
  if (!form) return;
  const salida = document.getElementById('resultado'), err = document.getElementById('err');
  const mostrar = html => { salida.innerHTML = html; salida.hidden = false; salida.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  const falla = e => { err.textContent = e.message; salida.hidden = true; };
  const origen = document.getElementById('origen-dato');
  const tipo = form.dataset.calc;
  const hoyISO = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  form.querySelectorAll('input[type=date][data-hoy]').forEach(i => { if (!i.value) i.value = hoyISO; });

  if (tipo === 'conversor') {
    let cot = {};
    json('datos/dolares.json').then(d => {
      cot = d.actual || {};
      form.casa.innerHTML = Object.entries(cot).map(([k, x]) => `<option value="${esc(k)}">${esc(x.nombre)}${k === 'blue' ? ' (informativo)' : ''}</option>`).join('');
      if (origen) origen.textContent = 'Cotizaciones de DolarAPI, actualizadas cada hora en esta página.';
    }).catch(() => { if (origen) origen.textContent = 'No se pudieron cargar las cotizaciones: probá más tarde.'; });
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const x = cot[form.casa.value]; if (!x) throw new Error('Todavía no se cargaron las cotizaciones.');
        const m = numero(form.monto.value); if (!(m > 0)) throw new Error('Cargá un monto.');
        const aPesos = form.sentido.value === 'usd';
        const px = aPesos ? x.compra || x.venta : x.venta;
        const r = aPesos ? fmt(m * px) : 'US$ ' + num(m / px);
        mostrar(`<div class="res-top uno"><div class="neto"><span>${aPesos ? 'En pesos' : 'En dólares'}</span><b>${r}</b></div></div>
          <p class="nota-chica">${esc(x.nombre)}: compra ${fmt(x.compra || 0)} · venta ${fmt(x.venta)}. ${aPesos ? 'Para vender dólares se usa el precio de compra.' : 'Para comprar dólares se usa el precio de venta.'} Actualizado: ${esc((x.fechaActualizacion || '').slice(0, 16).replace('T', ' '))} (hora UTC).${form.casa.value === 'blue' ? ' El blue es una cotización informativa del mercado informal.' : ''}</p>`);
      } catch (e) { falla(e); }
    });
  }

  if (tipo === 'monotributo') {
    let tabla = null;
    DATOS.then(d => {
      const x = d['monotributo-categorias-vigentes'];
      tabla = x && x.estructurado && x.estructurado.categorias;
      if (origen) origen.innerHTML = tabla ? `Tabla vigente verificada el ${fd(x.revisado)}${x.norma ? ' (' + esc(x.norma) + ')' : ''}. <a href="monotributo-categorias-vigentes.html">Ver la tabla completa</a>.`
        : 'La tabla vigente todavía está en verificación. <a href="monotributo-categorias-vigentes.html">Ver el dato</a>.';
    });
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const r = categoriaMono(tabla, numero(form.ingresos.value), form.tipo.value);
        if (r.excede) return mostrar(`<div class="res-top uno"><div class="neto"><span>Resultado</span><b>Superás el tope</b></div></div><p>Con esa facturación superás la categoría más alta (${esc(r.maxima.categoria)}: ${fmt(r.maxima.ingresos_max)}). Corresponde analizar el pase al régimen general.</p>`);
        mostrar(`<div class="res-top"><div><span>Categoría</span><b>${esc(r.fila.categoria)}</b></div><div class="neto"><span>Cuota mensual</span><b>${r.cuota ? fmt(r.cuota) : 'sin dato'}</b></div></div>
          <p class="nota-chica">Tope de la categoría: ${fmt(r.fila.ingresos_max)} de ingresos brutos anuales. La categoría también depende de la superficie, la energía y el alquiler: si alguno supera el tope de tu categoría, corresponde la siguiente.</p>`);
      } catch (e) { falla(e); }
    });
  }

  if (tipo === 'intereses') {
    DATOS.then(d => {
      const x = d['intereses-resarcitorios-arca'], t = x && x.estructurado && x.estructurado.resarcitorio_mensual;
      if (t && !form.tasa.value) form.tasa.value = String(t).replace('.', ',');
      if (origen) origen.innerHTML = t ? `Tasa vigente verificada el ${fd(x.revisado)}${x.norma ? ' (' + esc(x.norma) + ')' : ''}. <a href="intereses-resarcitorios-arca.html">Ver el dato</a>.`
        : 'La tasa vigente está en verificación: cargala a mano. <a href="intereses-resarcitorios-arca.html">Ver el dato</a>.';
    });
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const r = interesesArca(numero(form.monto.value), form.vence.value, form.paga.value, numero(form.tasa.value));
        mostrar(`<div class="res-top"><div><span>Días de atraso</span><b>${r.dias}</b></div><div><span>Intereses</span><b>${fmt(r.interes)}</b></div><div class="neto"><span>Total a pagar</span><b>${fmt(r.total)}</b></div></div>
          <p class="nota-chica">Cálculo: monto × ${esc(form.tasa.value)}% mensual ÷ 30 × ${r.dias} días. Si la tasa cambió durante el atraso, cada tramo va con su tasa: el cálculo exacto lo hace el sistema de ARCA al generar el VEP.</p>`);
      } catch (e) { falla(e); }
    });
  }

  if (tipo === 'alquiler') {
    form.addEventListener('submit', async ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const s = await json(`datos/serie-${form.indice.value}.json`);
        const r = window.RCCalcs.actualizar(s, numero(form.monto.value), form.desde.value, form.hasta.value);
        mostrar(`<div class="res-top"><div><span>Alquiler actual</span><b>${fmt(numero(form.monto.value))}</b></div><div class="neto"><span>Alquiler actualizado</span><b>${fmt(r.total)}</b></div><div><span>Aumento</span><b>${num((r.coef - 1) * 100)}%</b></div></div>
          <p class="nota-chica">${esc(r.detalle)}. ${esc(r.aviso || '')} Fuente: serie oficial del BCRA.</p>`);
      } catch (e) { falla(e); }
    });
  }

  if (tipo === 'embargo') {
    DATOS.then(d => {
      const x = d['salario-minimo-vital-y-movil'];
      if (x && x.monto && !form.smvm.value) form.smvm.value = num(x.monto);
      if (origen) origen.innerHTML = x && x.monto ? `Salario mínimo vigente este mes: <b>${fmt(x.monto)}</b>${x.norma ? ' (' + esc(x.norma) + ')' : ''}. <a href="salario-minimo-vital-y-movil.html">Ver el dato</a>.`
        : 'El salario mínimo vigente está en verificación: cargalo a mano. <a href="salario-minimo-vital-y-movil.html">Ver el dato</a>.';
    });
    form.alimentos.addEventListener('change', () => { form.querySelector('[data-escala]').hidden = form.alimentos.checked; });
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        if (form.alimentos.checked) return mostrar('<p><b>Las cuotas alimentarias y las litis expensas no siguen esta escala</b> (art. 4, Decreto 484/87): se retiene el porcentaje o el monto que fijó el juez en el oficio, de modo que permita la subsistencia del alimentante.</p>');
        const smvm = numero(form.smvm.value), r = embargo(numero(form.bruto.value), smvm);
        const deudas = String(form.deudas.value || '').split(/[\n;]+/).map(numero).filter(x => x > 0);
        let rep = '';
        if (deudas.length) {
          const t = repartir(r.maximo, deudas);
          rep = `<h3>Reparto entre los oficios (en orden de llegada)</h3><table class="tabla-desc"><tbody>${t.map((x, i) => `<tr><td>Oficio ${i + 1} (saldo ${fmt(deudas[i])})</td><td>${fmt(x)}</td></tr>`).join('')}</tbody></table>`;
        }
        mostrar(`<div class="res-top"><div><span>Tramo</span><b>${esc(r.tramo)}</b></div><div class="neto"><span>Embargo máximo del mes</span><b>${fmt(r.maximo)}</b></div></div>
          <table class="tabla-desc"><tbody><tr><td>Remuneración bruta</td><td>${fmt(numero(form.bruto.value))}</td></tr><tr><td>Salario mínimo vital y móvil</td><td>${fmt(smvm)}</td></tr>
          <tr><td>Excedente sobre el salario mínimo</td><td>${fmt(r.excedente)}</td></tr><tr class="tot"><td>Embargable (${r.pct}% del excedente)</td><td>${fmt(r.maximo)}</td></tr></tbody></table>${rep}
          <p class="nota-chica">Se calcula sobre la remuneración bruta del mes (art. 2, Decreto 484/87). El aguinaldo se calcula aparte, con la misma escala, cuota por cuota (art. 1). El embargo nunca puede superar lo que se debe.</p>`);
      } catch (e) { falla(e); }
    });
  }
})();
