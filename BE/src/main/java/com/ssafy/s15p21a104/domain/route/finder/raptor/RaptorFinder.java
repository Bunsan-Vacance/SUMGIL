package com.ssafy.s15p21a104.domain.route.finder.raptor;

import com.ssafy.s15p21a104.domain.route.bike.BikeUsePolicy;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 노선 스캔(RAPTOR) 탐색 프로토타입 — raptor-transition 티켓 ②.
 *
 * <p>엣지·정점 그래프 대신 <b>노선(정류장 순서 배열)</b>을 스캔한다. 라운드 = 환승 횟수이며
 * 중간 하차·환승이 스캔에서 자연 처리된다(설계 4부 부속 §3). kept 집합·corridor options·
 * 폴백 구조가 없다.
 *
 * <p>순수 로직이며 DB·Spring에 의존하지 않는다. 비용은 기본 {@code travelSec}이며
 * {@link SegmentCost}로 통과 시각·혼잡을 반영한다(calm). fast 모드는 비용=시간으로 두고
 * 최선 탑승 압축 단일 스캔, calm은 통과 시각별 비용 때문에 탑승별 전개(O(n²/2))를 쓴다.
 *
 * <p>프로토타입 범위: 도달·환승·대기·연결(도보·자전거)·라운드별 journey 산출.
 * 모드 필터·FoundPath 어댑터·파이프라인 교체(③)는 다음 단계.
 */
public final class RaptorFinder {

    /**
     * 노선 한 개. {@code stops[i] → stops[i+1]} 소요가 {@code travelSec[i]}, 정류장 {@code i}에서의
     * 승차 대기가 {@code boardWaitSec[i]}(버스 headway/2·지하철 대기, 미정이면 0).
     */
    public record Route(String routeId, TravelMode mode, List<String> stops, int[] travelSec,
                        int[] boardWaitSec) {
        public Route {
            Objects.requireNonNull(routeId, "routeId");
            Objects.requireNonNull(mode, "mode");
            Objects.requireNonNull(stops, "stops");
            Objects.requireNonNull(travelSec, "travelSec");
            Objects.requireNonNull(boardWaitSec, "boardWaitSec");
            if (stops.size() < 2 || travelSec.length != stops.size() - 1
                    || boardWaitSec.length != stops.size()) {
                throw new IllegalArgumentException("노선 길이 불일치: " + routeId);
            }
            for (int sec : travelSec) {
                if (sec < 0) {
                    throw new IllegalArgumentException("구간 소요 음수: " + routeId);
                }
            }
            for (int sec : boardWaitSec) {
                if (sec < 0) {
                    throw new IllegalArgumentException("승차 대기 음수: " + routeId);
                }
            }
        }

        /** 승차 대기 균일 노선(테스트·단순화용). */
        public Route(String routeId, TravelMode mode, List<String> stops, int[] travelSec,
                     int waitSec) {
            this(routeId, mode, stops, travelSec, uniform(stops.size(), waitSec));
        }

        private static int[] uniform(int length, int waitSec) {
            int[] waits = new int[length];
            java.util.Arrays.fill(waits, waitSec);
            return waits;
        }
    }

    /** 노선 밖 연결(도보·자전거). 방향 1건씩 등록한다. */
    public record Connection(String from, String to, int sec, TravelMode mode) {
        public Connection {
            if (sec < 0) {
                throw new IllegalArgumentException("연결 소요 음수");
            }
        }
    }

    /** 접근 사슬 한 칸 — 정점 도달 비용·직전 구간·자전거 누적(추적·상한·런 수). {@code fromNode == null}이면 시드(출발지). */
    public record Access(int costSec, String fromNode, int legSec, TravelMode mode, int bikeRunSec, int bikeRuns) {
    }

    /** 이탈 사슬 한 칸 — 정점에서 도착지까지의 비용·다음 구간·자전거 누적. {@code toNode == null}이면 시드(도착지). */
    public record Egress(int costSec, String toNode, int legSec, TravelMode mode, int bikeRunSec, int bikeRuns) {
    }

    /** 경계(접근·이탈 closure)가 만든 테이블 묶음 — 비용 + 경로 사슬(5부 R-A1). */
    public record AccessTables(Map<String, Access> origin, Map<String, Egress> dest) {
    }

    /** 구간 비용(초). {@code passThroughSec} = 구간 진입 시각(출발 기준 경과 초). */
    @FunctionalInterface
    public interface SegmentCost {
        long cost(String routeId, int fromIdx, int toIdx, long passThroughSec, int travelSec);

        /** 기본: 시간 비용 그대로. */
        SegmentCost TIME = (routeId, fromIdx, toIdx, passThroughSec, travelSec) -> travelSec;
    }

    /** journey 한 구간. transit = 노선 탑승(구간 전개용 {@code routeIndex}·정류장 위치 보유), 연결 = 접근·도보·자전거. */
    public record Leg(String routeId, TravelMode mode, String from, String to,
                      long boardSec, long alightSec, int routeIndex, int boardIndex, int alightIndex) {
        /** 연결·접근 leg. */
        public static Leg connection(String routeId, TravelMode mode, String from, String to,
                                     long boardSec, long alightSec) {
            return new Leg(routeId, mode, from, to, boardSec, alightSec, -1, -1, -1);
        }
    }

    public record Journey(List<Leg> legs, long totalSec, long totalCost, int transfers) {
    }

    private static final long INF = Long.MAX_VALUE / 4;

    private final List<Route> routes;
    private final Map<String, List<Connection>> connectionsBySource;
    private final SegmentCost costModel;

    public RaptorFinder(List<Route> routes, List<Connection> connections) {
        this(routes, connections, SegmentCost.TIME);
    }

    public RaptorFinder(List<Route> routes, List<Connection> connections, SegmentCost costModel) {
        this.routes = List.copyOf(routes);
        this.costModel = Objects.requireNonNull(costModel, "costModel");
        Map<String, List<Connection>> bySource = new HashMap<>();
        for (Connection connection : connections) {
            bySource.computeIfAbsent(connection.from(), key -> new ArrayList<>()).add(connection);
        }
        this.connectionsBySource = bySource;
    }

    /**
     * 라운드별 최선 journey(개선된 라운드만). 라운드에서 개선이 없으면 조기 종료.
     *
     * @param minimizeCost true면 비용(costModel 반영) 최소화, false면 시간 최소화
     */
    /** 비용만 있는 접근·이탈 맵(기존 API) — 경로 추적 정보 없이 시드로 감싼다. */
    public List<Journey> find(String originNodeId, String destNodeId,
                              Map<String, Integer> originAccess, Map<String, Integer> destAccess,
                              int maxRounds, boolean minimizeCost) {
        Objects.requireNonNull(originAccess, "originAccess");
        Objects.requireNonNull(destAccess, "destAccess");
        Map<String, Access> accesses = new HashMap<>();
        for (Map.Entry<String, Integer> entry : originAccess.entrySet()) {
            accesses.put(entry.getKey(), new Access(entry.getValue(), null, 0, TravelMode.WALK, 0, 0));
        }
        Map<String, Egress> egresses = new HashMap<>();
        for (Map.Entry<String, Integer> entry : destAccess.entrySet()) {
            egresses.put(entry.getKey(), new Egress(entry.getValue(), null, 0, TravelMode.WALK, 0, 0));
        }
        return find(originNodeId, destNodeId, new AccessTables(accesses, egresses),
                maxRounds, minimizeCost);
    }

    /**
     * 경계가 만든 접근·이탈 테이블(경로 사슬 포함)로 탐색한다(5부 R-A1).
     * 라운드 0 라벨이 접근 사슬을 그대로 이어받고, 복원이 이탈 사슬을 실제 연결 leg로 편다.
     */
    public List<Journey> find(String originNodeId, String destNodeId, AccessTables accessTables,
                              int maxRounds, boolean minimizeCost) {
        return find(originNodeId, destNodeId, accessTables, maxRounds, minimizeCost, false);
    }

    /**
     * @param requireTransit true면 탑승(BUS·SUBWAY) leg가 있는 최선만 journey로 돌려준다 —
     *        비탑승(전부 연결) 최단이 1등일 때 탑승 대안을 얻기 위한 모드(K 후보 수집)
     */
    public List<Journey> find(String originNodeId, String destNodeId, AccessTables accessTables,
                              int maxRounds, boolean minimizeCost, boolean requireTransit) {
        Objects.requireNonNull(accessTables, "accessTables");
        Map<String, Access> originAccess = accessTables.origin();
        Map<String, Egress> destAccess = accessTables.dest();
        Objects.requireNonNull(originAccess, "originAccess");
        Objects.requireNonNull(destAccess, "destAccess");
        if (maxRounds <= 0 || originAccess.isEmpty() || destAccess.isEmpty()) {
            return List.of();
        }
        List<Map<String, Label>> byRound = new ArrayList<>();
        Map<String, Label> round0 = new HashMap<>();
        for (Map.Entry<String, Access> access : originAccess.entrySet()) {
            Access value = access.getValue();
            Trace trace = value.fromNode() == null
                    ? new Trace(-1, null, "WALK", TravelMode.WALK, 0, value.costSec(), -1, -1, -1)
                    : new Trace(0, value.fromNode(), connectionRouteId(value.mode()), value.mode(),
                            value.costSec() - value.legSec(), value.costSec(), -1, -1, -1);
            round0.put(access.getKey(), new Label(value.costSec(), value.costSec(), 0,
                    value.bikeRunSec(), value.bikeRuns(), trace));
        }
        // 라운드 0 연결 이완 — 사슬 없는 단순 맵(기존 API)의 출발지 접근 한 홉 호환.
        relaxConnections(round0, 0, originAccess.keySet(), minimizeCost);
        byRound.add(round0);

        List<Journey> found = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        long prevBest = INF;
        Map<String, Label> prev = round0;

        for (int round = 1; round <= maxRounds; round++) {
            Map<String, Label> current = new HashMap<>(prev); // 이하 r회 — 이월
            Set<String> improvedStops = new LinkedHashSet<>();
            boolean improved = false;
            for (int routeIndex = 0; routeIndex < routes.size(); routeIndex++) {
                Route route = routes.get(routeIndex);
                improved |= scanRoute(route, routeIndex, prev, current, round, minimizeCost, improvedStops);
            }
            if (!improvedStops.isEmpty()) {
                improved |= relaxConnections(current, round, improvedStops, minimizeCost);
            }
            byRound.add(current);

            Journey best = bestJourney(byRound, destAccess, minimizeCost, originNodeId, destNodeId,
                    requireTransit);
            if (best != null && best.totalCost() < prevBest) {
                if (seen.add(signatureOf(best))) {
                    found.add(best);
                }
                prevBest = best.totalCost();
            }
            if (!improved) {
                break;
            }
            prev = current;
        }
        return List.copyOf(found);
    }

    /** 노선 한 개를 정류장 순서대로 훑어 하차 라벨을 이완한다. */
    private boolean scanRoute(Route route, int routeIndex, Map<String, Label> prev, Map<String, Label> current,
                              int round, boolean minimizeCost, Set<String> improvedStops) {
        List<String> stops = route.stops();
        int n = stops.size();
        boolean improved = false;
        if (!minimizeCost) {
            // fast: 단일 스캔 + 최선 탑승 압축(시각 최소화). 라운드 로컬 상태.
            long[] prefix = new long[n];
            for (int i = 0; i + 1 < n; i++) {
                prefix[i + 1] = prefix[i] + route.travelSec()[i];
            }
            long bestDepart = INF;
            int bestIdx = -1;
            Label bestBoarding = null;
            for (int i = 1; i < n; i++) {
                // 탑승 후보 갱신은 i-1 정류장까지 반영된 뒤 i로 전진한다.
                Label boarding = prev.get(stops.get(i - 1));
                if (boarding != null) {
                    long depart = boarding.time() + route.boardWaitSec()[i - 1];
                    if (depart < bestDepart) {
                        bestDepart = depart;
                        bestIdx = i - 1;
                        bestBoarding = boarding;
                    }
                }
                if (bestIdx < 0) {
                    continue;
                }
                long arrival = bestDepart + (prefix[i] - prefix[bestIdx]);
                Label label = new Label(arrival, arrival, bestBoarding.rides() + 1, 0,
                        bestBoarding.bikeRuns(),
                        new Trace(round - 1, stops.get(bestIdx),
                        route.routeId(), route.mode(), bestDepart, arrival, routeIndex, bestIdx, i));
                if (relax(current, stops.get(i), label)) {
                    improved = true;
                    improvedStops.add(stops.get(i));
                }
            }
        } else {
            // calm: 통과 시각별 비용 때문에 탑승별 전개(노선당 n≈58).
            for (int i = 0; i + 1 < n; i++) {
                Label boarding = prev.get(stops.get(i));
                if (boarding == null) {
                    continue;
                }
                long wait = route.boardWaitSec()[i];
                long time = boarding.time() + wait;
                long cost = boarding.cost() + wait;
                for (int j = i + 1; j < n; j++) {
                    int seg = j - 1;
                    long passThrough = time;
                    long segCost = costModel.cost(route.routeId(), seg, j, passThrough,
                            route.travelSec()[seg]);
                    time += route.travelSec()[seg];
                    cost += segCost;
                    Label label = new Label(time, cost, boarding.rides() + 1, 0,
                            boarding.bikeRuns(),
                            new Trace(round - 1, stops.get(i),
                            route.routeId(), route.mode(), boarding.time() + wait, time,
                            routeIndex, i, j));
                    if (relax(current, stops.get(j), label)) {
                        improved = true;
                        improvedStops.add(stops.get(j));
                    }
                }
            }
        }
        return improved;
    }

    /** 이번 라운드 개선 정류장에서 연결(도보·자전거)을 이완한다(같은 라운드 전환). */
    private boolean relaxConnections(Map<String, Label> current, int round,
                                     Set<String> improvedStops, boolean minimizeCost) {
        boolean improved = false;
        for (String stop : List.copyOf(improvedStops)) {
            List<Connection> connections = connectionsBySource.get(stop);
            if (connections == null) {
                continue;
            }
            Label from = current.get(stop);
            for (Connection connection : connections) {
                boolean bike = connection.mode() == TravelMode.BIKE;
                // 자전거 위치 규칙(2026-09-23): 탑승 사이 금지·측당 1런·2km 상한.
                if (bike && !BikeUsePolicy.allowsBikeConnection(
                        round, from.bikeRunSec(), from.bikeRuns(), connection.sec())) {
                    continue;
                }
                int bikeRun = bike ? from.bikeRunSec() + connection.sec() : 0;
                int bikeRuns = bike
                        ? BikeUsePolicy.runsAfterBike(from.bikeRunSec(), from.bikeRuns())
                        : from.bikeRuns();
                long time = from.time() + connection.sec();
                long cost = from.cost() + connection.sec();
                Label label = new Label(time, cost, from.rides(), bikeRun, bikeRuns,
                        new Trace(round, connection.from(),
                        connection.mode() == TravelMode.BIKE ? "BIKE" : "WALK",
                        connection.mode(), from.time(), time, -1, -1, -1));
                if (relax(current, connection.to(), label)) {
                    improved = true;
                }
            }
        }
        return improved;
    }

    /** 비용 기준 이완. fast 모드는 cost=time이라 시간 최소화와 동일해진다. */
    private static boolean relax(Map<String, Label> current, String stop, Label candidate) {
        Label existing = current.get(stop);
        if (existing == null || candidate.cost() < existing.cost()) {
            current.put(stop, candidate);
            return true;
        }
        return false;
    }

    /** 라운드별 최선 도착 journey. 하차 정류장 → 도착지 접근 비용을 더해 비교한다. */
    private Journey bestJourney(List<Map<String, Label>> byRound,
                                Map<String, Egress> destAccess, boolean minimizeCost,
                                String originNodeId, String destNodeId, boolean requireTransit) {
        long bestTotal = INF;
        int bestRound = -1;
        String bestStop = null;
        for (int round = 0; round < byRound.size(); round++) {
            Map<String, Label> labels = byRound.get(round);
            for (Map.Entry<String, Egress> dest : destAccess.entrySet()) {
                Label label = labels.get(dest.getKey());
                if (label == null) {
                    continue;
                }
                if (requireTransit && label.rides() < 1) {
                    continue;
                }
                long base = minimizeCost ? label.cost() : label.time();
                long total = base + dest.getValue().costSec();
                if (total < bestTotal) {
                    bestTotal = total;
                    bestRound = round;
                    bestStop = dest.getKey();
                }
            }
        }
        if (bestRound < 0) {
            return null;
        }
        return reconstruct(byRound, bestRound, bestStop, destAccess, minimizeCost,
                originNodeId, destNodeId);
    }

    /** 라벨 사슬을 따라 journey를 복원한다. trace.prevRound = 같은 라운드(연결) / 이전 라운드(탑승). */
    private Journey reconstruct(List<Map<String, Label>> byRound, int round, String stop,
                                Map<String, Egress> destAccess, boolean minimizeCost,
                                String originNodeId, String destNodeId) {
        List<Leg> legs = new ArrayList<>();
        Label label = byRound.get(round).get(stop);
        String current = stop;
        while (label != null) {
            Trace trace = label.trace();
            if (trace.prevRound() < 0) {
                legs.add(0, Leg.connection("WALK", TravelMode.WALK, originNodeId, current,
                        0, label.time()));
                break;
            }
            legs.add(0, new Leg(trace.routeId(), trace.mode(), trace.boardStop(), current,
                    trace.boardTime(), trace.alightTime(),
                    trace.routeIndex(), trace.boardIndex(), trace.alightIndex()));
            current = trace.boardStop();
            label = byRound.get(trace.prevRound()).get(current);
        }
        long alightSec = byRound.get(round).get(stop).time();
        long alightCost = byRound.get(round).get(stop).cost();
        // 이탈 사슬 — 도착지까지 실제 연결 leg(들)을 편다. 사슬이 없으면(비용만 있는 맵·역 도착)
        // 기존과 같은 합성 leg를 남긴다(어댑터가 0초 동일노드 leg를 제거).
        Egress seed = destAccess.get(stop);
        long egressSec = seed == null ? 0 : seed.costSec();
        String node = stop;
        long t = alightSec;
        Egress step = seed;
        while (step != null && step.toNode() != null) {
            legs.add(Leg.connection(connectionRouteId(step.mode()), step.mode(), node, step.toNode(),
                    t, t + step.legSec()));
            t += step.legSec();
            node = step.toNode();
            step = destAccess.get(node);
        }
        if (node.equals(stop)) {
            legs.add(Leg.connection("WALK", TravelMode.WALK, stop, destNodeId,
                    alightSec, alightSec + egressSec));
        }
        int rides = 0;
        for (Leg leg : legs) {
            if (leg.mode() == TravelMode.BUS || leg.mode() == TravelMode.SUBWAY) {
                rides++;
            }
        }
        return new Journey(List.copyOf(legs), alightSec + egressSec, alightCost + egressSec,
                Math.max(0, rides - 1));
    }

    /** 연결 leg의 routeId — 기존 엔진과 같은 문자열 규칙(WALK/BIKE). */
    private static String connectionRouteId(TravelMode mode) {
        return mode == TravelMode.BIKE ? "BIKE" : "WALK";
    }

    /** journey의 leg 서명 — 라운드 간 중복 제거용. */
    private static String signatureOf(Journey journey) {
        StringBuilder signature = new StringBuilder();
        for (Leg leg : journey.legs()) {
            signature.append(leg.mode()).append(':').append(leg.from()).append('>')
                    .append(leg.to()).append(':').append(leg.routeId()).append('|');
        }
        return signature.toString();
    }

    /** rides = 이 라벨 사슬의 탑승(BUS·SUBWAY) 횟수 · bikeRunSec = 연속 자전거 누적(대여 1회 상한용). */
    private record Label(long time, long cost, int rides, int bikeRunSec, int bikeRuns, Trace trace) {
    }

    private record Trace(int prevRound, String boardStop, String routeId, TravelMode mode,
                         long boardTime, long alightTime, int routeIndex, int boardIndex,
                         int alightIndex) {
    }
}
