package com.ssafy.s15p21a104.domain.route.finder.raptor;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.PriorityQueue;

/**
 * 연결망(도보·자전거) 접근·이탈 closure — RAPTOR 경계용(5부 R-A1).
 *
 * <p>RAPTOR는 연결(도보·자전거)을 라운드당 1홉만 이완한다. 출발지→대여소→대여소→역 같은
 * 다중 홉 경로는 엔진 안에서 표현할 수 없으므로, 경계에서 연결망 Dijkstra(one-to-many)로
 * 접근·이탈 테이블을 만들어 넘긴다 — 업계 정석(spec/route-modes §7.3, ULTRA·MR).
 *
 * <p>비용만이 아니라 <b>추적용 사슬</b>(직전/다음 구간)을 함께 담는다. 엔진이 journey 복원 시
 * 실제 WALK/BIKE leg를 그대로 방출할 수 있어야 하기 때문이다(비용만 주면 합성 leg로 뭉개진다).
 *
 * <p>모드 필터는 호출부 책임이다(전달받은 연결 목록만 사용). 순수 로직이며 DB에 의존하지 않는다.
 */
public final class RaptorAccessClosure {

    private static final int INF = Integer.MAX_VALUE / 4;

    private RaptorAccessClosure() {
    }

    /**
     * 출발 정점에서 연결망을 타고 도달 가능한 모든 정점의 최소 비용과 사슬.
     *
     * @param originNodeId 출발 정점(좌표 검색의 PLACE-ORIGIN 등)
     * @param connections 방향별 연결(도보·자전거). 호출부가 모드 필터한 목록
     * @return 정점 → 접근(Access). 도달 불가 정점은 키 없음. 시드는 {@code fromNode == null}
     */
    public static Map<String, RaptorFinder.Access> from(String originNodeId,
                                                        List<RaptorFinder.Connection> connections) {
        Objects.requireNonNull(originNodeId, "originNodeId");
        Objects.requireNonNull(connections, "connections");
        Map<String, List<RaptorFinder.Connection>> bySource = new HashMap<>();
        for (RaptorFinder.Connection connection : connections) {
            bySource.computeIfAbsent(connection.from(), key -> new ArrayList<>()).add(connection);
        }
        return forwardClosure(originNodeId, bySource);
    }

    /**
     * 연결망을 타고 도착 정점으로 갈 수 있는 모든 정점의 최소 비용과 사슬 — 역방향.
     *
     * @param destNodeId 도착 정점(좌표 검색의 PLACE-DEST 등)
     * @param connections 방향별 연결(도보·자전거). 호출부가 모드 필터한 목록
     * @return 정점 → 이탈(Egress). 도달 불가 정점은 키 없음. 시드는 {@code toNode == null}
     */
    public static Map<String, RaptorFinder.Egress> to(String destNodeId,
                                                      List<RaptorFinder.Connection> connections) {
        Objects.requireNonNull(destNodeId, "destNodeId");
        Objects.requireNonNull(connections, "connections");
        Map<String, List<RaptorFinder.Connection>> byTarget = new HashMap<>();
        for (RaptorFinder.Connection connection : connections) {
            byTarget.computeIfAbsent(connection.to(), key -> new ArrayList<>()).add(connection);
        }
        return reverseClosure(destNodeId, byTarget);
    }

    /** 연결망 다익스트라(정방향) — 각 정점의 최선 직전 구간을 남긴다. */
    private static Map<String, RaptorFinder.Access> forwardClosure(String originNodeId,
            Map<String, List<RaptorFinder.Connection>> bySource) {
        record Entry(String node, int cost) {
        }
        Map<String, Integer> best = new HashMap<>();
        Map<String, Integer> bestBikeRun = new HashMap<>();
        Map<String, RaptorFinder.Access> out = new HashMap<>();
        PriorityQueue<Entry> queue = new PriorityQueue<>(Comparator.comparingInt(Entry::cost));
        best.put(originNodeId, 0);
        bestBikeRun.put(originNodeId, 0);
        out.put(originNodeId, new RaptorFinder.Access(0, null, 0, TravelMode.WALK, 0));
        queue.add(new Entry(originNodeId, 0));
        while (!queue.isEmpty()) {
            Entry entry = queue.poll();
            if (entry.cost() > best.getOrDefault(entry.node(), INF)) {
                continue; // 낡은 항목
            }
            int run = bestBikeRun.getOrDefault(entry.node(), 0);
            for (RaptorFinder.Connection connection : bySource.getOrDefault(entry.node(), List.of())) {
                boolean bike = connection.mode() == TravelMode.BIKE;
                int nextRun = bike ? run + connection.sec() : 0;
                if (bike && nextRun > com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder
                        .MAX_ACT_SEC) {
                    continue; // 대여 1회 상한 초과 — 가지치기(5부 T3)
                }
                int nextCost = entry.cost() + connection.sec();
                if (nextCost < best.getOrDefault(connection.to(), INF)) {
                    best.put(connection.to(), nextCost);
                    bestBikeRun.put(connection.to(), nextRun);
                    out.put(connection.to(), new RaptorFinder.Access(
                            nextCost, entry.node(), connection.sec(), connection.mode(), nextRun));
                    queue.add(new Entry(connection.to(), nextCost));
                }
            }
        }
        return out;
    }

    /** 연결망 다익스트라(역방향) — 각 정점의 최선 다음 구간을 남긴다. */
    private static Map<String, RaptorFinder.Egress> reverseClosure(String destNodeId,
            Map<String, List<RaptorFinder.Connection>> byTarget) {
        record Entry(String node, int cost) {
        }
        Map<String, Integer> best = new HashMap<>();
        Map<String, Integer> bestBikeRun = new HashMap<>();
        Map<String, RaptorFinder.Egress> out = new HashMap<>();
        PriorityQueue<Entry> queue = new PriorityQueue<>(Comparator.comparingInt(Entry::cost));
        best.put(destNodeId, 0);
        bestBikeRun.put(destNodeId, 0);
        out.put(destNodeId, new RaptorFinder.Egress(0, null, 0, TravelMode.WALK, 0));
        queue.add(new Entry(destNodeId, 0));
        while (!queue.isEmpty()) {
            Entry entry = queue.poll();
            if (entry.cost() > best.getOrDefault(entry.node(), INF)) {
                continue; // 낡은 항목
            }
            int run = bestBikeRun.getOrDefault(entry.node(), 0);
            for (RaptorFinder.Connection connection : byTarget.getOrDefault(entry.node(), List.of())) {
                boolean bike = connection.mode() == TravelMode.BIKE;
                int nextRun = bike ? run + connection.sec() : 0;
                if (bike && nextRun > com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder
                        .MAX_ACT_SEC) {
                    continue; // 대여 1회 상한 초과 — 가지치기(5부 T3)
                }
                int nextCost = entry.cost() + connection.sec();
                if (nextCost < best.getOrDefault(connection.from(), INF)) {
                    best.put(connection.from(), nextCost);
                    bestBikeRun.put(connection.from(), nextRun);
                    out.put(connection.from(), new RaptorFinder.Egress(
                            nextCost, entry.node(), connection.sec(), connection.mode(), nextRun));
                    queue.add(new Entry(connection.from(), nextCost));
                }
            }
        }
        return out;
    }
}
