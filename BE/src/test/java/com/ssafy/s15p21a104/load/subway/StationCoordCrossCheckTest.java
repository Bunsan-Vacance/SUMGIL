package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 두 좌표 원천(국가철도공단 역위치 ↔ KTDB 노드)이 같은 역에서 크게 어긋나면 경고한다.
 * 실측: 148역 중 중앙값 33 m 로 일치하지만 산본 1.1 km · 별내별가람 7.8 km · 청산 28.6 km 는 어느 한쪽이 틀린 것이다.
 */
class StationCoordCrossCheckTest {

    @Test
    @DisplayName("임계값(500 m) 안이면 경고가 없다")
    void noWarningWithinThreshold() {
        List<String> w = StationCoordCrossCheck.warnings(
                List.of(new StationCoord("1001", "남영", 37.5410, 126.9712, null)),
                List.of(new StationCoord(null, "남영", 37.5403, 126.9712, null)), 500);

        assertTrue(w.isEmpty());
    }

    @Test
    @DisplayName("임계값을 넘으면 역 이름과 거리(m)를 담은 경고 한 줄 — 원천 어느 쪽을 쓸지는 호출자가 정한다")
    void warnsBeyondThreshold() {
        List<String> w = StationCoordCrossCheck.warnings(
                List.of(new StationCoord("1004", "산본", 37.3580, 126.9330, null)),
                List.of(new StationCoord(null, "산본", 37.3680, 126.9330, null)), 500);

        assertEquals(1, w.size());
        assertTrue(w.get(0).contains("산본") && w.get(0).contains("m"));
    }

    @Test
    @DisplayName("참조 원천에 없는 역은 비교하지 않는다")
    void skipsStationsMissingInReference() {
        List<String> w = StationCoordCrossCheck.warnings(
                List.of(new StationCoord("1001", "남영", 37.5410, 126.9712, null)), List.of(), 500);

        assertTrue(w.isEmpty());
    }

    @Test
    @DisplayName("resolve: 대체 임계값(5 km)을 넘게 어긋난 역은 원천 결함으로 보고 목록에서 빼서 참조 원천이 채우게 한다 — 청산 28 km, 별내별가람 7.8 km")
    void resolveDropsGrosslyWrongCoordinates() {
        StationCoordCrossCheck.Result r = StationCoordCrossCheck.resolve(
                List.of(new StationCoord("1001", "청산", 37.73873, 127.04589, null),
                        new StationCoord("1001", "남영", 37.5410, 126.9712, null)),
                List.of(new StationCoord(null, "청산", 37.99511, 127.07430, null),
                        new StationCoord(null, "남영", 37.5403, 126.9712, null)),
                500, 5000);

        assertEquals(1, r.kept().size());
        assertEquals("남영", r.kept().get(0).stationName());
        assertEquals(List.of("청산"), r.replaced());
        assertEquals(1, r.warnings().size());
        assertTrue(r.warnings().get(0).contains("청산") && r.warnings().get(0).contains("대체"));
    }

    @Test
    @DisplayName("resolve: 경고 임계값과 대체 임계값 사이(500 m~5 km)는 값을 유지하고 경고만 남긴다 — 산본 1.1 km")
    void resolveKeepsButWarnsInBetween() {
        StationCoordCrossCheck.Result r = StationCoordCrossCheck.resolve(
                List.of(new StationCoord("1004", "산본", 37.35030, 126.92554, null)),
                List.of(new StationCoord(null, "산본", 37.35808, 126.93312, null)),
                500, 5000);

        assertEquals(1, r.kept().size());
        assertTrue(r.replaced().isEmpty());
        assertEquals(1, r.warnings().size());
        assertTrue(r.warnings().get(0).contains("산본"));
    }

    @Test
    @DisplayName("resolve: 참조가 없거나 임계값 안이면 그대로 유지하고 경고도 없다")
    void resolveKeepsAgreeingOrUnreferenced() {
        StationCoordCrossCheck.Result r = StationCoordCrossCheck.resolve(
                List.of(new StationCoord("1001", "남영", 37.5410, 126.9712, null),
                        new StationCoord("1001", "구로", 37.5024, 126.8815, null)),
                List.of(new StationCoord(null, "남영", 37.5403, 126.9712, null)),
                500, 5000);

        assertEquals(2, r.kept().size());
        assertTrue(r.warnings().isEmpty());
        assertTrue(r.replaced().isEmpty());
    }

    @Test
    @DisplayName("majority: 국가철도공단이 표준데이터와 어긋나고 표준데이터·KTDB 가 일치하면 표준데이터 좌표로 바꾼다 — 한국항공대 4.9 km, 산본 1.1 km. 노선 코드는 유지")
    void majorityReplacesOutlierPrimary() {
        StationCoordCrossCheck.Result r = StationCoordCrossCheck.majority(
                List.of(new StationCoord("1063", "한국항공대", 37.637837, 126.832503, null),
                        new StationCoord("1004", "산본", 37.350297, 126.925537, null)),
                List.of(new StationCoord("1063", "한국항공대", 37.603102, 126.868291, "1268"),
                        new StationCoord(null, "산본", 37.358019, 126.932969, "1707")),
                List.of(new StationCoord(null, "한국항공대", 37.603419, 126.867672, null),
                        new StationCoord(null, "산본", 37.358076, 126.933117, null)),
                500);

        assertEquals(List.of("한국항공대", "산본"), r.replaced());
        assertEquals(2, r.warnings().size());
        StationCoord airUniv = r.kept().get(0);
        assertEquals("1063", airUniv.lineId());
        assertEquals(37.603102, airUniv.lat());
        assertEquals(126.868291, airUniv.lng());
        assertEquals("1004", r.kept().get(1).lineId());
    }

    @Test
    @DisplayName("majority: 세 원천이 다 없거나, 표준데이터와 KTDB 가 서로 어긋나면 판정하지 않고 그대로 둔다 (resolve 가 이어서 본다)")
    void majorityLeavesUndecidableAlone() {
        StationCoordCrossCheck.Result r = StationCoordCrossCheck.majority(
                List.of(new StationCoord("1075", "송도", 37.417769, 126.678991, null),
                        new StationCoord("1001", "남영", 37.5410, 126.9712, null)),
                List.of(new StationCoord("1075", "송도", 37.429714, 126.654486, null)),
                List.of(new StationCoord(null, "송도", 37.4500, 126.7000, null),
                        new StationCoord(null, "남영", 37.5403, 126.9712, null)),
                500);

        assertTrue(r.replaced().isEmpty());
        assertTrue(r.warnings().isEmpty());
        assertEquals(37.417769, r.kept().get(0).lat());
        assertEquals(2, r.kept().size());
    }
}
