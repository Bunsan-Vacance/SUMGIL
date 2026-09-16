// 응답 요약(필드 목록·시각 필드 후보·샘플 축약)과 응답 시간 통계.
import { spec } from './sources.mjs';

export function fieldNames(rows) {
  const names = new Set();
  for (const row of rows) {
    if (row && typeof row === 'object') {
      for (const key of Object.keys(row)) names.add(key);
    }
  }
  return [...names].sort();
}

// 생성·수신 시각으로 보이는 필드: Dt / Tm / time / date 로 끝나거나 _at 으로 끝나는 키.
// 예) recptnDt(지하철 도착정보 생성시각), mkTm(버스 제공시각), collected_at(수집기 수신시각)
const TIME_FIELD = /(dt|tm|time|date|_at)$/i;

export function timeFieldCandidates(rows) {
  const out = [];
  for (const field of fieldNames(rows)) {
    if (!TIME_FIELD.test(field)) continue;
    const withValue = rows.find((row) => row && row[field] != null && row[field] !== '');
    out.push({ field, sample: withValue ? withValue[field] : null });
  }
  return out;
}

// 저장소에 커밋할 샘플: 메타데이터는 그대로 두고 행만 앞에서 keep 개 남긴다. 입력은 바꾸지 않는다.
export function trimSample(source, body, keep = 20) {
  const { rowsPath } = spec(source);
  const clone = structuredClone(body);
  const parent = rowsPath.slice(0, -1).reduce((cur, key) => (cur == null ? undefined : cur[key]), clone);
  const last = rowsPath[rowsPath.length - 1];
  const rows = parent && Array.isArray(parent[last]) ? parent[last] : [];
  if (rows.length > 0) parent[last] = rows.slice(0, keep);
  clone._probe = {
    source,
    originalRowCount: rows.length,
    keptRowCount: Math.min(rows.length, keep),
    savedAt: new Date().toISOString(),
  };
  return clone;
}

// 최근접 순위(nearest-rank) 백분위. 표본이 적을 때 보간보다 보수적이다.
export function stats(values) {
  const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  const n = sorted.length;
  if (n === 0) return { n: 0, min: null, max: null, median: null, p95: null };
  const median = n % 2 === 1 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  const p95 = sorted[Math.max(0, Math.ceil(0.95 * n) - 1)];
  return { n, min: sorted[0], max: sorted[n - 1], median, p95 };
}
