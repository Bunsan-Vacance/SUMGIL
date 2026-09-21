package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.buscongestion.BusCongestionGrade;
import java.util.Optional;

/**
 * 버스 실시간 혼잡 등급 → 공통 수치 축 정규화(5부 C1, 티켓 `route-heuristic-cost-layer`).
 *
 * <p>지하철 혼잡은 정원 대비 %(수치, 100=정원)이고 버스 실시간(297)은 등급 코드다.
 * 비용·랭킹에서 두 모드를 비교하려면 한 축이어야 하므로 등급을 지하철 축과 같은
 * 수치로 옮긴다 — 앵커: <b>100 = 보통</b>(지하철 100과 같은 "가중 없음" 경계).
 *
 * <p>값은 명시적 가정(초안)이며 골든 OD로 보정한다. 데이터 없음(코드 0·미지 코드)은
 * 중립(null) — 호출부는 가중하지 않는다(값을 지어내지 않음).
 */
public final class BusCrowdingScale {

    /** 여유(코드 3). 가중 없음 구간(≤100). */
    public static final double RELAXED_LEVEL = 70.0;

    /** 보통(코드 4). 앵커 — 지하철 100과 같이 가중 경계. */
    public static final double NORMAL_LEVEL = 100.0;

    /** 혼잡(코드 5). */
    public static final double CONGESTED_LEVEL = 130.0;

    /** 혼잡 심화(코드 6). */
    public static final double SATURATED_LEVEL = 170.0;

    private BusCrowdingScale() {
    }

    /** 등급 → 공통 수치. null이면 중립(빈 값). */
    public static Optional<Double> levelOf(BusCongestionGrade grade) {
        if (grade == null) {
            return Optional.empty();
        }
        return Optional.of(switch (grade) {
            case RELAXED -> RELAXED_LEVEL;
            case NORMAL -> NORMAL_LEVEL;
            case CONGESTED -> CONGESTED_LEVEL;
            case SATURATED -> SATURATED_LEVEL;
        });
    }

    /**
     * 문자열 등급(FE 계약값·{@code RouteLegResponse.congestionGrade}) → 공통 수치.
     * null·공백·미지 값은 중립(빈 값).
     */
    public static Optional<Double> levelOfName(String gradeName) {
        if (gradeName == null || gradeName.isBlank()) {
            return Optional.empty();
        }
        try {
            return levelOf(BusCongestionGrade.valueOf(gradeName));
        } catch (IllegalArgumentException e) {
            return Optional.empty();
        }
    }
}
