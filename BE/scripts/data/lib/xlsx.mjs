// xlsx 시트 XML 을 문자열 행 배열로 바꾼다. 공공데이터 파일의 값(문자·숫자·공유 문자열)만 다루며
// 서식·수식·날짜 변환은 하지 않는다 — 원천 값을 그대로 옮기는 것이 목적이다 (Excel 일련 날짜도 그대로 남는다).
import { readZip } from './zip.mjs';

const ENTITIES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'" };

function decode(text) {
  return text.replace(/&(amp|lt|gt|quot|apos);/g, (m) => ENTITIES[m]).replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)));
}

// "A" → 0, "Z" → 25, "AA" → 26
function colIndex(ref) {
  let n = 0;
  for (const ch of ref) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
}

function innerText(xml) {
  return [...xml.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)].map((m) => m[1]).join('');
}

/** sharedStrings.xml → 인덱스별 문자열. 서식 런(<r>)은 이어 붙인다. */
export function parseSharedStrings(xml) {
  if (!xml) return [];
  return [...xml.matchAll(/<si\b[^>]*>([\s\S]*?)<\/si>/g)].map((m) => decode(innerText(m[1])));
}

/**
 * 시트 XML → 행 배열. 각 행은 열 위치를 유지하며(중간 빈 셀은 ''), 마지막 값이 있는 열까지만 담는다.
 * 값이 하나도 없는 행(<row/> 또는 빈 셀만)은 빈 배열로 남겨 호출자가 걸러낸다.
 */
export function sheetRows(sheetXml, sharedStringsXml = '') {
  const shared = parseSharedStrings(sharedStringsXml);
  const rows = [];
  for (const row of sheetXml.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)) {
    const cells = [];
    let max = -1;
    for (const c of row[1].matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
      const attrs = c[1];
      const inner = c[2] ?? '';
      const ref = /\br="([A-Z]+)\d+"/.exec(attrs)?.[1];
      if (!ref) continue;
      const type = /\bt="(\w+)"/.exec(attrs)?.[1];
      const idx = colIndex(ref);
      let value;
      if (type === 's') {
        const n = /<v>([\s\S]*?)<\/v>/.exec(inner)?.[1];
        value = n === undefined ? '' : shared[Number(n)] ?? '';
      } else if (type === 'inlineStr') {
        value = decode(innerText(inner));
      } else {
        value = decode(/<v>([\s\S]*?)<\/v>/.exec(inner)?.[1] ?? '');
      }
      cells[idx] = value;
      if (value !== '') max = Math.max(max, idx);
    }
    const out = [];
    for (let i = 0; i <= max; i += 1) out.push(cells[i] ?? '');
    rows.push(out);
  }
  return rows;
}

/**
 * 여러 줄 머리글을 한 줄로 합친다. 열마다 비어 있지 않은 조각을 위에서부터 이어 붙이고 공백·줄바꿈을 없앤다.
 * 병합 셀의 값은 첫 열에만 있으므로 "소재지(위치)자치구" 처럼 붙는다 — 그대로 두고 CLI 의 --header 로 이름을 덮어쓴다.
 */
export function mergeHeaderRows(rows) {
  const width = Math.max(0, ...rows.map((r) => r.length));
  const out = [];
  for (let col = 0; col < width; col += 1) {
    out.push(rows.map((r) => (r[col] ?? '').replace(/\s+/g, '')).filter((s) => s !== '').join(''));
  }
  return out;
}

/** xlsx 파일 버퍼 → 지정 시트의 행 배열. */
export function workbookRows(xlsxBuffer, sheet = 'sheet1') {
  const entries = readZip(xlsxBuffer);
  const sheetXml = entries.get(`xl/worksheets/${sheet}.xml`);
  if (!sheetXml) {
    const sheets = [...entries.keys()].filter((k) => k.startsWith('xl/worksheets/')).join(', ');
    throw new Error(`시트 '${sheet}' 가 없다. 있는 시트: ${sheets || '(없음)'}`);
  }
  const shared = entries.get('xl/sharedStrings.xml');
  return sheetRows(sheetXml.toString('utf8'), shared ? shared.toString('utf8') : '');
}
