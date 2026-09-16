package com.ssafy.s15p21a104.domain.route;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.SlotVariant.SLOT_BOUNDARY;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.SlotVariant.WEEKDAY_MORNING;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.SlotVariant.WEEKEND;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.StockVariant.DEPLETED;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.StockVariant.NO_SOURCE;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.StockVariant.PRESENT;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bikeLeg;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bikeStock;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.congestedGraph;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.disconnectedGraph;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.measuredRule;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.measuredTransferTimes;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.mockStation;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.slot;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.stationInfos;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.stationInfosWithNullCoords;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subwayLeg;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeStockGate;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.ShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-120 중앙 픽스처 사용 예시. 각 선행 픽스처가 호출 가능함을 보인다.
 * 본 구현 변경 없이 조립 함수만 검증한다.
 */
class RouteTestFixturesTest {

    @Test
    @DisplayName("120-E1: 그래프·역·표시정보 조립이 동작한다")
    void e1_기본조립() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100));

        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals("A", mockStation("A", "에이역").getStationId());
        assertEquals(3, stationInfos("A", "B", "C").size());
    }

    @Test
    @DisplayName("120-E2: 버스 엣지가 그래프에 실린다")
    void e2_버스엣지() {
        RouteGraph graph = graphOf(
                bus("A", "B", "B100", 300),
                subway("B", "C", "L1", 100));

        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertTrue(path.edges().stream().anyMatch(e -> e.mode() == TravelMode.BUS));
    }

    @Test
    @DisplayName("120-E3: 혼잡도 비교용 그래프가 탐색된다")
    void e3_혼잡도그래프() {
        FoundPath path = new ShortestPathFinder(new TransferRule(180))
                .find(congestedGraph(), "A", "C");

        assertEquals("A", path.stations().get(0));
        assertEquals("C", path.stations().get(path.stations().size() - 1));
    }

    @Test
    @DisplayName("120-E4: 재고 3종 변형이 게이트 판정에 반영된다")
    void e4_재고변형() {
        assertTrue(BikeStockGate.passes(List.of(bikeLeg("R1")), bikeStock(PRESENT)));
        assertFalse(BikeStockGate.passes(List.of(bikeLeg("R1"), subwayLeg()), bikeStock(DEPLETED)));
        assertTrue(BikeStockGate.passes(List.of(bikeLeg("R1")), bikeStock(NO_SOURCE)));
    }

    @Test
    @DisplayName("120-E5: 실측 표준 규칙이 환승에 적용된다")
    void e5_실측규칙() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L2", 50));

        FoundPath path = new ShortestPathFinder(measuredRule()).find(graph, "A", "C");

        assertEquals(100 + 50 + 60, path.totalSec());
        assertEquals(1, measuredTransferTimes().size());
    }

    @Test
    @DisplayName("120-E6: 출발시각 슬롯 3종이 구분된다")
    void e6_시각슬롯() {
        assertTrue(slot(WEEKDAY_MORNING).timeSlot() != slot(WEEKEND).timeSlot()
                || slot(WEEKDAY_MORNING).dowType() != slot(WEEKEND).dowType());
        assertEquals(19, slot(SLOT_BOUNDARY).timeSlot());
    }

    @Test
    @DisplayName("120-E7: 좌표 null 표시정보와 도보·자전거 엣지가 조립된다")
    void e7_geometry경계() {
        Map<String, RouteMapper.StationInfo> infos = stationInfosWithNullCoords(
                List.of("B"), List.of("A", "C"));

        assertTrue(infos.get("B").lat() == null);
        assertTrue(infos.get("A").lat() != null);
        assertEquals(TravelMode.WALK, walk("A", "R1", 120).mode());
        assertEquals(TravelMode.BIKE, bike("A", "R1", 120).mode());
    }

    @Test
    @DisplayName("120-E8: 고립 그래프에서 도달 불가 구간이 확인된다")
    void e8_경계그래프() {
        RouteGraph graph = disconnectedGraph();

        assertTrue(graph.findEdge("X", "X").isPresent());
        assertTrue(graph.findEdge("A", "X").isEmpty());
    }
}
