/* Ramacontable · ¿Monotributo o Responsable Inscripto? Compara cuánto te queda en el bolsillo por año en cada régimen.
   Usa los datos del día (datos/datos-del-dia.json): categorías del Monotributo, Ingresos Brutos simplificado de cada provincia,
   escala y deducciones de Ganancias y aportes de autónomos. Es una estimación: no incluye honorarios, percepciones ni casos especiales. */
(function () {
  const IVA = 0.21;
  // Deducción especial art. 30 inc. c) ap. 1 (cuenta propia): 3,5 veces la ganancia no imponible
  // (tabla anual 2026 de ARCA: $ 21.068.849,78 frente a $ 6.019.671,36 de ganancia no imponible).
  const ESPECIAL_AUT = 3.5;
  const fmt = n => '$ ' + Math.round(n).toLocaleString('es-AR');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function numero(txt) {
    const t = String(txt == null ? '' : txt).trim().replace(/\$|\s|%/g, '');
    if (!t) return 0;
    const n = /,\d{1,4}$/.test(t) || (t.includes('.') && t.includes(',')) ? Number(t.replace(/\./g, '').replace(',', '.'))
      : (/^\d{1,3}(\.\d{3})+$/.test(t) ? Number(t.replace(/\./g, '')) : Number(t.replace(',', '.')));
    return isFinite(n) ? n : NaN;
  }
  const est = (d, slug) => ((d[slug] || {}).estructurado) || null;

  // Ingresos Brutos simplificado por mes según provincia (el componente provincial del Monotributo o régimen propio)
  function iibbSimplificado(d, prov, letra, tipo, ingresos) {
    const tablas = { ba: 'ingresos-brutos-arba-regimen-simplificado', cba: 'monotributo-unificado-cordoba', mza: 'monotributo-unificado-mendoza',
      er: 'monotributo-unificado-entre-rios', salta: 'regimen-simplificado-salta', sf: 'ingresos-brutos-santa-fe-regimen-simplificado' };
    const e = est(d, tablas[prov]);
    if (!e || !e.categorias) return null;
    let f;
    if (prov === 'sf') f = e.categorias.filter(c => c.ingresos_max > 0).sort((a, b) => a.ingresos_max - b.ingresos_max).find(c => ingresos <= c.ingresos_max);
    else f = e.categorias.find(c => c.categoria === letra);
    if (!f) return null;
    const v = tipo === 'bienes' ? (f.importe_bienes ?? f.importe_resto ?? f.importe) : (f.importe_servicios ?? f.importe);
    return v > 0 ? v : null;
  }

  function ganancias(esc_, neta) {
    if (!(neta > 0)) return 0;
    const t = esc_.find(x => neta > x.desde && (x.hasta == null || neta <= x.hasta)) || esc_[esc_.length - 1];
    return t.fijo + (neta - t.desde) * t.pct / 100;
  }

  function comparar(d, p) {
    const mono = est(d, 'monotributo-categorias-vigentes'), gan = est(d, 'ganancias-deducciones-sueldos'), aut = est(d, 'autonomos-categorias-aportes');
    if (!mono || !gan || !aut) throw new Error('Los datos vigentes todavía están en verificación. Probá más tarde.');
    if (!(p.facturacion > 0)) throw new Error('Cargá cuánto facturás por año.');
    if (!(p.gastos >= 0) || p.gastos >= p.facturacion) throw new Error('Los gastos tienen que ser menores que la facturación.');
    // --- Monotributo
    const cats = mono.categorias.filter(c => c.ingresos_max > 0).sort((a, b) => a.ingresos_max - b.ingresos_max);
    const cat = cats.find(c => p.facturacion <= c.ingresos_max);
    let m = null;
    if (cat) {
      const cuota = (p.tipo === 'bienes' ? cat.cuota_bienes : cat.cuota_servicios) * 12;
      const iibbMes = p.prov === 'otra' ? p.iibbOtra : iibbSimplificado(d, p.prov, cat.categoria, p.tipo, p.facturacion);
      const iibb = (iibbMes || 0) * 12;
      m = { cat: cat.categoria, cuota, iibb, iibbFalta: p.prov !== 'otra' && iibbMes == null, bolsillo: p.facturacion - p.gastos - cuota - iibb };
    }
    // --- Responsable Inscripto
    const ri = a => {
      const cobro = p.facturacion * (1 + IVA * (1 - a));            // lo que paga el cliente con IVA
      const neto = cobro / (1 + IVA), debito = cobro - neto;
      const credito = p.gastos * p.pctFactA * IVA / (1 + IVA);       // IVA de los gastos con factura A
      const iva = Math.max(0, debito - credito);
      const gastosNetos = p.gastos - credito;
      const iibb = neto * p.alicIIBB;
      const autonomos = aut.categorias.find(c => c.categoria === p.catAut).aporte * 12;
      const deduc = gan.ganancia_no_imponible * (1 + ESPECIAL_AUT) + (p.conyuge ? gan.conyuge : 0) + p.hijos * gan.hijo;
      const neta = neto - gastosNetos - iibb - autonomos - deduc;
      const g = ganancias(gan.escala, neta);
      return { cobro, neto, debito, credito, iva, iibb, autonomos, gan: g, bolsillo: neto - gastosNetos - iibb - autonomos - g };
    };
    return { m, r: ri(p.absorbe), r0: ri(0), r100: ri(1), tope: cats[cats.length - 1].ingresos_max, periodo: gan.periodo };
  }

  const form = document.getElementById('calc-monori');
  if (!form) return;
  const salida = document.getElementById('resultado-monori'), err = form.querySelector('.error');
  const prov = form.prov, otra = form.querySelector('[data-otra]');
  const clientes = form.clientes, abs = form.absorbe;
  prov.addEventListener('change', () => { otra.hidden = prov.value !== 'otra'; });
  clientes.addEventListener('change', () => { abs.value = clientes.value === 'empresas' ? '0' : '100'; });
  const DATOS = fetch('datos/datos-del-dia.json').then(r => r.json()).catch(() => ({}));
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    err.textContent = '';
    try {
      const d = await DATOS;
      const p = { facturacion: numero(form.facturacion.value), gastos: numero(form.gastos.value) || 0, pctFactA: Math.min(100, Math.max(0, numero(form.facta.value) || 0)) / 100,
        absorbe: Math.min(100, Math.max(0, numero(abs.value) || 0)) / 100, tipo: form.tipo.value, prov: prov.value, iibbOtra: numero(form.iibbotra.value) || 0,
        alicIIBB: (numero(form.alic.value) || 0) / 100, catAut: form.catAut.value, conyuge: form.conyuge.checked, hijos: Math.max(0, Math.floor(numero(form.hijos.value) || 0)) };
      if ([p.facturacion, p.gastos].some(isNaN)) throw new Error('Revisá los importes.');
      const x = comparar(d, p), r = x.r, m = x.m;
      let veredicto;
      if (!m) veredicto = `<p class="res-grande">Con ${fmt(p.facturacion)} por año superás el tope del Monotributo (${fmt(x.tope)}): te corresponde ser Responsable Inscripto.</p>`;
      else {
        const dif = m.bolsillo - r.bolsillo;
        veredicto = `<p class="res-grande">${dif >= 0 ? 'Te conviene el <b>Monotributo</b>' : 'Te conviene ser <b>Responsable Inscripto</b>'}: te quedan ${fmt(Math.abs(dif))} más por año.</p>`;
      }
      const fila = (n, a, b) => `<tr><td>${n}</td><td>${a}</td><td>${b}</td></tr>`;
      salida.innerHTML = veredicto + `<div class="tabla"><table><thead><tr><th>Por año</th><th>Monotributo${m ? '<br><small class="cat">categoría ' + m.cat + '</small>' : ''}</th><th>Inscripto</th></tr></thead><tbody>`
        + fila('Lo que cobrás', m ? fmt(p.facturacion) : '—', fmt(r.cobro) + (p.absorbe < 1 ? ' (con IVA)' : ''))
        + fila('IVA que pagás a ARCA', m ? 'En la cuota' : '—', fmt(r.iva) + ` <small>(${fmt(r.debito)} de tus ventas − ${fmt(r.credito)} de tus compras)</small>`)
        + fila('Cuota del Monotributo', m ? fmt(m.cuota) : '—', '—')
        + fila('Ingresos Brutos', m ? (m.iibbFalta ? 'Sin dato' : fmt(m.iibb)) : '—', fmt(r.iibb))
        + fila('Aportes de autónomos', m ? 'En la cuota' : '—', fmt(r.autonomos))
        + fila('Ganancias', m ? 'En la cuota' : '—', fmt(r.gan))
        + fila('Gastos de la actividad', m ? fmt(p.gastos) : '—', fmt(p.gastos - r.credito) + (r.credito ? ' <small>(sin el IVA que recuperás)</small>' : ''))
        + `<tr><th>Te queda en el bolsillo</th><th>${m ? fmt(m.bolsillo) : '—'}</th><th>${fmt(r.bolsillo)}</th></tr></tbody></table></div>`
        + (m ? `<p class="ayuda">Si absorbieras todo el IVA (cobrás lo mismo que hoy), como inscripto te quedarían ${fmt(x.r100.bolsillo)}; si lo sumaras todo al precio, ${fmt(x.r0.bolsillo)}.</p>` : '')
        + `<p class="ayuda">Escala y deducciones de Ganancias: ${esc(x.periodo || 'vigentes')} (ganancia no imponible y deducción especial de cuenta propia${p.conyuge ? ', cónyuge' : ''}${p.hijos ? ', hijos' : ''}). Aportes de autónomos: categoría ${esc(p.catAut)}.</p>`;
      salida.hidden = false;
      salida.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) { err.textContent = e.message; salida.hidden = true; }
  });
  window.RCMonoRI = { comparar };
})();
