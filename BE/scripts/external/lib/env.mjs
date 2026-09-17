// BE/.env 를 의존성 없이 읽는다. KEY=VALUE 한 줄 형식, # 주석, 양쪽 따옴표만 지원한다.
import { readFileSync } from 'node:fs';

export function parseDotenv(text) {
  const out = {};
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === '' || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    const quoted =
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")));
    if (quoted) value = value.slice(1, -1);
    if (key) out[key] = value;
  }
  return out;
}

// 파일이 없으면 빈 객체. 그 외 오류는 그대로 던진다.
export function loadDotenv(path) {
  try {
    return parseDotenv(readFileSync(path, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return {};
    throw err;
  }
}
