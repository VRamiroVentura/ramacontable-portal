/* Ramacontable · calculadoras (actualización de montos, días hábiles, plazo fijo, préstamos, vacaciones,
   liquidación final, horas extras e IVA). Datos oficiales del BCRA en datos/serie-*.json. */
(function () {
  const DIA = 86400000;
  const r2 = n => Math.round(n * 100) / 100;
  const fmt = n => '$ ' + Number(n).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = (n, d = 2) => Number(n).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d }) + '%';
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const F = s => new Date(s + 'T00:00:00Z');
  const iso = d => d.toISOString().slice(0, 10);
  const fd = s => s ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) : '';
  function numero(txt) {
    const t = String(txt == null ? '' : txt).trim().replace(/\$|\s|%/g, '');
    if (!t) return 0;
    const n = /,\d{1,4}$/.test(t) || (t.includes('.') && t.includes(',')) ? Number(t.replace(/\./g, '').replace(',', '.'))
      : (/^\d{1,3}(\.\d{3})+$/.test(t) ? Number(t.replace(/\./g, '')) : Number(t.replace(',', '.')));
    return isFinite(n) ? n : NaN;
  }

  // ---------- datos ----------
  const cache = {};
  function serie(clave) {
    if (!cache[clave]) cache[clave] = fetch(`datos/serie-${clave}.json`).then(r => { if (!r.ok) throw new Error('sin datos'); return r.json(); });
    return cache[clave];
  }
  // valor vigente en una fecha: el último informado en esa fecha o antes
  function valorEn(s, fecha) {
    let lo = 0, hi = s.f.length - 1, res = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (s.f[m] <= fecha) { res = m; lo = m + 1; } else hi = m - 1; }
    return res < 0 ? null : { fecha: s.f[res], valor: s.v[res], i: res };
  }

  // ---------- cálculos puros ----------
  function actualizar(s, monto, desde, hasta, modo = 'simple') {
    if (!(monto > 0)) throw new Error('Cargá un monto mayor a cero.');
    if (!desde || !hasta || hasta <= desde) throw new Error('La fecha final tiene que ser posterior a la inicial.');
    const ult = s.f[s.f.length - 1];
    const aviso = hasta > ult ? `El último dato publicado es del ${fd(ult)}: se usa ese valor.` : '';
    if (s.tipo === 'indice') {
      const a = valorEn(s, desde), b = valorEn(s, hasta);
      if (!a) throw new Error(`No hay datos antes del ${fd(s.f[0])}.`);
      const coef = b.valor / a.valor;
      return { coef, total: r2(monto * coef), detalle: `${fd(a.fecha)}: ${a.valor.toLocaleString('es-AR')} → ${fd(b.fecha)}: ${b.valor.toLocaleString('es-AR')}`, aviso };
    }
    if (s.tipo === 'acumulada') {
      const a = valorEn(s, desde), b = valorEn(s, hasta);
      if (!a) throw new Error(`No hay datos antes del ${fd(s.f[0])}.`);
      const tasa = b.valor - a.valor;
      return { coef: 1 + tasa / 100, total: r2(monto * (1 + tasa / 100)), detalle: `Tasa acumulada en el período: ${pct(tasa, 4)} (diferencia entre ${pct(a.valor, 4)} y ${pct(b.valor, 4)})`, aviso };
    }
    if (s.tipo === 'mensual') {
      // inflación: se capitalizan los meses posteriores al mes inicial hasta el mes final
      const mi = desde.slice(0, 7), mf = hasta.slice(0, 7);
      let coef = 1, meses = 0, ultimo = '';
      s.f.forEach((f, i) => { const m = f.slice(0, 7); if (m > mi && m <= mf) { coef *= 1 + s.v[i] / 100; meses++; ultimo = m; } });
      if (!meses) throw new Error('Todavía no hay inflación publicada para ese período.');
      const falta = ultimo < mf ? `El INDEC publicó hasta ${ultimo.slice(5)}/${ultimo.slice(0, 4)}: los meses siguientes no están incluidos.` : '';
      return { coef, total: r2(monto * coef), detalle: `${meses} meses de inflación, acumulada ${pct((coef - 1) * 100)}`, aviso: falta };
    }
    // tna: tasa diaria del día (si un día no hay dato, se usa el último informado)
    let fac = modo === 'compuesto' ? 1 : 0, dias = 0;
    const ini = valorEn(s, desde);
    if (!ini) throw new Error(`No hay datos antes del ${fd(s.f[0])}.`);
    let i = ini.i;
    for (let d = F(desde); iso(d) < hasta; d = new Date(d.getTime() + DIA)) {
      const hoy = iso(d);
      while (i + 1 < s.f.length && s.f[i + 1] <= hoy) i++;
      const td = s.v[i] / 100 / 365;
      if (modo === 'compuesto') fac *= 1 + td; else fac += td;
      dias++;
    }
    const coef = modo === 'compuesto' ? fac : 1 + fac;
    return { coef, total: r2(monto * coef), detalle: `${dias} días, interés ${pct((coef - 1) * 100)} (${modo === 'compuesto' ? 'capitalizado diariamente' : 'interés simple'})`, aviso };
  }
  function tasaFija(monto, desde, hasta, tna, modo) {
    if (!(monto > 0) || !(tna >= 0)) throw new Error('Revisá el monto y la tasa.');
    if (!desde || !hasta || hasta <= desde) throw new Error('La fecha final tiene que ser posterior a la inicial.');
    const dias = Math.round((F(hasta) - F(desde)) / DIA);
    const coef = modo === 'compuesto' ? Math.pow(1 + tna / 100 / 365, dias) : 1 + tna / 100 * dias / 365;
    return { coef, total: r2(monto * coef), detalle: `${dias} días a ${pct(tna)} TNA (${modo === 'compuesto' ? 'capitalizado diariamente' : 'interés simple'})`, aviso: '' };
  }

  function contarHabiles(desde, hasta, feriados) {
    if (!desde || !hasta || hasta < desde) throw new Error('La fecha final tiene que ser igual o posterior a la inicial.');
    const set = new Set(feriados);
    let habiles = 0, corridos = 0, finde = 0, fer = [];
    for (let d = new Date(F(desde).getTime() + DIA); iso(d) <= hasta; d = new Date(d.getTime() + DIA)) {
      corridos++;
      const dow = d.getUTCDay(), s = iso(d);
      if (dow === 0 || dow === 6) finde++;
      else if (set.has(s)) fer.push(s);
      else habiles++;
    }
    return { habiles, corridos, finde, feriados: fer };
  }
  function sumarHabiles(desde, n, feriados) {
    if (!desde || !(n > 0)) throw new Error('Cargá la fecha y la cantidad de días hábiles.');
    const set = new Set(feriados);
    let d = F(desde), k = 0;
    while (k < n) { d = new Date(d.getTime() + DIA); const dow = d.getUTCDay(); if (dow !== 0 && dow !== 6 && !set.has(iso(d))) k++; }
    return iso(d);
  }

  function plazoFijo(monto, tna, dias, renov = 1) {
    if (!(monto > 0) || !(tna > 0) || !(dias >= 30)) throw new Error('Monto y tasa mayores a cero; plazo mínimo 30 días.');
    const interes = r2(monto * tna / 100 * dias / 365);
    const tea = (Math.pow(1 + tna / 100 * dias / 365, 365 / dias) - 1) * 100;
    let capital = monto;
    for (let i = 0; i < renov; i++) capital = capital * (1 + tna / 100 * dias / 365);
    return { interes, total: r2(monto + interes), tea, tem: tna * 30 / 365, renovado: r2(capital) };
  }

  function prestamo(monto, tna, n, sistema = 'frances') {
    if (!(monto > 0) || !(tna > 0) || !(n >= 1 && n <= 480)) throw new Error('Revisá monto, tasa y cantidad de cuotas (1 a 480).');
    const i = tna / 100 / 12;
    const filas = [];
    let saldo = monto, totInt = 0, totCuota = 0;
    const cuotaF = monto * i / (1 - Math.pow(1 + i, -n));
    for (let k = 1; k <= n; k++) {
      const interes = saldo * i;
      const amort = sistema === 'frances' ? cuotaF - interes : monto / n;
      const cuota = amort + interes;
      saldo -= amort;
      totInt += interes; totCuota += cuota;
      filas.push([k, cuota, interes, amort, Math.max(0, saldo)]);
    }
    return { filas, totInt: r2(totInt), totCuota: r2(totCuota), primera: r2(filas[0][1]), tem: i * 100, tea: (Math.pow(1 + i, 12) - 1) * 100 };
  }

  // Ley de Contrato de Trabajo, art. 150: días de vacaciones según antigüedad al 31/12
  function diasVacaciones(ingreso, anio) {
    const fin = F(`${anio}-12-31`), ing = F(ingreso);
    let anios = fin.getUTCFullYear() - ing.getUTCFullYear();
    if (fin.getUTCMonth() < ing.getUTCMonth() || (fin.getUTCMonth() === ing.getUTCMonth() && fin.getUTCDate() < ing.getUTCDate())) anios--;
    const meses = (fin - ing) / DIA / 30.4375;
    const dias = anios < 5 ? 14 : anios < 10 ? 21 : anios < 20 ? 28 : 35;
    return { dias, anios: Math.max(0, anios), meses };
  }
  function vacaciones({ ingreso, anio, sueldo, tipo = 'mensual', jornal = 0, feriados = [] }) {
    if (!ingreso) throw new Error('Cargá la fecha de ingreso.');
    if (ingreso > `${anio}-12-31`) throw new Error('La fecha de ingreso es posterior al año elegido.');
    const v = diasVacaciones(ingreso, anio);
    let dias = v.dias, art153 = false, trabajados = 0;
    // art. 153: si no trabajó la mitad de los días hábiles del año, 1 día cada 20 trabajados
    if (ingreso > `${anio}-01-01`) {
      const totalAnio = contarHabiles(`${anio - 1}-12-31`, `${anio}-12-31`, feriados).habiles;
      const prev = new Date(F(ingreso).getTime() - DIA);
      trabajados = contarHabiles(iso(prev), `${anio}-12-31`, feriados).habiles;
      if (trabajados < totalAnio / 2) { dias = Math.floor(trabajados / 20); art153 = true; }
    }
    let valorDia, normal = 0, plus = 0;
    if (tipo === 'mensual') {
      if (!(sueldo > 0)) throw new Error('Cargá el sueldo mensual.');
      valorDia = sueldo / 25; normal = sueldo / 30;
      plus = r2((valorDia - normal) * dias);
    } else {
      if (!(jornal > 0)) throw new Error('Cargá el valor del jornal.');
      valorDia = jornal;
    }
    return { ...v, dias, art153, trabajados, valorDia: r2(valorDia), total: r2(valorDia * dias), plus };
  }

  function liquidacion({ ingreso, egreso, motivo, sueldo, mejor, tope = 0, preavisoOtorgado = false, prueba = false, vacGozadas = 0, sacVac = true }) {
    if (!ingreso || !egreso || egreso < ingreso) throw new Error('Revisá las fechas de ingreso y egreso.');
    if (!(sueldo > 0)) throw new Error('Cargá el sueldo mensual.');
    mejor = mejor > 0 ? mejor : sueldo;
    const e = F(egreso), y = e.getUTCFullYear(), m = e.getUTCMonth();
    const diaMes = e.getUTCDate(), diasMes = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const items = [];
    const add = (n, v, nota, tipo = 'rem') => { if (v > 0) items.push({ n, v: r2(v), nota, tipo }); };
    add(`Días trabajados del mes (${diaMes})`, sueldo / 30 * Math.min(diaMes, 30), 'Sueldo ÷ 30 × días trabajados del mes de egreso.');
    // SAC proporcional del semestre
    const iniSem = F(`${y}-${m < 6 ? '01' : '07'}-01`), desdeSem = F(ingreso) > iniSem ? F(ingreso) : iniSem;
    const diasSem = Math.round((e - desdeSem) / DIA) + 1, totSem = m < 6 ? ((y % 4 === 0 && y % 100) || y % 400 === 0 ? 182 : 181) : 184;
    add(`SAC proporcional (${diasSem} días del semestre)`, mejor / 2 * diasSem / totSem, 'Mejor remuneración del semestre ÷ 2, proporcional a los días trabajados (Ley 23.041).');
    // vacaciones no gozadas proporcionales (art. 156)
    const v = diasVacaciones(ingreso, y);
    const iniAnio = F(`${y}-01-01`), desdeAnio = F(ingreso) > iniAnio ? F(ingreso) : iniAnio;
    const diasAnio = Math.round((e - desdeAnio) / DIA) + 1;
    const diasVac = Math.max(0, v.dias * diasAnio / 365 - vacGozadas);
    const vac = sueldo / 25 * diasVac;
    add(`Vacaciones no gozadas (${diasVac.toLocaleString('es-AR', { maximumFractionDigits: 2 })} días)`, vac, `Corresponden ${v.dias} días por año según antigüedad, en proporción a lo trabajado en el año, a sueldo ÷ 25 (arts. 150, 155 y 156 LCT).`, 'no');
    if (sacVac) add('SAC sobre vacaciones no gozadas', vac / 12, 'Criterio habitual en la práctica: un doceavo de las vacaciones no gozadas.', 'no');
    let antig = 0;
    if (motivo === 'sin_causa' && !prueba) {
      const ing = F(ingreso);
      let anios = y - ing.getUTCFullYear();
      let mesesRest = (m - ing.getUTCMonth()) + (diaMes < ing.getUTCDate() ? -1 : 0);
      if (mesesRest < 0) { anios--; mesesRest += 12; }
      const periodos = Math.max(1, anios + (mesesRest >= 3 && (mesesRest > 3 || diaMes !== ing.getUTCDate()) ? 1 : 0));
      let base = mejor;
      if (tope > 0) base = Math.max(Math.min(mejor, tope), mejor * 0.67);
      antig = Math.max(base * periodos, sueldo);
      add(`Indemnización por antigüedad (${periodos} ${periodos === 1 ? 'período' : 'períodos'})`, antig,
        `Mejor remuneración mensual, normal y habitual${tope > 0 ? ` con el tope del convenio (nunca menos del 67% de la remuneración)` : ''} × años de servicio o fracción mayor a 3 meses (art. 245 LCT). Según la Ley 27.802, la base no incluye SAC ni premios que no sean mensuales.`, 'ind');
      if (!preavisoOtorgado) {
        const mesesPre = (anios + mesesRest / 12) >= 5 ? 2 : 1;
        const pre = sueldo * mesesPre;
        add(`Indemnización sustitutiva del preaviso (${mesesPre} ${mesesPre === 1 ? 'mes' : 'meses'})`, pre, '1 mes hasta 5 años de antigüedad y 2 meses desde los 5 años (arts. 231 y 232 LCT).', 'ind');
        const integ = diaMes < diasMes ? sueldo / 30 * Math.max(0, 30 - Math.min(diaMes, 30)) : 0;
        add(`Integración del mes de despido (${Math.max(0, 30 - Math.min(diaMes, 30))} días)`, integ, 'Días que faltan para terminar el mes, cuando el despido no coincide con el último día (art. 233 LCT).', 'ind');
        add('SAC sobre preaviso e integración', (pre + integ) / 12, 'Criterio habitual en la práctica: un doceavo del preaviso y la integración.', 'ind');
      }
    }
    const total = r2(items.reduce((s, x) => s + x.v, 0));
    return { items, total, rem: r2(items.filter(x => x.tipo === 'rem').reduce((s, x) => s + x.v, 0)) };
  }

  function horasExtras({ sueldo, divisor, h50, h100 }) {
    if (!(sueldo > 0) || !(divisor > 0)) throw new Error('Cargá el sueldo y las horas mensuales.');
    const hora = sueldo / divisor;
    return { hora: r2(hora), v50: r2(hora * 1.5 * (h50 || 0)), v100: r2(hora * 2 * (h100 || 0)), total: r2(hora * 1.5 * (h50 || 0) + hora * 2 * (h100 || 0)) };
  }

  function iva(monto, alicuota, modo) {
    if (!(monto > 0)) throw new Error('Cargá un monto mayor a cero.');
    if (modo === 'agregar') return { neto: r2(monto), iva: r2(monto * alicuota / 100), total: r2(monto * (1 + alicuota / 100)) };
    const neto = monto / (1 + alicuota / 100);
    return { neto: r2(neto), iva: r2(monto - neto), total: r2(monto) };
  }

  window.RCCalcs = { actualizar, tasaFija, contarHabiles, sumarHabiles, plazoFijo, prestamo, vacaciones, diasVacaciones, liquidacion, horasExtras, iva, numero, valorEn };

  // ---------- interfaz ----------
  const form = document.getElementById('calc');
  if (!form) return;
  const salida = document.getElementById('resultado'), err = document.getElementById('err');
  const mostrar = html => { salida.innerHTML = html; salida.hidden = false; salida.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  const hoy = iso(new Date(Date.now() - new Date().getTimezoneOffset() * 60000));
  form.querySelectorAll('input[type=date][data-hoy]').forEach(i => { if (!i.value) i.value = hoy; });
  let feriados = null;
  const cargarFeriados = () => feriados || (feriados = fetch('datos/feriados.json').then(r => r.json()).catch(() => ({ fechas: [], anios: [] })));
  const tipo = form.dataset.calc;
  const tabla = filas => `<table class="tabla-desc"><tbody>${filas.map(f => `<tr${f[2] ? ' class="tot"' : ''}><td>${f[0]}</td><td>${f[1]}</td></tr>`).join('')}</tbody></table>`;

  const etiqueta = (sel, textos) => { const f = () => { form.querySelector('[data-etq]').textContent = textos[sel.value]; }; sel.addEventListener('change', f); f(); };

  if (tipo === 'actualizacion') {
    etiqueta(form.sentido, { adelante: 'Monto en la fecha inicial', atras: 'Monto en la fecha final' });
    const metodo = form.metodo, fija = form.querySelector('[data-fija]'), modoBox = form.querySelector('[data-modo]');
    const ver = () => { const v = metodo.value; fija.hidden = v !== 'fija'; modoBox.hidden = !(v === 'fija' || ['badlar', 'tamar', 'plazo_fijo', 'personales'].includes(v)); };
    metodo.addEventListener('change', ver); ver();
    fetch('datos/series.json').then(r => r.json()).then(info => {
      const box = document.getElementById('ultimos');
      if (box) box.innerHTML = Object.values(info).map(s => `<li><span>${esc(s.nombre)}</span><b>${fd(s.hasta)}</b></li>`).join('');
    }).catch(() => {});
    form.addEventListener('submit', async ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const monto = numero(form.monto.value), desde = form.desde.value, hasta = form.hasta.value, modo = form.modo.value;
        const v = metodo.value;
        const atras = form.sentido.value === 'atras';
        const calc = (m, s) => s ? actualizar(s, m, desde, hasta, modo) : tasaFija(m, desde, hasta, numero(form.tna.value), modo);
        const base = calc(monto, v === 'fija' ? null : await serie(v));
        // hacia atrás: se divide por el mismo coeficiente
        const r = atras ? { ...base, total: r2(monto / base.coef) } : base;
        let comp = '';
        if (form.comparar.checked) {
          const claves = ['ipc', 'cer', 'uva', 'icl', 'dolar_minorista', 'dolar_mayorista', 'justicia', 'plazo_fijo', 'badlar'];
          const filas = [];
          for (const k of claves) {
            try { const s = await serie(k); const x = actualizar(s, monto, desde, hasta, 'simple'); filas.push([esc(s.nombre), fmt(atras ? monto / x.coef : x.total), pct((x.coef - 1) * 100)]); } catch (e) { /* sin datos para esa fecha */ }
          }
          comp = `<h3>Comparación con todos los índices</h3><table class="tabla-desc"><thead><tr><th>Índice o tasa</th><th>${atras ? `Equivale al ${fd(desde)}` : `Equivale al ${fd(hasta)}`}</th><th>Variación</th></tr></thead><tbody>${filas.map(f => `<tr><td>${f[0]}</td><td>${f[1]}</td><td>${f[2]}</td></tr>`).join('')}</tbody></table>`;
        }
        mostrar(`<div class="res-top"><div><span>${atras ? 'Monto al ' + fd(hasta) : 'Monto al ' + fd(desde)}</span><b>${fmt(monto)}</b></div><div><span>Variación del período</span><b>${pct((r.coef - 1) * 100)}</b></div><div class="neto"><span>${atras ? 'Equivale al ' + fd(desde) : 'Equivale al ' + fd(hasta)}</span><b>${fmt(r.total)}</b></div></div>
          <p>Coeficiente: <b>${r.coef.toLocaleString('es-AR', { maximumFractionDigits: 6 })}</b> · ${esc(r.detalle)}</p>${r.aviso ? `<p class="nota-chica">${esc(r.aviso)}</p>` : ''}${comp}`);
      } catch (e) { err.textContent = e.message === 'sin datos' ? 'No se pudieron cargar los datos del BCRA. Probá de nuevo en un rato.' : e.message; salida.hidden = true; }
    });
  }

  if (tipo === 'dias') {
    form.addEventListener('submit', async ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const fer = await cargarFeriados();
        const fuera = [form.desde.value, form.hasta.value].map(x => (x || '').slice(0, 4)).filter(a => a && !fer.anios.includes(a));
        const avisoAnio = fuera.length ? `<p class="nota-chica">Para ${[...new Set(fuera)].join(' y ')} todavía no tenemos cargados los feriados: solo se descuentan sábados y domingos.</p>` : '';
        let html = '';
        if (form.hasta.value) {
          const r = contarHabiles(form.desde.value, form.hasta.value, fer.fechas);
          html += `<div class="res-top"><div><span>Días corridos</span><b>${r.corridos}</b></div><div><span>Fines de semana y feriados</span><b>${r.finde + r.feriados.length}</b></div><div class="neto"><span>Días hábiles</span><b>${r.habiles}</b></div></div>
            <p class="nota-chica">Se cuenta desde el día siguiente a la fecha inicial hasta la fecha final, inclusive.</p>${r.feriados.length ? `<p>Feriados descontados: ${r.feriados.map(fd).join(', ')}.</p>` : ''}`;
        }
        if (numero(form.n.value) > 0) {
          const f = sumarHabiles(form.desde.value, numero(form.n.value), fer.fechas);
          html += `<div class="res-top uno"><div class="neto"><span>${numero(form.n.value)} días hábiles después del ${fd(form.desde.value)}</span><b>${fd(f)}</b></div></div>`;
        }
        if (!html) throw new Error('Cargá la fecha final o la cantidad de días hábiles a sumar.');
        mostrar(html + avisoAnio);
      } catch (e) { err.textContent = e.message; salida.hidden = true; }
    });
  }

  if (tipo === 'plazofijo') {
    etiqueta(form.sentido, { inicio: 'Capital que invertís hoy', final: 'Monto que querés cobrar al vencimiento' });
    serie('plazo_fijo').then(s => { if (!form.tna.value) form.tna.value = String(s.v[s.v.length - 1]).replace('.', ','); }).catch(() => {});
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        let capital = numero(form.monto.value);
        const tna = numero(form.tna.value), dias = numero(form.dias.value), renov = numero(form.renov.value) || 1;
        if (form.sentido.value === 'final') capital = r2(capital / Math.pow(1 + tna / 100 * dias / 365, renov));
        const r = plazoFijo(capital, tna, dias, renov);
        mostrar(`<div class="res-top"><div><span>Capital inicial</span><b>${fmt(capital)}</b></div><div><span>Intereses del primer plazo</span><b>${fmt(r.interes)}</b></div><div class="neto"><span>${renov > 1 ? `Al final de ${renov} renovaciones` : 'Total al vencimiento'}</span><b>${fmt(renov > 1 ? r.renovado : r.total)}</b></div></div>
          <p>TEA ${pct(r.tea)}</p>
          ${tabla([['Tasa efectiva mensual aproximada', pct(r.tem)], [`Capital si renovás ${numero(form.renov.value) || 1} ${numero(form.renov.value) > 1 ? 'veces' : 'vez'} a la misma tasa`, fmt(r.renovado)]])}
          <p class="nota-chica">Interés = capital × TNA × días ÷ 365. La tasa real depende del banco: el valor sugerido es el promedio de plazo fijo a 30 días que publica el BCRA.</p>`);
      } catch (e) { err.textContent = e.message; salida.hidden = true; }
    });
  }

  if (tipo === 'prestamo') {
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const r = prestamo(numero(form.monto.value), numero(form.tna.value), numero(form.cuotas.value), form.sistema.value);
        const filas = r.filas.length > 24 ? r.filas.slice(0, 12).concat([null]).concat(r.filas.slice(-6)) : r.filas;
        mostrar(`<div class="res-top"><div><span>${form.sistema.value === 'frances' ? 'Cuota fija' : 'Primera cuota'}</span><b>${fmt(r.primera)}</b></div><div><span>Total de intereses</span><b>${fmt(r.totInt)}</b></div><div class="neto"><span>Total a pagar</span><b>${fmt(r.totCuota)}</b></div></div>
          <p>TEM ${pct(r.tem)} · TEA ${pct(r.tea)}</p>
          <div class="tabla"><table class="tabla-desc"><thead><tr><th>N°</th><th>Cuota</th><th>Interés</th><th>Capital</th><th>Saldo</th></tr></thead><tbody>
          ${filas.map(f => f ? `<tr><td>${f[0]}</td><td>${fmt(f[1])}</td><td>${fmt(f[2])}</td><td>${fmt(f[3])}</td><td>${fmt(f[4])}</td></tr>` : '<tr><td colspan="5">…</td></tr>').join('')}</tbody></table></div>
          <p class="nota-chica">No incluye IVA sobre intereses, seguros ni gastos: el costo financiero total (CFT) del banco es mayor.</p>`);
      } catch (e) { err.textContent = e.message; salida.hidden = true; }
    });
  }

  if (tipo === 'vacaciones') {
    form.tipo.addEventListener('change', () => { form.querySelector('[data-jornal]').hidden = form.tipo.value !== 'jornal'; form.querySelector('[data-sueldo]').hidden = form.tipo.value === 'jornal'; });
    form.addEventListener('submit', async ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const fer = await cargarFeriados();
        const r = vacaciones({ ingreso: form.ingreso.value, anio: Number(form.anio.value), sueldo: numero(form.sueldo.value), tipo: form.tipo.value, jornal: numero(form.jornal.value), feriados: fer.fechas });
        mostrar(`<div class="res-top"><div><span>Días de vacaciones</span><b>${r.dias}</b></div><div><span>Valor por día</span><b>${fmt(r.valorDia)}</b></div><div class="neto"><span>Total de vacaciones</span><b>${fmt(r.total)}</b></div></div>
          ${tabla([['Antigüedad al 31/12', `${r.anios} ${r.anios === 1 ? 'año' : 'años'}`],
            ['Días que corresponden', r.art153 ? `${r.dias} (1 día cada 20 hábiles trabajados: trabajó ${r.trabajados} días hábiles, menos de la mitad del año · art. 153 LCT)` : `${r.dias} días corridos (art. 150 LCT)`],
            ...(form.tipo.value === 'mensual' ? [['Cálculo del día', 'Sueldo ÷ 25 (art. 155 LCT)'], ['Plus vacacional (diferencia contra sueldo ÷ 30)', fmt(r.plus)]] : [['Cálculo del día', 'Valor del jornal']])])}
          <p class="nota-chica">Las vacaciones se pagan al inicio del descanso. El período para otorgarlas es entre el 1 de octubre y el 30 de abril, con aviso de 45 días (art. 154 LCT). Algunos convenios dan más días: verificá el tuyo.</p>`);
      } catch (e) { err.textContent = e.message; salida.hidden = true; }
    });
  }

  if (tipo === 'liquidacion') {
    const ver = () => { form.querySelector('[data-despido]').hidden = form.motivo.value !== 'sin_causa'; };
    form.motivo.addEventListener('change', ver); ver();
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const r = liquidacion({ ingreso: form.ingreso.value, egreso: form.egreso.value, motivo: form.motivo.value, sueldo: numero(form.sueldo.value), mejor: numero(form.mejor.value),
          tope: numero(form.tope.value), preavisoOtorgado: form.preaviso.checked, prueba: form.prueba.checked, vacGozadas: numero(form.gozadas.value), sacVac: form.sacvac.checked });
        const grupos = { rem: 'Conceptos remunerativos (llevan aportes)', no: 'Vacaciones no gozadas', ind: 'Indemnizaciones (no llevan aportes)' };
        let html = `<div class="res-top uno"><div class="neto"><span>Total bruto estimado</span><b>${fmt(r.total)}</b></div></div>`;
        for (const [g, t] of Object.entries(grupos)) {
          const it = r.items.filter(x => x.tipo === g);
          if (it.length) html += `<h3>${t}</h3><ol class="pasos-sac">${it.map(x => `<li><p><b>${esc(x.n)}:</b> ${fmt(x.v)}</p><span class="porque">${esc(x.nota)}</span></li>`).join('')}</ol>`;
        }
        html += `<p class="nota-chica">Sobre los conceptos remunerativos (${fmt(r.rem)}) se descuentan aportes (jubilación 11%, PAMI 3%, obra social 3%) y, si corresponde, cuota sindical. No incluye multas, horas extras ni conceptos particulares del convenio.</p>`;
        mostrar(html);
      } catch (e) { err.textContent = e.message; salida.hidden = true; }
    });
  }

  if (tipo === 'horas') {
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const r = horasExtras({ sueldo: numero(form.sueldo.value), divisor: numero(form.divisor.value), h50: numero(form.h50.value), h100: numero(form.h100.value) });
        mostrar(`<div class="res-top"><div><span>Valor hora normal</span><b>${fmt(r.hora)}</b></div><div><span>Horas al 50% / al 100%</span><b>${fmt(r.v50)} / ${fmt(r.v100)}</b></div><div class="neto"><span>Total horas extras</span><b>${fmt(r.total)}</b></div></div>
          <p class="nota-chica">Valor hora = sueldo ÷ horas mensuales. Recargo del 50% en días comunes y del 100% en sábados después de las 13, domingos y feriados (art. 201 LCT). Las horas extras son remunerativas: llevan aportes y suman para el aguinaldo.</p>`);
      } catch (e) { err.textContent = e.message; salida.hidden = true; }
    });
  }

  if (tipo === 'iva') {
    form.addEventListener('submit', ev => {
      ev.preventDefault(); err.textContent = '';
      try {
        const r = iva(numero(form.monto.value), numero(form.alicuota.value), form.modo.value);
        mostrar(`<div class="res-top"><div><span>Neto gravado</span><b>${fmt(r.neto)}</b></div><div><span>IVA ${form.alicuota.value.replace('.', ',')}%</span><b>${fmt(r.iva)}</b></div><div class="neto"><span>Total con IVA</span><b>${fmt(r.total)}</b></div></div>`);
      } catch (e) { err.textContent = e.message; salida.hidden = true; }
    });
  }
})();
