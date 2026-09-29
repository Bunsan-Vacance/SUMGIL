package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 후보 파생 메트릭 테스트(5부 C6) — 탐색이 아니라 후처리용 파생값.
 */
class CandidateMetricsTest {

    private static RouteLegResponse leg(TravelMode mode, double minutes) {
        return new RouteLegResponse(mode, "n1", "n1", 37.5, 127.0, "n2", "n2", 37.5, 127.1,
                mode == TravelMode.TRANSFER ? null : mode.name(), minutes, null, "unavailable",
                null, null, null);
    }

    @Test
    @DisplayName("M1: 도보·자전거 분과 대여 행위 수(BIKE leg 수), 환승 수를 센다")
    void m1_합산() {
        CandidateMetrics metrics = CandidateMetrics.of(List.of(
                leg(TravelMode.WALK, 3.0),
                leg(TravelMode.BIKE, 4.0),
                leg(TravelMode.BUS, 20.0),
                leg(TravelMode.TRANSFER, 3.0),
                leg(TravelMode.BIKE, 2.5),
                leg(TravelMode.WALK, 1.0)));

        assertEquals(4.0, metrics.walkMinutes(), 0.001);
        assertEquals(6.5, metrics.bikeMinutes(), 0.001);
        assertEquals(2, metrics.rentalActs());
        assertEquals(1, metrics.transfers());
    }

    @Test
    @DisplayName("M2: 대중교통만 있으면 도보·자전거·대여는 0이다")
    void m2_대중교통만() {
        CandidateMetrics metrics = CandidateMetrics.of(List.of(
                leg(TravelMode.SUBWAY, 18.0),
                leg(TravelMode.TRANSFER, 3.0),
                leg(TravelMode.BUS, 10.0)));

        assertEquals(0, metrics.walkMinutes(), 0.001);
        assertEquals(0, metrics.bikeMinutes(), 0.001);
        assertEquals(0, metrics.rentalActs());
        assertEquals(1, metrics.transfers());
    }
}
