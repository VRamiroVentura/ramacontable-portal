/* Ramacontable · ¿Cuánto me pagan si trabajo un feriado? (LCT arts. 166 a 169 y 201).
   Mensualizados: el feriado ya está en el sueldo; si lo trabajan cobran además un día a sueldo ÷ 25.
   Jornalizados: si lo trabajan, doble por las horas trabajadas; si no, el jornal simple (con el requisito del art. 169).
   Días no laborables: decide el empleador y se pagan simple, sin recargo. */
(function () {
  const fmt = n => '$ ' + Number(n).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function numero(txt) {
    const t = String(txt == null ? '' : txt).trim().replace(/\$|\s|%/g, '');
    if (!t) return 0;
    const n = /,\d{1,4}$/.test(t) || (t.includes('.') && t.includes(',')) ? Number(t.replace(/\./g, '').replace(',', '.'))
      : (/^\d{1,3}(\.\d{3})+$/.test(t) ? Number(t.replace(/\./g, '')) : Number(t.replace(',', '.')));
    return isFinite(n) ? n : NaN;
  }
  const r2 = n => Math.round(n * 100) / 100;

  function feriado(p) {
    const filas = [];
    let extra = 0, nota = '';
    if (p.tipo === 'mensual') {
      if (!(p.sueldo > 0)) throw new Error('Cargá tu sueldo mensual bruto.');
      const dia = r2(p.sueldo / 25);
      if (p.dia === 'feriado' && p.trabajo) {
        extra = dia;
        filas.push(['Sueldo del mes (ya incluye el feriado)', fmt(p.sueldo)], ['Adicional por trabajar el feriado (sueldo ÷ 25)', fmt(dia)]);
        nota = 'Cobrás tu sueldo normal y, además, un día más a sueldo ÷ 25: en total el feriado te queda pago doble.';
      } else if (p.dia === 'feriado') {
        filas.push(['Sueldo del mes (ya incluye el feriado)', fmt(p.sueldo)], ['Adicional', fmt(0)]);
        nota = 'Si no lo trabajás no te descuentan nada: el feriado ya está pago dentro del sueldo mensual.';
      } else {
        filas.push(['Sueldo del mes', fmt(p.sueldo)], ['Adicional', fmt(0)]);
        nota = p.trabajo ? 'El día no laborable trabajado se paga como un día común: no tiene recargo.'
          : 'Si tu empleador no abre, no te descuentan nada: cobrás el sueldo igual.';
      }
      return { extra, total: r2(p.sueldo + extra), filas, nota, totalTxt: 'Total del mes' };
    }
    if (!(p.hora > 0)) throw new Error('Cargá el valor de tu hora.');
    const jornada = p.jornada > 0 ? p.jornada : 8;
    if (p.trabajo && !(p.horas > 0)) throw new Error('Cargá cuántas horas trabajaste ese día.');
    let dia = 0;
    if (p.dia === 'feriado' && p.trabajo) {
      dia = r2(p.hora * p.horas * 2);
      filas.push([`${p.horas} h × ${fmt(p.hora)} × 2 (pago doble)`, fmt(dia)]);
      nota = 'Las horas trabajadas en el feriado se pagan dobles.';
    } else if (p.dia === 'feriado') {
      dia = r2(p.hora * jornada);
      filas.push([`Jornal simple: ${jornada} h × ${fmt(p.hora)}`, fmt(dia)]);
      nota = 'Te pagan el jornal aunque no trabajes si trabajaste para el mismo empleador 48 horas o 6 jornadas en los 10 días hábiles anteriores al feriado (art. 169).';
    } else if (p.trabajo) {
      dia = r2(p.hora * p.horas);
      filas.push([`${p.horas} h × ${fmt(p.hora)} (sin recargo)`, fmt(dia)]);
      nota = 'El día no laborable trabajado se paga simple: sin recargo.';
    } else {
      dia = r2(p.hora * jornada);
      filas.push([`Jornal simple: ${jornada} h × ${fmt(p.hora)}`, fmt(dia)]);
      nota = 'Si tu empleador no abre el día no laborable, se paga el jornal simple.';
    }
    return { extra: dia, total: dia, filas, nota, totalTxt: 'Te pagan por ese día' };
  }

  const form = document.getElementById('calc-feriado');
  if (!form) { window.RCFeriado = { feriado }; return; }
  const salida = document.getElementById('resultado-feriado'), err = form.querySelector('.error');
  const ver = () => {
    const j = form.tipo.value === 'jornal', t = form.trabajo.value === 'si';
    form.querySelector('[data-mensual]').hidden = j;
    form.querySelector('[data-jornal]').hidden = !j;
    form.querySelector('[data-horas]').hidden = !(j && t);
  };
  form.tipo.addEventListener('change', ver); form.trabajo.addEventListener('change', ver); ver();
  form.addEventListener('submit', ev => {
    ev.preventDefault(); err.textContent = '';
    try {
      const p = { tipo: form.tipo.value, dia: form.dia.value, trabajo: form.trabajo.value === 'si', sueldo: numero(form.sueldo.value),
        hora: numero(form.hora.value), jornada: numero(form.jornada.value), horas: numero(form.horas.value) };
      if ([p.sueldo, p.hora, p.jornada, p.horas].some(isNaN)) throw new Error('Revisá los números.');
      const r = feriado(p);
      salida.innerHTML = `<p class="res-grande">${r.totalTxt}: <b>${fmt(r.total)}</b></p>`
        + '<div class="tabla"><table><tbody>' + r.filas.map(f => `<tr><td>${f[0]}</td><td>${f[1]}</td></tr>`).join('') + '</tbody></table></div>'
        + `<p class="ayuda">${r.nota} Si además hacés horas extras ese día, se pagan con un recargo del 100% (art. 201).</p>`
        + '<p class="ayuda">Montos brutos: sobre el total se descuentan los aportes (jubilación, PAMI y obra social).</p>';
      salida.hidden = false;
    } catch (e) { err.textContent = e.message; salida.hidden = true; }
  });
  window.RCFeriado = { feriado };
})();
