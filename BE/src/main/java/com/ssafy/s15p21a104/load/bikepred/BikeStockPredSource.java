package com.ssafy.s15p21a104.load.bikepred;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;

/**
 * 재고 예측 표의 원천. 구현을 바꿔 원천을 교체한다 ({@code load.bikepred.source}).
 * <p>
 * <b>지금 구현은 파일 하나뿐이다.</b> AI 서빙 API 는 원천이 아니라 <b>같은 산출물의 조회 창구</b>다 —
 * {@code GET /bike/stations/{rental_id}/stock} 은 대여소 하나씩만 응답하고, 그 뒤에서 읽는 파일이
 * 바로 이 로더가 읽는 {@code bike_stock_pred_<시각>.csv} 의 parquet 짝이다
 * ({@code AI/app/BIKE/service.py} 의 {@code BikeStockStore}). 40만 행을 적재하려고 그 API 를 대여소 수만큼
 * 부르는 것은 같은 파일을 한 번에 읽는 것보다 나을 이유가 없다. AI 가 표 전체를 주는 엔드포인트를 내놓으면
 * 그때 구현을 하나 더 만든다.
 */
public interface BikeStockPredSource {

    /**
     * 읽은 결과.
     *
     * @param rows     적재 후보 행
     * @param stats    파싱 통계 (건너뛴 행·라벨별 건수 포함)
     * @param origin   실제로 읽은 원천. 폴더를 줬을 때 어느 파일이 뽑혔는지 로그·문서에 남긴다
     * @param warnings 원천 단계 경고 (파싱 경고 + meta 대조 경고)
     */
    record Loaded(List<BikeStockPredRow> rows, BikeStockPredParser.Stats stats, Path origin, List<String> warnings) {
    }

    Loaded read() throws IOException;
}
