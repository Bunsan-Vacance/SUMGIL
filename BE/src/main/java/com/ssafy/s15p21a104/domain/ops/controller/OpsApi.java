package com.ssafy.s15p21a104.domain.ops.controller;

import com.ssafy.s15p21a104.domain.ops.dto.response.BikeStockOverviewResponse;
import com.ssafy.s15p21a104.domain.ops.dto.response.CongestionHeatmapResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

@Tag(name = "운영자 뷰")
@RequestMapping("/api/ops")
public interface OpsApi {

    @Operation(summary = "대여소 재고·예측 일괄 조회(운영자 뷰)", description = "지도 bbox 안 따릉이 대여소의 실시간 재고와 "
            + "도착 시각 예측을 한 번에 반환한다. 읽기 전용이며 최종 사용자 화면용이 아니다. "
            + "재고는 단건 API와 같은 Redis 캐시를 읽고 stockStatus(AVAILABLE·STALE·UNAVAILABLE)로 신뢰도를 구분한다. "
            + "일괄 예측은 AI 모델을 부르지 않고 bike_stock_pred 표만 읽으므로 predictionSource는 항상 TABLE이다(단건 예측과 다름). "
            + "행이 없으면 predictionStatus=UNAVAILABLE이고 predictedBikes·availabilityProbability·predictedAt은 null이다 — "
            + "null을 0으로 해석하면 안 된다. 개수는 limit(기본 200, 최대 500)까지이며 넘으면 bbox 중심에서 가까운 순으로 "
            + "자르고 truncated=true다. bbox가 비정상(sw>=ne, 좌표 범위 밖)·limit 범위 밖·arrivalTime 형식 오류는 400이다.")
    @GetMapping("/bike-stations/stock-overview")
    ApiResult<BikeStockOverviewResponse> bikeStockOverview(
            @RequestParam Double swLat,
            @RequestParam Double swLng,
            @RequestParam Double neLat,
            @RequestParam Double neLng,
            @RequestParam(required = false) String arrivalTime,
            @RequestParam(required = false) Integer limit);

    @Operation(summary = "혼잡도 예측 히트맵 조회(운영자 뷰)", description = "congestion_pred(링크×방향×슬롯 예측)를 "
            + "호선×슬롯 셀로 집계해 반환한다. 읽기 전용이며 최종 사용자 화면용이 아니다. "
            + "집계 규칙: data_status가 ok·calibration_fallback인 행만 쓰고(segment_truncated 등은 제외, fallback은 포함해 "
            + "nFallback으로 수를 알린다) level은 평균이 아닌 중앙값이며 방향은 합친다. "
            + "슬롯 축은 10~47(05:00~24:00, 30분 단위 38칸) 고정이고 행이 없는 슬롯은 level·maxLevel이 null, nLinks·nFallback이 0이다. "
            + "date를 생략하면 Asia/Seoul 오늘이다. 데이터가 없는 날짜는 200에 lines: []이다(값을 지어내지 않음). "
            + "date 형식(YYYY-MM-DD) 오류는 400이다. 기존 GET /api/congestion(정적 표)과 다른 표이며 source로 구분한다.")
    @GetMapping("/congestion/heatmap")
    ApiResult<CongestionHeatmapResponse> congestionHeatmap(@RequestParam(required = false) String date);
}
