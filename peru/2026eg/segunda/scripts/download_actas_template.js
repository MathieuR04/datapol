// =============================================================================
// Pegar en la consola del navegador en:
// https://resultadosegundavuelta.onpe.gob.pe/main/actas
// Generado por: bash scripts/generate_download_actas.sh | pbcopy
// =============================================================================

const MESA_IDS    = __MESA_IDS__;
const BASE        = 'https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend';
const DELAY_MS    = 300;
const ID_ELECCION = 10;

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function getActaId(codigoMesa) {
  const r = await fetch(`${BASE}/actas/buscar/mesa?codigoMesa=${codigoMesa}`);
  const d = await r.json();
  if (!d.success || !d.data?.length) return null;
  const acta = d.data.find(a => a.idEleccion === ID_ELECCION);
  return acta ? acta.id : null;
}

async function getEscrutinioFileId(actaId) {
  const r = await fetch(`${BASE}/actas/${actaId}`);
  const d = await r.json();
  if (!d.success || !d.data?.archivos) return null;
  const archivo = d.data.archivos.find(a => a.tipo === 1);
  return archivo ? archivo.id : null;
}

async function getPresignedUrl(fileId) {
  const r = await fetch(`${BASE}/actas/file?id=${fileId}`);
  const d = await r.json();
  return d.success ? d.data : null;
}

async function downloadPdf(url, filename) {
  const blob = await fetch(url).then(r => r.blob());
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl; a.download = filename; a.style.display = 'none';
  document.body.appendChild(a); a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(blobUrl); }, 100);
}

async function downloadAll() {
  const results = { ok: 0, noActa: 0, noFile: 0, noUrl: 0, error: 0 };
  const failed  = [];
  console.log(`Iniciando descarga de ${MESA_IDS.length} actas (~${Math.round(MESA_IDS.length * DELAY_MS / 60000)} min)...`);

  for (let i = 0; i < MESA_IDS.length; i++) {
    const mesaId = MESA_IDS[i];
    try {
      const actaId = await getActaId(mesaId);
      if (!actaId) { results.noActa++; failed.push({mesaId, reason:'noActa'}); continue; }

      const fileId = await getEscrutinioFileId(actaId);
      if (!fileId) { results.noFile++; failed.push({mesaId, reason:'noFile'}); continue; }

      const url = await getPresignedUrl(fileId);
      if (!url) { results.noUrl++; failed.push({mesaId, reason:'noUrl'}); continue; }

      await downloadPdf(url, `${mesaId}.pdf`);
      results.ok++;
      if (i % 10 === 0) console.log(`[${i+1}/${MESA_IDS.length}] ✓ ${mesaId}`);
    } catch(e) {
      results.error++;
      failed.push({mesaId, reason: e.message});
    }
    await sleep(DELAY_MS);
  }

  console.log('\n=== RESUMEN ===');
  console.log(`✓ Descargados: ${results.ok}`);
  console.log(`✗ Sin acta:    ${results.noActa}`);
  console.log(`✗ Sin archivo: ${results.noFile}`);
  console.log(`✗ Sin URL:     ${results.noUrl}`);
  console.log(`✗ Errores:     ${results.error}`);
  if (failed.length) console.log('\nFallidos:', JSON.stringify(failed.map(f => f.mesaId)));
}

downloadAll();
