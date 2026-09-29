// AI 재고 예측 산출물의 이름 규칙과 최신 선택. 순수 함수만 둔다(테스트 대상).
//
// 배치는 파일 이름에 생성시각을 넣어 만든다: bike_stock_pred_<YYYYMMDD>-<HHMMSS>.csv
// 따라서 사전순 정렬이 곧 시간순이고, 이 규칙은 세 곳이 같아야 한다 —
//   ① 이 스크립트(내려받을 파일 고르기)
//   ② 자바 로더 CsvBikeStockPredSource(폴더에서 읽을 파일 고르기)
//   ③ AI 서빙 API 의 BikeStockStore(service.py 의 sorted(glob))
// 다르게 고르면 BE 가 적재한 표와 AI API 응답이 서로 다른 배치 결과가 된다.

/** bike_stock_pred_20260917-014432.csv 형태만 고른다. 같은 폴더에 parquet·meta.json 이 함께 있다. */
export const ARTIFACT_PATTERN = /^bike_stock_pred_\d{8}-\d{6}\.csv$/;

/** 파일명 목록에서 가장 늦은 산출물. 없으면 null — 경로를 아는 부르는 쪽이 오류 메시지를 만든다. */
export function latestArtifact(names) {
  const artifacts = names.filter((name) => ARTIFACT_PATTERN.test(name)).sort();
  return artifacts.length === 0 ? null : artifacts[artifacts.length - 1];
}

/** 같은 회차의 meta.json 이름. 행 수 대조에 쓴다. */
export function siblingMeta(csvName) {
  return csvName.replace(/\.csv$/, '.meta.json');
}
