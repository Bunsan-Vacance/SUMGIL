package com.ssafy.s15p21a104.domain.route.bike;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 자전거 사용 위치 규칙 테스트(2026-09-23) — BIKE 런은 첫 탑승 전 1회·마지막 하차 후 1회만,
 * 탑승 사이(중간)는 0회. 접근·이탈 안에서도 체인(2런)은 금지한다. 무탑승 경로는 1런까지.
 */
class BikeUsePolicyTest {

    @Test
    @DisplayName("P1: 접근 1런만 있으면 허용")
    void p1_접근만() {
        assertTrue(BikeUsePolicy.allowedPath(List.of(
                walk("O", "R1", 60), bike("R1", "S", 240), bus("S", "D", "B1", 100))));
    }

    @Test
    @DisplayName("P2: 이탈 1런만 있으면 허용")
    void p2_이탈만() {
        assertTrue(BikeUsePolicy.allowedPath(List.of(
                bus("O", "S", "B1", 100), bike("S", "R1", 240), walk("R1", "D", 60))));
    }

    @Test
    @DisplayName("P3: 접근 1런 + 이탈 1런은 허용(시작·끝 모두)")
    void p3_양끝() {
        assertTrue(BikeUsePolicy.allowedPath(List.of(
                bike("O", "R1", 120), walk("R1", "S", 60), bus("S", "D", "B1", 100),
                bike("D", "R2", 120), walk("R2", "E", 60))));
    }

    @Test
    @DisplayName("P4: 탑승 사이 BIKE 런은 금지")
    void p4_중간() {
        assertFalse(BikeUsePolicy.allowedPath(List.of(
                bus("O", "S", "B1", 100), bike("S", "X", 120), bus("X", "D", "B2", 100))));
    }

    @Test
    @DisplayName("P5: 접근 2런(대여소 체인)은 금지")
    void p5_접근체인() {
        assertFalse(BikeUsePolicy.allowedPath(List.of(
                bike("O", "R1", 120), walk("R1", "R2", 60), bike("R2", "S", 120),
                bus("S", "D", "B1", 100))));
    }

    @Test
    @DisplayName("P6: 이탈 2런(대여소 체인)은 금지")
    void p6_이탈체인() {
        assertFalse(BikeUsePolicy.allowedPath(List.of(
                bus("O", "S", "B1", 100), bike("S", "R1", 120), walk("R1", "R2", 60),
                bike("R2", "D", 120))));
    }

    @Test
    @DisplayName("P7: 무탑승 1런은 허용(직행 자전거)")
    void p7_무탑승1런() {
        assertTrue(BikeUsePolicy.allowedPath(List.of(
                bike("O", "R1", 120), bike("R1", "D", 120))));
    }

    @Test
    @DisplayName("P8: 무탑승 2런은 금지")
    void p8_무탑승2런() {
        assertFalse(BikeUsePolicy.allowedPath(List.of(
                bike("O", "R1", 120), walk("R1", "R2", 60), bike("R2", "D", 120))));
    }

    @Test
    @DisplayName("P9: 2km(480초) 초과 런은 금지")
    void p9_상한초과() {
        assertFalse(BikeUsePolicy.allowedPath(List.of(
                bike("O", "R1", 250), bike("R1", "D", 250))));
    }

    @Test
    @DisplayName("P10: 자전거가 아예 없으면 허용")
    void p10_자전거없음() {
        assertTrue(BikeUsePolicy.allowedPath(List.of(
                walk("O", "S", 60), bus("S", "D", "B1", 100))));
    }

    @Test
    @DisplayName("P11: 빈 경로는 허용")
    void p11_빈경로() {
        assertTrue(BikeUsePolicy.allowedPath(List.<Edge>of()));
    }
}
