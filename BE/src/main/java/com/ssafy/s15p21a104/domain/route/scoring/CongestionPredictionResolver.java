package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.route.dto.response.CongestionDataStatus;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionGrade;
import com.ssafy.s15p21a104.domain.route.dto.response.CongestionPrediction;
import com.ssafy.s15p21a104.domain.route.dto.response.PredictionBasis;
import com.ssafy.s15p21a104.domain.route.dto.response.WorstSegmentResponse;
import java.time.LocalDate;
import java.util.Objects;
import java.util.Optional;

/**
 * 혼잡 예측 응답 판정(S15P21A104-236, FE-BE 통합 계약 §2).
 *
 * <p>순위: 날짜 범위 밖 → NO_CALIBRATION / 최악 구간 있음 → AVAILABLE /
 * 방향 미판정 → LINE1_TRUNCATED / 그 외 → NO_LOOKUP. 비AVAILABLE은 수치·등급·근거·위치가
 * 전부 null이다.
 *
 * <p>2026-09-22 기준 변경: 값과 근거·위치는 호출부({@link WorstCongestionPicker})가 정해
 * 넘긴다. 이 클래스는 응답 계약(등급·상태)만 판정한다.
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다.
 */
public final class CongestionPredictionResolver {

    private CongestionPredictionResolver() {
    }

    /**
     * @param percent 가장 혼잡한 구간의 혼잡도(%)
     * @param basis 예측 근거(RECENT_7D·WEEKDAY_AVERAGE·LIVE)
     * @param segment 가장 혼잡한 구간 위치
     */
    public record Worst(double percent, PredictionBasis basis, WorstSegmentResponse segment) {
    }

    /**
     * @param worst 가장 혼잡한 구간(없으면 빈 값)
     * @param directionUnresolved 방향을 못 정한 SUBWAY 엣지 존재 여부
     * @param departureDate 출발일(서울 기준)
     * @param today 오늘(서울 기준)
     * @return 예측 응답. dataStatus는 null 불가
     */
    public static CongestionPrediction resolve(
            Optional<Worst> worst,
            boolean directionUnresolved,
            LocalDate departureDate,
            LocalDate today) {
        Objects.requireNonNull(worst, "worst");
        Objects.requireNonNull(departureDate, "departureDate");
        Objects.requireNonNull(today, "today");
        if (departureDate.isBefore(today) || departureDate.isAfter(today.plusDays(3))) {
            return unavailable(CongestionDataStatus.NO_CALIBRATION);
        }
        if (worst.isPresent()) {
            Worst value = worst.get();
            return available(value.percent(), value.basis(), value.segment());
        }
        if (directionUnresolved) {
            return unavailable(CongestionDataStatus.LINE1_TRUNCATED);
        }
        return unavailable(CongestionDataStatus.NO_LOOKUP);
    }

    private static CongestionPrediction available(double percent, PredictionBasis basis, WorstSegmentResponse segment) {
        CongestionGrade grade = percent < 50 ? CongestionGrade.LOW
                : percent < 100 ? CongestionGrade.MEDIUM : CongestionGrade.HIGH;
        return new CongestionPrediction(percent, grade, CongestionDataStatus.AVAILABLE, basis, segment);
    }

    private static CongestionPrediction unavailable(CongestionDataStatus status) {
        return new CongestionPrediction(null, null, status, null, null);
    }
}
