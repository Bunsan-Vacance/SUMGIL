// AI 혼잡도 예측 산출물의 이름 규칙과 최신 선택. 순수 함수만 둔다(테스트 대상).
//
// 배치는 파일 이름에 대상 날짜와 생성시각을 넣어 만든다: predictions_<YYYY-MM-DD>_<HHMMSS>.csv
// 따라서 사전순 정렬이 곧 (날짜, 생성시각) 순이고, 이 규칙은 두 곳이 같아야 한다 —
//   ① 이 스크립트(내려받을 파일 고르기)
//   ② 자바 로더 CsvCongestionPredSource(폴더에서 읽을 파일 고르기)
//
// 같은 날짜를 다시 만들면 _HHMMSS 가 달라 CSV 가 쌓인다(AI 가 오래된 것을 지우지 않기로 했다).
// 그래서 "최신" 은 덮어쓰기가 아니라 정렬로 고른다.
//
// 재고 예측(bikepred)과 패턴이 다르다: 저쪽은 predictions 가 아니라 bike_stock_pred_ 접두어이고
// 날짜에 하이픈이 없다(20260917-014432). 규칙을 공유하지 않고 각자 둔다 — 원천이 다른 배치다.

/** predictions_2026-09-20_234300.csv 형태만 고른다. predictions_train_… 같은 다른 산출물은 걸러진다. */
export const ARTIFACT_PATTERN = /^predictions_\d{4}-\d{2}-\d{2}_\d{6}\.csv$/;

/** 파일명 목록에서 가장 늦은 산출물. 없으면 null — 경로를 아는 부르는 쪽이 오류 메시지를 만든다. */
export function latestArtifact(names) {
  const artifacts = names.filter((name) => ARTIFACT_PATTERN.test(name)).sort();
  return artifacts.length === 0 ? null : artifacts[artifacts.length - 1];
}

/**
 * 같은 회차의 사이드카 이름. 로더가 generated_at 과 행 수를 여기서 읽으므로 CSV 와 함께 받아야 한다 —
 * 없으면 적재가 아예 멈춘다(재고 예측은 경고만 냈지만 여기서는 NOT NULL 열이 걸려 있다).
 */
export function siblingMeta(csvName) {
  return csvName.replace(/\.csv$/, '.meta.json');
}
