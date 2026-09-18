package com.ssafy.s15p21a104.domain.congestion.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-158(통지 05 S-1): 방향 판정. 2호선 지선은 예외표 수신 전까지 결측 취급.
 */
class SubwayDirectionResolverTest {

    @Test
    @DisplayName("일반 노선은 역번호 오름차순이면 상선")
    void 일반노선_오름차순_상선() {
        Optional<String> direction = SubwayDirectionResolver.resolve("221", "222", "1001");

        assertEquals(Optional.of("상선"), direction);
    }

    @Test
    @DisplayName("일반 노선은 역번호 내림차순이면 하선")
    void 일반노선_내림차순_하선() {
        Optional<String> direction = SubwayDirectionResolver.resolve("222", "221", "1001");

        assertEquals(Optional.of("하선"), direction);
    }

    @Test
    @DisplayName("2호선 본선은 오름차순이면 내선, 내림차순이면 외선")
    void 이호선_본선_내선_외선() {
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("221", "222", "1002"));
        assertEquals(Optional.of("외선"), SubwayDirectionResolver.resolve("222", "221", "1002"));
    }

    @Test
    @DisplayName("성수지선 역이 끼면 2호선이라도 판정을 보류한다(빈 값)")
    void 성수지선_보류() {
        // 성수(211) - 용답(244)
        Optional<String> direction = SubwayDirectionResolver.resolve("211", "244", "1002");

        assertTrue(direction.isEmpty());
    }

    @Test
    @DisplayName("신정지선 역이 끼면 2호선이라도 판정을 보류한다(빈 값)")
    void 신정지선_보류() {
        // 까치산(200) - 신정네거리(249)
        Optional<String> direction = SubwayDirectionResolver.resolve("200", "249", "1002");

        assertTrue(direction.isEmpty());
    }

    @Test
    @DisplayName("역번호가 숫자가 아니면(수도권 확장 역 등) 판정을 보류한다")
    void 숫자아닌_역번호_보류() {
        Optional<String> direction = SubwayDirectionResolver.resolve("D004", "A01", "1113");

        assertTrue(direction.isEmpty());
    }
}
