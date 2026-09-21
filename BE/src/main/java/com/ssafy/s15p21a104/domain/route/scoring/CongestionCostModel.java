package com.ssafy.s15p21a104.domain.route.scoring;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.KShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.Objects;
import java.util.Set;

/**
 * 혼잡 가중 엣지 비용 모델(S15P21A104-216).
 *
 * <p>비용 = {@code travelSec × (1 + λ × max(0, level − 100) / 100)}.
 * 혼잡도는 정원 대비 %라 100 이하는 체감 가중이 없고, 모르는 값은
 * 가중 없이 시간 비용을 쓴다(값을 지어내지 않음). 환승 상수·대기는
 * 탐색기가 별도로 더하므로 여기서 다루지 않는다.
 *
 * <p>순수 함수이며 DB·Spring에 의존하지 않는다. 요일·슬롯은 호출부가
 * {@link LevelSource}에 묶어서 넘긴다.
 */
public final class CongestionCostModel {

    /** 혼잡도 조회: (targetType, targetId). 모르면 null. */
    public interface LevelSource {
        Double levelOf(String targetType, String targetId);
    }

    private CongestionCostModel() {
    }

    /**
     * @param lambda 혼잡 가중치 λ (기본 0.5, 설정값). 0이면 시간 비용과 같다
     * @param levels 혼잡도 조회 함수
     * @param busRouteIndex 정규 BUS 구간 운행 노선 인덱스(234). null이면 routeId 폴백
     * @return 엣지 → 가중 이동 비용(초)
     */
    public static KShortestPathFinder.EdgeCostModel of(double lambda, LevelSource levels,
                                                        BusRouteIndex busRouteIndex) {
        Objects.requireNonNull(levels, "levels");
        return edge -> {
            Objects.requireNonNull(edge, "edge");
            if (edge.mode() != TravelMode.SUBWAY && edge.mode() != TravelMode.BUS) {
                return edge.travelSec();
            }
            Double level = levelOf(edge, levels, busRouteIndex);
            if (level == null) {
                return edge.travelSec();
            }
            return Math.round(edge.travelSec()
                    * (1 + lambda * Math.max(0, level - 100) / 100));
        };
    }

    private static Double levelOf(Edge edge, LevelSource levels, BusRouteIndex busRouteIndex) {
        if (edge.mode() == TravelMode.SUBWAY) {
            return levels.levelOf("LINE", edge.routeId());
        }
        Set<String> options = BusRouteIndex.optionsFor(edge, busRouteIndex);
        Double best = null;
        for (String routeId : options) {
            Double level = levels.levelOf("ROUTE", routeId);
            if (level != null && (best == null || level < best)) {
                // corridor는 여러 노선이 겹친다 — 탑승 시 가장 덜 붐비는
                // 노선을 탄다고 보고 최소값을 쓴다.
                best = level;
            }
        }
        return best;
    }
}
