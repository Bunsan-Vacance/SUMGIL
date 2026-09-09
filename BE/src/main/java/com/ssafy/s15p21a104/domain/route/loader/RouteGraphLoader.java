package com.ssafy.s15p21a104.domain.route.loader;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.graph.RouteNameMapper;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.extern.slf4j.Slf4j;

/**
 * SUBWAY 구간 행 원시 데이터를 {@link RouteGraph}로 순수 조립하는 로더.
 *
 * <p>DB·Redis 접근이 전혀 없으며 {@link RouteGraphRawData}를 받아 그래프를 조립한다.
 * 실제 조회는 별도 DB 조회 계약(Repository)이 맡아 이 로더에 원시 데이터만 넘긴다.
 *
 * <p>조립 규칙
 * <ul>
 *   <li>행 1개 = 유향 엣지 1개. 동일 구간에 양방향 행이 있으면 엣지 2개.</li>
 *   <li>단방향 행만 있으면 엣지 1개뿐이며 역방향을 임의로 만들지 않는다.</li>
 *   <li>정점 = 역 ID 하나. 같은 역이 여러 노선에 걸쳐도 정점은 하나(노선별 정점 금지).</li>
 *   <li>환승 노드·엣지를 만들지 않는다.</li>
 *   <li>역별 소속 노선 목록은 그 역을 잇는 엣지들의 {@code routeId} 집합에서 파생한다.</li>
 *   <li>SUBWAY 행이 0개면 빈 그래프를 반환하지 않고 {@link DomainException}으로 실패한다.</li>
 * </ul>
 */
@Slf4j
public final class RouteGraphLoader {

    private RouteGraphLoader() {
    }

    /**
     * 원시 SUBWAY 행·이름 데이터로 그래프와 이름 매핑을 조립한다.
     *
     * <p>입력 검증(빈 데이터)을 제외하면 순수 함수이며 호출마다 새 {@link RouteGraph}를 만든다.
     *
     * @param rawData SUBWAY 행(대표 슬롯 필터 후)·역·노선 이름
     * @return 로드 결과(조립된 불변 그래프와 이름 매핑)
     * @throws DomainException SUBWAY 행이 0개일 때
     */
    public static LoadResult load(RouteGraphRawData rawData) {
        List<RouteEdgeRow> rows = rawData == null ? null : rawData.subwayEdges();
        if (rows == null || rows.isEmpty()) {
            log.error("지하철 메모리 그래프 로드 실패: SUBWAY 행이 0개이다.");
            throw new DomainException(ErrorType.INTERNAL_SERVER_ERROR);
        }

        Set<String> nodes = new LinkedHashSet<>();
        Map<String, List<Edge>> adjacency = new LinkedHashMap<>();
        Map<String, Set<String>> stationLines = new LinkedHashMap<>();

        for (RouteEdgeRow row : rows) {
            Edge edge = toEdge(row);

            // 정점: 출발·도착 역 ID를 각각 정점으로 등록(중복은 집합이 흡수).
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());

            // 인접 리스트: 출발 역의 나가는 엣지 목록.
            adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>())
                    .add(edge);

            // 역 소속 노선 파생: 해당 구간을 잇는 엣지의 routeId.
            stationLines.computeIfAbsent(edge.fromNode(), key -> new LinkedHashSet<>())
                    .add(edge.routeId());
            stationLines.computeIfAbsent(edge.toNode(), key -> new LinkedHashSet<>())
                    .add(edge.routeId());
        }

        RouteGraph graph = RouteGraph.of(nodes, adjacency, stationLines);
        RouteNameMapper nameMapper = new RouteNameMapper(rawData.stationNames(), rawData.lineNames());

        log.info("지하철 메모리 그래프 로드 완료: 역 {}개, 엣지 {}개", graph.nodeCount(), graph.edgeCount());

        return new LoadResult(graph, nameMapper);
    }

    private static Edge toEdge(RouteEdgeRow row) {
        // SUBWAY 행만 다루므로 수단을 고정 주입한다. 비용·분기에는 쓰지 않는다.
        return new Edge(row.fromNode(), row.toNode(), row.routeId(),
                row.travelSec(), row.waitSec(), TravelMode.SUBWAY);
    }

    /**
     * 로드 결과. 불변 그래프와 이름 매핑의 묶음.
     *
     * @param graph 조립된 그래프(불변)
     * @param nameMapper 역·노선 이름 매핑
     */
    public record LoadResult(RouteGraph graph, RouteNameMapper nameMapper) {
    }
}
