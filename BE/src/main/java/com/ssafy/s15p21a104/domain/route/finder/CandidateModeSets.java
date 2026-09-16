package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 허용 수단 조합별 대체 후보 탐색에 쓰는 "핵심 수단" 조합 목록(S15P21A104-185).
 *
 * <p>{@link RouteGraphRegistry}(그래프 로드 시점에 조합별 하위 그래프를 미리 계산·캐싱,
 * S15P21A104-155)와 {@code RouteSearchService}(그 캐시를 읽어 탐색) 양쪽이 같은 목록을
 * 봐야 하므로 한곳에 둔다 — 따로 들고 있으면 둘이 어긋날 수 있다.
 *
 * <p>WALK는 접근·연결용이라 모든 조합에 항상 포함한다({@link #withWalk}).
 */
public final class CandidateModeSets {

    public static final List<Set<TravelMode>> CORE_MODE_SETS = List.of(
            Set.of(TravelMode.SUBWAY, TravelMode.BUS, TravelMode.BIKE),
            Set.of(TravelMode.SUBWAY),
            Set.of(TravelMode.BUS),
            Set.of(TravelMode.BIKE),
            Set.of(TravelMode.SUBWAY, TravelMode.BUS),
            Set.of(TravelMode.SUBWAY, TravelMode.BIKE),
            Set.of(TravelMode.BUS, TravelMode.BIKE)
    );

    private CandidateModeSets() {
    }

    /** WALK는 접근·연결용이라 모든 수단 조합에 항상 포함한다. */
    public static Set<TravelMode> withWalk(Set<TravelMode> coreModes) {
        Set<TravelMode> modes = new HashSet<>(coreModes);
        modes.add(TravelMode.WALK);
        return modes;
    }
}
