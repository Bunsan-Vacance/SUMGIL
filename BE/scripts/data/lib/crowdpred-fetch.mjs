// AI 혼잡도 예측 산출물의 이름 규칙과 내려받을 것 고르기. 순수 함수만 둔다(테스트 대상).
//
// 배치는 파일 이름에 대상 날짜와 생성 시각을 넣어 만든다: predictions_<YYYY-MM-DD>_<HHMMSS>.csv
// 시각은 서버 시간대(UTC)이고 생성 "날짜" 는 없다. 배치가 매일 오늘·내일 2일치를 만들어 같은 대상
// 날짜가 이틀에 걸쳐 두 번 생기는데(전날 "내일치" · 당일 "오늘치", 둘 다 00:30 UTC + 랜덤 지연),
// 이름만으로는 어느 쪽이 나중인지 가를 수 없다.
//
// 그래서 이 스크립트는 "최신" 을 고르지 않는다. 대상 날짜가 기준일 이후인 산출물을 전부 받아 폴더를
// 동기화하고, 같은 날짜의 최신 회차 판정은 자바 로더(CsvCongestionPredSource) 가 사이드카
// generated_at 으로 한다. 규칙을 한 곳에만 두기 위해서다(304).
//
// 재고 예측(bikepred)과 패턴이 다르다: 저쪽은 predictions 가 아니라 bike_stock_pred_ 접두어이고
// 날짜에 하이픈이 없다(20260917-014432). 규칙을 공유하지 않고 각자 둔다 — 원천이 다른 배치다.

/** predictions_2026-09-20_234300.csv 형태만 고른다. predictions_train_… 같은 다른 산출물은 걸러진다. */
export const ARTIFACT_PATTERN = /^predictions_\d{4}-\d{2}-\d{2}_\d{6}\.csv$/;

const PREFIX = 'predictions_';
const DATE_LENGTH = 'YYYY-MM-DD'.length;

/** predictions_2026-09-21_063113.csv → 2026-09-21. 사이드카 target_date 와 같은 값이다. */
export function targetDateOf(name) {
  return name.slice(PREFIX.length, PREFIX.length + DATE_LENGTH);
}

/**
 * 대상 날짜가 since(YYYY-MM-DD) 와 같거나 뒤인 산출물 전부, 이름 순. since 가 없으면 전부.
 * 같은 날짜의 여러 회차도 모두 돌려준다 — 고르는 일은 자바 로더의 몫이다.
 * ISO 날짜 문자열은 사전순이 곧 날짜순이라 문자열 비교로 충분하다.
 */
export function artifactsSince(names, since) {
  return names
    .filter((name) => ARTIFACT_PATTERN.test(name))
    .filter((name) => since === undefined || targetDateOf(name) >= since)
    .sort();
}

/**
 * 같은 회차의 사이드카 이름. 로더가 generated_at 과 행 수를 여기서 읽으므로 CSV 와 함께 받아야 한다 —
 * 없으면 적재가 아예 멈춘다(재고 예측은 경고만 냈지만 여기서는 NOT NULL 열이 걸려 있다).
 */
export function siblingMeta(csvName) {
  return csvName.replace(/\.csv$/, '.meta.json');
}
