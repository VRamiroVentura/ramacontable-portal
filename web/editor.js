/* Ramacontable · editor del paso a paso
   - Limpia lo que se pega desde Excel / Word (solo tablas, texto y formato).
   - Convierte en el navegador .xlsx, .docx, .pdf e imágenes: el archivo original nunca se sube.
   - Las imágenes (capturas o páginas de PDF) se redibujan como JPG nuevos antes de subir. */
window.RCEditor = (function () {
  const TAGS = ['table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'colgroup', 'col', 'caption', 'p', 'br', 'b', 'strong', 'i', 'em', 'u', 's',
    'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'span', 'div', 'img', 'sub', 'sup', 'hr', 'blockquote'];
  const ATTRS = ['colspan', 'rowspan', 'style', 'align', 'valign', 'src', 'alt', 'width'];
  const CSS_OK = ['color', 'background', 'background-color', 'font-weight', 'font-style', 'text-align', 'vertical-align', 'text-decoration',
    'border', 'border-top', 'border-bottom', 'border-left', 'border-right', 'white-space', 'padding', 'padding-left', 'text-indent'];
  let prefijoImg = '';
  let listo = false;

  function configurar(urlSupabase) {
    prefijoImg = (urlSupabase || '').replace(/\/$/, '') + '/storage/v1/object/public/pasos/';
    if (listo || !window.DOMPurify) return;
    listo = true;
    DOMPurify.addHook('uponSanitizeAttribute', (nodo, d) => {
      if (d.attrName === 'style') {
        const limpio = d.attrValue.split(';').map(x => x.trim()).filter(Boolean).filter(dec => {
          const [p, ...v] = dec.split(':'); const prop = (p || '').trim().toLowerCase(); const val = v.join(':').toLowerCase();
          return CSS_OK.includes(prop) && !/url\(|expression|javascript|@import|position|behavior/.test(val);
        }).join(';');
        if (!limpio) d.keepAttr = false; else d.attrValue = limpio;
      }
      if (d.attrName === 'src') {
        if (nodo.nodeName !== 'IMG' || !prefijoImg || !d.attrValue.startsWith(prefijoImg)) d.keepAttr = false;
      }
    });
    DOMPurify.addHook('afterSanitizeAttributes', nodo => {
      if (nodo.nodeName === 'IMG' && !nodo.getAttribute('src')) nodo.remove();
    });
  }
  function limpiar(html) {
    return DOMPurify.sanitize(html, { ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ATTRS, ALLOW_DATA_ATTR: false });
  }

  // Excel pone los formatos en <style> con clases (xl65, etc.): los pasamos a cada celda antes de limpiar
  function estilosEnLinea(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const css = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n').replace(/<!--|-->/g, '');
    const reglas = css.replace(/\/\*[\s\S]*?\*\//g, '').match(/[^{}]+\{[^{}]*\}/g) || [];
    reglas.forEach(r => {
      const i = r.indexOf('{'); const sel = r.slice(0, i).trim(); const decl = r.slice(i + 1, -1).trim();
      if (!sel || sel.startsWith('@')) return;
      sel.split(',').map(s => s.trim()).forEach(s => {
        if (!/^[a-z0-9.\s_-]+$/i.test(s)) return;
        try { doc.body.querySelectorAll(s).forEach(el => el.setAttribute('style', decl + ';' + (el.getAttribute('style') || ''))); } catch (e) { }
      });
    });
    // Excel usa "background:#xxxx" o "mso-pattern": dejamos solo lo que CSS_OK reconoce
    doc.querySelectorAll('[class]').forEach(el => el.removeAttribute('class'));
    return doc.body.innerHTML;
  }
  function desdePegado(datos) {
    const html = datos.getData('text/html');
    if (html) return limpiar(estilosEnLinea(html));
    const txt = datos.getData('text/plain');
    if (!txt) return '';
    if (txt.includes('\t')) { // tabla pegada como texto
      const filas = txt.replace(/\r/g, '').split('\n').filter(f => f.length);
      return limpiar('<table>' + filas.map(f => '<tr>' + f.split('\t').map(c => '<td>' + esc(c) + '</td>').join('') + '</tr>').join('') + '</table>');
    }
    return limpiar(txt.split(/\n{2,}/).map(p => '<p>' + esc(p).replace(/\n/g, '<br>') + '</p>').join(''));
  }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // ---------- imágenes: se redibujan como JPG nuevo ----------
  async function canvasDeArchivo(blob) {
    const bmp = await createImageBitmap(blob);
    const escala = Math.min(1, 1400 / bmp.width);
    const c = document.createElement('canvas'); c.width = Math.round(bmp.width * escala); c.height = Math.round(bmp.height * escala);
    const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); g.drawImage(bmp, 0, 0, c.width, c.height);
    return c;
  }
  function aJpg(canvas) {
    return new Promise(ok => {
      const intentar = q => canvas.toBlob(b => (b.size > 950000 && q > 0.45) ? intentar(q - 0.15) : ok(b), 'image/jpeg', q);
      intentar(0.85);
    });
  }

  // ---------- Excel (.xlsx) → tabla ----------
  const XNS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
  function xml(txt) { return new DOMParser().parseFromString(txt, 'application/xml'); }
  function hijos(el, nombre) { return [...el.getElementsByTagNameNS('*', nombre)]; }
  function colNum(ref) { let n = 0; for (const ch of ref.replace(/\d/g, '')) n = n * 26 + ch.charCodeAt(0) - 64; return n - 1; }
  function filaNum(ref) { return parseInt(ref.replace(/\D/g, ''), 10) - 1; }
  function formatoNumero(v, fmtId, fmtCodigo) {
    const n = Number(v); if (!isFinite(n)) return v;
    const cod = fmtCodigo || '';
    if (fmtId === 9 || fmtId === 10 || /%/.test(cod)) return (n * 100).toLocaleString('es-AR', { maximumFractionDigits: 2 }) + '%';
    if ((fmtId >= 14 && fmtId <= 22) || /[dmy]{2}/i.test(cod.replace(/\[[^\]]*\]|"[^"]*"/g, ''))) {
      const d = new Date(Math.round((n - 25569) * 86400000)); return d.toLocaleDateString('es-AR', { timeZone: 'UTC' });
    }
    const dec = /0\.00/.test(cod) || fmtId === 2 || fmtId === 4 ? 2 : (Number.isInteger(n) ? 0 : 2);
    const txt = n.toLocaleString('es-AR', { minimumFractionDigits: dec, maximumFractionDigits: dec });
    return (/\$/.test(cod) ? '$ ' : '') + txt;
  }
  async function xlsxAHtml(archivo) {
    const zip = await JSZip.loadAsync(archivo);
    const leer = async p => zip.file(p) ? zip.file(p).async('string') : null;
    const ss = await leer('xl/sharedStrings.xml');
    const textos = ss ? hijos(xml(ss).documentElement, 'si').map(si => hijos(si, 't').map(t => t.textContent).join('')) : [];
    const est = await leer('xl/styles.xml');
    let xfs = [], fuentes = [], rellenos = [], fmts = {};
    if (est) {
      const d = xml(est);
      hijos(d, 'numFmt').forEach(f => { fmts[+f.getAttribute('numFmtId')] = f.getAttribute('formatCode'); });
      const fonts = hijos(d, 'fonts')[0]; fuentes = fonts ? [...fonts.children].map(f => ({ b: hijos(f, 'b').length > 0, i: hijos(f, 'i').length > 0, color: (hijos(f, 'color')[0] || { getAttribute: () => null }).getAttribute('rgb') })) : [];
      const fills = hijos(d, 'fills')[0]; rellenos = fills ? [...fills.children].map(f => { const fg = hijos(f, 'fgColor')[0]; return fg && fg.getAttribute('rgb'); }) : [];
      const cx = hijos(d, 'cellXfs')[0]; xfs = cx ? [...cx.children].map(x => ({ font: +x.getAttribute('fontId') || 0, fill: +x.getAttribute('fillId') || 0, fmt: +x.getAttribute('numFmtId') || 0, al: (hijos(x, 'alignment')[0] || { getAttribute: () => null }).getAttribute('horizontal') })) : [];
    }
    const wb = xml(await leer('xl/workbook.xml'));
    const rels = xml(await leer('xl/_rels/workbook.xml.rels'));
    const destino = {}; hijos(rels, 'Relationship').forEach(r => { destino[r.getAttribute('Id')] = r.getAttribute('Target'); });
    const hojas = hijos(wb, 'sheet').filter(s => s.getAttribute('state') !== 'hidden').slice(0, 5);
    let salida = '';
    for (const h of hojas) {
      const rid = h.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id') || h.getAttribute('r:id');
      let ruta = destino[rid] || ''; ruta = ruta.startsWith('/') ? ruta.slice(1) : 'xl/' + ruta.replace(/^\.\//, '');
      const txt = await leer(ruta); if (!txt) continue;
      const d = xml(txt); const celdas = {}; let maxF = 0, maxC = 0;
      hijos(d, 'c').forEach(c => {
        const ref = c.getAttribute('r'); const f = filaNum(ref), co = colNum(ref);
        if (f > 300 || co > 40) return;
        const t = c.getAttribute('t'); const v = hijos(c, 'v')[0]; const st = xfs[+c.getAttribute('s') || 0] || {};
        let valor = '';
        if (t === 's' && v) valor = textos[+v.textContent] || '';
        else if (t === 'inlineStr') valor = hijos(c, 't').map(x => x.textContent).join('');
        else if (t === 'b' && v) valor = v.textContent === '1' ? 'VERDADERO' : 'FALSO';
        else if (v) valor = (t === 'str' || t === 'e') ? v.textContent : formatoNumero(v.textContent, st.fmt, fmts[st.fmt]);
        const fu = fuentes[st.font] || {}; const fondo = rellenos[st.fill];
        const css = [fu.b ? 'font-weight:bold' : '', fu.i ? 'font-style:italic' : '', fu.color && fu.color.length === 8 && fu.color !== 'FF000000' ? 'color:#' + fu.color.slice(2) : '',
          fondo && fondo.length === 8 && fondo !== 'FFFFFFFF' ? 'background-color:#' + fondo.slice(2) : '',
          st.al ? 'text-align:' + ({ centerContinuous: 'center' }[st.al] || st.al) : (t === 's' || t === 'str' || t === 'inlineStr' ? '' : 'text-align:right')].filter(Boolean).join(';');
        if (valor !== '' || css.includes('background')) { celdas[f + ':' + co] = { valor, css }; maxF = Math.max(maxF, f); maxC = Math.max(maxC, co); }
      });
      const tapadas = new Set(), span = {};
      hijos(d, 'mergeCell').forEach(m => {
        const [a, b] = m.getAttribute('ref').split(':'); if (!b) return;
        const f1 = filaNum(a), c1 = colNum(a), f2 = filaNum(b), c2 = colNum(b);
        span[f1 + ':' + c1] = { rs: f2 - f1 + 1, cs: c2 - c1 + 1 };
        for (let f = f1; f <= f2; f++) for (let c = c1; c <= c2; c++) if (f !== f1 || c !== c1) tapadas.add(f + ':' + c);
      });
      if (!Object.keys(celdas).length) continue;
      let filas = '';
      for (let f = 0; f <= maxF; f++) {
        let tr = '';
        for (let c = 0; c <= maxC; c++) {
          const k = f + ':' + c; if (tapadas.has(k)) continue;
          const ce = celdas[k] || { valor: '', css: '' }; const sp = span[k];
          tr += `<td${sp && sp.cs > 1 ? ` colspan="${sp.cs}"` : ''}${sp && sp.rs > 1 ? ` rowspan="${sp.rs}"` : ''}${ce.css ? ` style="${ce.css}"` : ''}>${esc(ce.valor)}</td>`;
        }
        filas += `<tr>${tr}</tr>`;
      }
      salida += (hojas.length > 1 ? `<h4>${esc(h.getAttribute('name'))}</h4>` : '') + `<table>${filas}</table>`;
    }
    return limpiar(salida || '<p>La planilla está vacía.</p>');
  }

  // ---------- Word (.docx) → texto con formato ----------
  async function docxAHtml(archivo) {
    const zip = await JSZip.loadAsync(archivo);
    const d = xml(await zip.file('word/document.xml').async('string'));
    const cuerpo = hijos(d, 'body')[0];
    const run = r => {
      const pr = hijos(r, 'rPr')[0];
      let t = ''; [...r.childNodes].forEach(n => { if (n.localName === 't') t += esc(n.textContent); else if (n.localName === 'tab') t += ' &nbsp; '; else if (n.localName === 'br') t += '<br>'; });
      if (!t) return '';
      if (pr) {
        const tiene = n => { const e = hijos(pr, n)[0]; return e && e.getAttribute('w:val') !== '0' && e.getAttribute('w:val') !== 'false'; };
        if (tiene('b')) t = `<b>${t}</b>`; if (tiene('i')) t = `<i>${t}</i>`; if (tiene('u')) t = `<u>${t}</u>`;
        const sh = hijos(pr, 'highlight')[0]; if (sh) t = `<span style="background-color:${sh.getAttribute('w:val')}">${t}</span>`;
      }
      return t;
    };
    const parrafo = p => {
      const pr = hijos(p, 'pPr')[0];
      const estilo = pr && hijos(pr, 'pStyle')[0] ? hijos(pr, 'pStyle')[0].getAttribute('w:val') || '' : '';
      const al = pr && hijos(pr, 'jc')[0] ? hijos(pr, 'jc')[0].getAttribute('w:val') : '';
      const txt = hijos(p, 'r').filter(r => r.parentNode === p || r.parentNode.localName === 'hyperlink').map(run).join('');
      const css = al === 'center' ? ' style="text-align:center"' : al === 'right' || al === 'end' ? ' style="text-align:right"' : '';
      if (/^(Heading|Ttulo|Titulo)\s?1$/i.test(estilo)) return { tag: `<h3${css}>${txt}</h3>` };
      if (/^(Heading|Ttulo|Titulo)\s?[2-9]$/i.test(estilo)) return { tag: `<h4${css}>${txt}</h4>` };
      if ((pr && hijos(pr, 'numPr').length) || /^(List|Lista|Prrafodelista|ListParagraph)/i.test(estilo)) return { li: txt };
      return { tag: `<p${css}>${txt || '&nbsp;'}</p>` };
    };
    const tabla = tb => '<table>' + [...tb.children].filter(n => n.localName === 'tr').map(tr => '<tr>' + [...tr.children].filter(n => n.localName === 'tc').map(tc => {
      const pr = hijos(tc, 'tcPr')[0]; const gs = pr && hijos(pr, 'gridSpan')[0]; const sh = pr && hijos(pr, 'shd')[0];
      const fill = sh && sh.getAttribute('w:fill'); const vm = pr && hijos(pr, 'vMerge')[0];
      if (vm && vm.getAttribute('w:val') !== 'restart') return '';
      const contenido = [...tc.children].filter(n => n.localName === 'p').map(p => { const r = parrafo(p); return r.tag || r.li; }).join('');
      return `<td${gs ? ` colspan="${gs.getAttribute('w:val')}"` : ''}${fill && fill !== 'auto' ? ` style="background-color:#${fill}"` : ''}>${contenido}</td>`;
    }).join('') + '</tr>').join('') + '</table>';
    let html = '', lista = [];
    const cerrar = () => { if (lista.length) { html += '<ul>' + lista.map(l => `<li>${l}</li>`).join('') + '</ul>'; lista = []; } };
    [...cuerpo.children].forEach(n => {
      if (n.localName === 'p') { const r = parrafo(n); if (r.li != null) lista.push(r.li); else { cerrar(); html += r.tag; } }
      else if (n.localName === 'tbl') { cerrar(); html += tabla(n); }
    });
    cerrar();
    return limpiar(html);
  }

  // recorta los márgenes en blanco para que en el celu se lea más grande
  function recortarBlanco(c) {
    const g = c.getContext('2d'); const { width: w, height: hh } = c; const px = g.getImageData(0, 0, w, hh).data;
    let x0 = w, y0 = hh, x1 = -1, y1 = -1;
    for (let y = 0; y < hh; y += 2) for (let x = 0; x < w; x += 2) {
      const i = (y * w + x) * 4; if (px[i] < 235 || px[i + 1] < 235 || px[i + 2] < 235) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (x1 < 0) return null; // página en blanco
    const m = 24; x0 = Math.max(0, x0 - m); y0 = Math.max(0, y0 - m); x1 = Math.min(w, x1 + m); y1 = Math.min(hh, y1 + m);
    const r = document.createElement('canvas'); r.width = x1 - x0; r.height = y1 - y0;
    const rg = r.getContext('2d'); rg.fillStyle = '#fff'; rg.fillRect(0, 0, r.width, r.height); rg.drawImage(c, x0, y0, r.width, r.height, 0, 0, r.width, r.height);
    return r;
  }

  // ---------- PDF → imágenes (máx. 10 páginas) ----------
  async function pdfACanvases(archivo) {
    const pdfjs = await import(new URL('vendor/pdf.min.mjs', document.baseURI).href);
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('vendor/pdf.worker.min.mjs', document.baseURI).href;
    const doc = await pdfjs.getDocument({ data: await archivo.arrayBuffer(), isEvalSupported: false }).promise;
    const salida = [], textos = [];
    for (let i = 1; i <= Math.min(doc.numPages, 10); i++) {
      const pag = await doc.getPage(i);
      const vp0 = pag.getViewport({ scale: 1 }); const vp = pag.getViewport({ scale: Math.min(2, 1200 / vp0.width) });
      const c = document.createElement('canvas'); c.width = Math.round(vp.width); c.height = Math.round(vp.height);
      const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
      await pag.render({ canvasContext: g, viewport: vp, canvas: c }).promise;
      const rc = recortarBlanco(c); if (rc) salida.push(rc);
      const tc = await pag.getTextContent();
      textos.push(tc.items.map(it => it.str + (it.hasEOL ? '\n' : ' ')).join('').replace(/[ \t]+/g, ' ').trim());
    }
    return { canvases: salida, total: doc.numPages, texto: textos.join('\n\n').slice(0, 60000) };
  }

  return { configurar, limpiar, desdePegado, canvasDeArchivo, aJpg, xlsxAHtml, docxAHtml, pdfACanvases, esc };
})();
