// CSV 쓰기 (RFC 4180). 로더의 CsvTable(BE/src/main/java/.../load/csv/CsvTable.java)이 같은 규칙으로 읽는다.
// 줄바꿈은 LF — 저장소 .gitattributes 와 같다.

export function csvEscape(value) {
  if (value === null || value === undefined) return '';
  const s = String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/**
 * CSV 텍스트 → 헤더를 키로 하는 행 객체 배열. toCsv 와 같은 규칙(RFC 4180 따옴표, CRLF, BOM, 빈 줄 무시). 짧은 행은 '' 로 채운다.
 */
export function parseCsv(text) {
  const src = text.startsWith('﻿') ? text.slice(1) : text;
  const records = [];
  let row = [];
  let cell = '';
  let quoted = false;
  let started = false;
  for (let i = 0; i < src.length; i += 1) {
    const c = src[i];
    if (quoted) {
      if (c === '"') {
        if (src[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += c;
      }
      continue;
    }
    if (c === '"') {
      quoted = true;
      started = true;
    } else if (c === ',') {
      row.push(cell);
      cell = '';
      started = true;
    } else if (c === '\r') {
      // CRLF 의 CR 은 무시
    } else if (c === '\n') {
      if (started || cell !== '') {
        row.push(cell);
        records.push(row);
      }
      row = [];
      cell = '';
      started = false;
    } else {
      cell += c;
      started = true;
    }
  }
  if (started || cell !== '') {
    row.push(cell);
    records.push(row);
  }
  if (records.length === 0) return [];
  const header = records[0].map((h) => h.trim());
  return records.slice(1).map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}

/**
 * 헤더 한 줄 + 데이터 행. 헤더보다 짧은 행은 빈 칸으로 채우고, 긴 행은 열이 어긋난 파일이므로 오류로 멈춘다.
 */
export function toCsv(header, rows) {
  const width = header.length;
  const lines = [header.map(csvEscape).join(',')];
  rows.forEach((row, i) => {
    if (row.length > width) {
      throw new Error(`열 수 불일치: ${i + 1}번째 행이 ${row.length}열, 헤더는 ${width}열`);
    }
    const cells = [...row];
    while (cells.length < width) cells.push('');
    lines.push(cells.map(csvEscape).join(','));
  });
  return `${lines.join('\n')}\n`;
}
