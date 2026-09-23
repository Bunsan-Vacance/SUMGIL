package com.ssafy.s15p21a104.domain.route.bike;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;

/**
 * 자전거 사용 위치 규칙(2026-09-23 사용자 결정) — 순수 로직, 한 곳 정의.
 *
 * <p>BIKE 런(연속 BIKE 엣지)은 <b>첫 탑승(SUBWAY·BUS) 전 1회</b>와 <b>마지막 하차 후 1회</b>만
 * 허용한다. 시작·끝 모두 가능하지만 <b>탑승 사이(중간)는 0회</b>이고, 접근·이탈 안에서도
 * 체인(2런)은 금지한다 — "대여소에 계속 반납/대여를 반복"하는 경로를 원천 차단한다.
 * 대중교통 없는 경로(도보+자전거 단독)는 총 1런까지 허용한다.
 *
 * <p>런 길이 상한(2km, {@link BikeEdgeBuilder#MAX_ACT_SEC})은 그대로 유지한다.
 */
public final class BikeUsePolicy {

    /** 접근·이탈 각 측의 허용 BIKE 런 수. */
    public static final int MAX_RUNS_PER_SIDE = 1;

    private BikeUsePolicy() {
    }

    /**
     * 이어온 상태에서 BIKE 연결을 쓸 수 있는가.
     *
     * @param round 탑승 라운드(0 = 접근 구간, ≥1 = 탑승 사이)
     * @param bikeRunSec 이어온 런 길이(초). 0이면 런 밖
     * @param bikeRuns 지금까지 쓴 런 수
     * @param addSec 추가할 BIKE 연결 길이(초)
     * @return 허용 여부
     */
    public static boolean allowsBikeConnection(int round, int bikeRunSec, int bikeRuns, int addSec) {
        if (round >= 1) {
            return false; // 탑승 사이 금지
        }
        if (bikeRunSec == 0 && bikeRuns >= MAX_RUNS_PER_SIDE) {
            return false; // 두 번째 런(체인) 금지
        }
        return bikeRunSec + addSec <= BikeEdgeBuilder.MAX_ACT_SEC;
    }

    /**
     * BIKE 연결을 쓴 뒤의 런 수.
     *
     * @param bikeRunSec 연결 전 런 길이(0이면 새 런 시작)
     * @param bikeRuns 연결 전 런 수
     * @return 연결 후 런 수
     */
    public static int runsAfterBike(int bikeRunSec, int bikeRuns) {
        return bikeRunSec > 0 ? bikeRuns : bikeRuns + 1;
    }

    /**
     * 경로 엣지 열이 위치·길이 규칙을 지키는가(엔진 공통 안전망).
     *
     * @param edges 경로 엣지(순서대로)
     * @return 규칙 준수 여부
     */
    public static boolean allowedPath(List<Edge> edges) {
        int firstTransit = -1;
        int lastTransit = -1;
        for (int i = 0; i < edges.size(); i++) {
            TravelMode mode = edges.get(i).mode();
            if (mode == TravelMode.SUBWAY || mode == TravelMode.BUS) {
                if (firstTransit < 0) {
                    firstTransit = i;
                }
                lastTransit = i;
            }
        }
        int accessRuns = 0;
        int middleRuns = 0;
        int egressRuns = 0;
        int runSec = 0;
        boolean inRun = false;
        for (int i = 0; i < edges.size(); i++) {
            Edge edge = edges.get(i);
            if (edge.mode() != TravelMode.BIKE) {
                inRun = false;
                runSec = 0;
                continue;
            }
            runSec += edge.travelSec();
            if (runSec > BikeEdgeBuilder.MAX_ACT_SEC) {
                return false;
            }
            if (!inRun) {
                inRun = true;
                if (firstTransit < 0 || i < firstTransit) {
                    accessRuns++;
                } else if (i > lastTransit) {
                    egressRuns++;
                } else {
                    middleRuns++;
                }
            }
        }
        if (firstTransit < 0) {
            return accessRuns <= MAX_RUNS_PER_SIDE; // 무탑승: 총 1런
        }
        return accessRuns <= MAX_RUNS_PER_SIDE
                && egressRuns <= MAX_RUNS_PER_SIDE
                && middleRuns == 0;
    }
}
