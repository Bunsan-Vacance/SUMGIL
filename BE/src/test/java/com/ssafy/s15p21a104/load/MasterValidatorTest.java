package com.ssafy.s15p21a104.load;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.bike.BikeStationRow;
import com.ssafy.s15p21a104.load.bus.BusRouteRow;
import com.ssafy.s15p21a104.load.bus.BusStopRow;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 마스터 3종(bus_stop·bus_route·bike_station)의 스키마가 강제하지 않는 규칙.
 * 오류가 있으면 적재하지 않고, 원천에 없는 값(좌표·거치대수 null)은 경고 또는 통과다.
 */
class MasterValidatorTest {

    private static final BusStopRow STOP = new BusStopRow("111000012", "구파발역입구", 37.6366, 126.9188);
    private static final BusRouteRow ROUTE = new BusRouteRow("100100026", "147");
    private static final BikeStationRow BIKE = new BikeStationRow("ST-4", "망원역 1번출구 앞", 37.5556, 126.9106, 15);

    @Test
    @DisplayName("정상 데이터는 오류·경고가 없다")
    void okData() {
        ValidationReport bus = MasterValidator.validateBus(List.of(STOP), List.of(ROUTE));
        ValidationReport bike = MasterValidator.validateBike(List.of(BIKE));

        assertTrue(bus.ok());
        assertTrue(bus.warnings().isEmpty());
        assertTrue(bike.ok());
        assertTrue(bike.warnings().isEmpty());
    }

    @Test
    @DisplayName("같은 키가 두 번이면 오류 — stop_id·route_id·rental_id 모두")
    void duplicateKeysAreErrors() {
        ValidationReport bus = MasterValidator.validateBus(List.of(STOP, STOP), List.of(ROUTE, ROUTE));
        ValidationReport bike = MasterValidator.validateBike(List.of(BIKE, BIKE));

        assertEquals(2, bus.errors().size());
        assertEquals(1, bike.errors().size());
    }

    @Test
    @DisplayName("좌표가 수도권 범위 밖이면 오류(열이 뒤바뀐 파싱), 좌표 없음은 경고")
    void coordinateRangeAndMissing() {
        ValidationReport bus = MasterValidator.validateBus(List.of(
                new BusStopRow("1", "뒤바뀜", 126.9188, 37.6366),
                new BusStopRow("2", "좌표없음", null, null)), List.of());

        assertEquals(1, bus.errors().size());
        assertEquals(1, bus.warnings().size());
        assertTrue(bus.warnings().get(0).startsWith("좌표 없음"));
    }

    @Test
    @DisplayName("이름이 비어 있거나 길이 한도(정류소·대여소 100자, 노선 50자)를 넘으면 오류")
    void nameBlankOrTooLong() {
        String long101 = "가".repeat(101);
        String long51 = "나".repeat(51);
        ValidationReport bus = MasterValidator.validateBus(
                List.of(new BusStopRow("1", " ", 37.5, 127.0), new BusStopRow("2", long101, 37.5, 127.0)),
                List.of(new BusRouteRow("r1", ""), new BusRouteRow("r2", long51)));
        ValidationReport bike = MasterValidator.validateBike(List.of(new BikeStationRow("ST-1", long101, 37.5, 127.0, 1)));

        assertEquals(4, bus.errors().size());
        assertEquals(1, bike.errors().size());
    }

    @Test
    @DisplayName("거치대수가 음수면 오류, null 은 경고 없이 통과 — 원천에 없는 값은 비워 둔다")
    void dockCount() {
        ValidationReport bike = MasterValidator.validateBike(List.of(
                new BikeStationRow("ST-1", "음수", 37.5, 127.0, -1),
                new BikeStationRow("ST-2", "없음", 37.5, 127.0, null)));

        assertEquals(1, bike.errors().size());
        assertTrue(bike.warnings().isEmpty());
    }

    @Test
    @DisplayName("키가 비어 있으면 오류")
    void blankKey() {
        ValidationReport bus = MasterValidator.validateBus(List.of(new BusStopRow("", "이름", 37.5, 127.0)), List.of());

        assertEquals(1, bus.errors().size());
    }
}
