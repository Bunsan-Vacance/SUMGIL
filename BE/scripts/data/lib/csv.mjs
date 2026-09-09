// CSV 쓰기 (RFC 4180). 로더의 CsvTable(BE/src/main/java/.../load/csv/CsvTable.java)이 같은 규칙으로 읽는다.
// 줄바꿈은 LF — 저장소 .gitattributes 와 같다.

export function csvEscape(value) {
  if (value === null || value === undefined) return '';
  const s = String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
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
