package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Objects;

/**
 * 수단 교체(환승) 상한(S15P21A104-337, 2026-09-27 사용자 결정) — 순수 로직, 한 곳 정의.
 *
 * <p>탑승 = 지하철·버스의 같은 노선 연속 구간 1회, 자전거 런 1회. 도보·환승 구간은 탑승으로 세지 않고,
 * 끼면 탑승이 끊긴 것으로 본다.
 * 수단 교체 = 탑승 횟수 − 1, 상한 {@value #MAX_MODE_CHANGES}회. RAPTOR 라운드(대중교통 4회)와
 * 접근·이탈 자전거가 겹쳐 탑승 5~6회 조합이 나오던 것을 막는 안전장치다.
 */
public final class ModeChangePolicy {

    /** 수단 교체 상한. */
    public static final int MAX_MODE_CHANGES = 3;

    private ModeChangePolicy() {
    }

    /**
     * @param edges 경로 엣지(순서대로)
     * @return 수단 교체 횟수(탑승 횟수 − 1, 탑승이 없으면 0)
     */
    public static int modeChanges(List<Edge> edges) {
        Objects.requireNonNull(edges, "edges");
        int rides = 0;
        String current = null;
        for (Edge edge : edges) {
            TravelMode mode = edge.mode();
            if (mode != TravelMode.SUBWAY && mode != TravelMode.BUS && mode != TravelMode.BIKE) {
                current = null; // 도보·환승이 끼면 탑승이 끊긴다
                continue;
            }
            // 자전거는 런 단위, 대중교통은 노선 단위로 같은 탑승을 이어 본다.
            String ride = mode == TravelMode.BIKE ? "BIKE" : mode + ":" + edge.routeId();
            if (!ride.equals(current)) {
                rides++;
                current = ride;
            }
        }
        return Math.max(0, rides - 1);
    }

    /** 경로가 수단 교체 상한을 지키는가(엔진 공통 안전망). */
    public static boolean allowedPath(List<Edge> edges) {
        return modeChanges(edges) <= MAX_MODE_CHANGES;
    }
}
