package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.route.dto.response.CongestionDataStatus;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionGrade;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionPrediction;
import com.ssafy.s15p21a104.domain.route.dto.response.PredictionBasis;
import java.time.LocalDate;
import java.util.Objects;
import java.util.Optional;

/**
 * 혼잡 예측 응답 판정(S15P21A104-236, FE-BE 통합 계약 §2).
 *
 * <p>순위: 날짜 범위 밖 → NO_CALIBRATION / 링크 점수 → AVAILABLE+RECENT_7D /
 * 노선 점수 → AVAILABLE+WEEKDAY_AVERAGE / 방향 미판정 → LINE1_TRUNCATED /
 * 그 외 → NO_LOOKUP. 비AVAILABLE은 수치·등급·근거 전부 null이다.
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다.
 */
public final class CongestionPredictionResolver {

    private CongestionPredictionResolver() {
    }

    /**
     * @param linkPercent 링크 단위 가중 평균 혼잡도(%). congestion_pred 기반
     * @param linePercent 노선 단위 혼잡도(%). congestion stat 기반
     * @param directionUnresolved 방향을 못 정한 SUBWAY 엣지 존재 여부
     * @param departureDate 출발일(서울 기준)
     * @param today 오늘(서울 기준)
     * @return 예측 응답. dataStatus는 null 불가
     */
    public static CongestionPrediction resolve(
            Optional<Double> linkPercent,
            Optional<Double> linePercent,
            boolean directionUnresolved,
            LocalDate departureDate,
            LocalDate today) {
        Objects.requireNonNull(linkPercent, "linkPercent");
        Objects.requireNonNull(linePercent, "linePercent");
        Objects.requireNonNull(departureDate, "departureDate");
        Objects.requireNonNull(today, "today");
        if (departureDate.isBefore(today) || departureDate.isAfter(today.plusDays(3))) {
            return new CongestionPrediction(
                    null, null, CongestionDataStatus.NO_CALIBRATION, null);
        }
        if (linkPercent.isPresent()) {
            return available(linkPercent.get(), PredictionBasis.RECENT_7D);
        }
        if (linePercent.isPresent()) {
            return available(linePercent.get(), PredictionBasis.WEEKDAY_AVERAGE);
        }
        if (directionUnresolved) {
            return new CongestionPrediction(
                    null, null, CongestionDataStatus.LINE1_TRUNCATED, null);
        }
        return new CongestionPrediction(
                null, null, CongestionDataStatus.NO_LOOKUP, null);
    }

    private static CongestionPrediction available(double percent, PredictionBasis basis) {
        CongestionGrade grade = percent < 50 ? CongestionGrade.LOW
                : percent < 100 ? CongestionGrade.MEDIUM : CongestionGrade.HIGH;
        return new CongestionPrediction(percent, grade, CongestionDataStatus.AVAILABLE, basis);
    }
}
