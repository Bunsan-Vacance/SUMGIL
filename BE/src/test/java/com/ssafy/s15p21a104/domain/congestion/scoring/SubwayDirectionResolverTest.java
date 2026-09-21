package com.ssafy.s15p21a104.domain.congestion.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-158(통지 05 S-1): 방향 판정. 실측 혼잡도 CSV로 정정됨
 * (이원빈 회신 `TO_ROUTE-subway-direction-01.md`, 2026-09-21).
 */
class SubwayDirectionResolverTest {

    @Test
    @DisplayName("1호선은 역번호 오름차순이면 상선")
    void 일호선_오름차순_상선() {
        assertEquals(Optional.of("상선"), SubwayDirectionResolver.resolve("221", "222", "1001"));
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("222", "221", "1001"));
    }

    @Test
    @DisplayName("2호선 본선은 오름차순이면 내선, 내림차순이면 외선")
    void 이호선_본선_내선_외선() {
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("221", "222", "1002"));
        assertEquals(Optional.of("외선"), SubwayDirectionResolver.resolve("222", "221", "1002"));
    }

    @Test
    @DisplayName("3~8호선은 역번호 오름차순이면 하선(1호선과 반대)")
    void 삼호선에서_팔호선_오름차순_하선() {
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("309", "310", "1003"));
        assertEquals(Optional.of("상선"), SubwayDirectionResolver.resolve("310", "309", "1003"));
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("2511", "2512", "1005"));
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("2810", "2811", "1008"));
    }

    @Test
    @DisplayName("2호선 지선 내부 링크는 더 이상 통째로 결측 처리되지 않는다(이전 버그 수정)")
    void 지선_내부_링크는_정상_판정() {
        // 성수지선: 성수(211) → 용답(244), 둘 다 지선 역이지만 반전 링크는 아니다.
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("211", "244", "1002"));
        // 신정지선: 신도림(234) → 도림천(247).
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("234", "247", "1002"));
    }

    @Test
    @DisplayName("2호선 본선 구간(문래 포함)은 지선으로 오인돼 결측 처리되지 않는다(이전 버그 수정)")
    void 문래가_낀_본선_구간도_정상_판정() {
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("234", "235", "1002"));
    }

    @Test
    @DisplayName("용두↔신설동(2호선 성수지선 경계)은 반전 링크라 판정을 보류한다")
    void 용두_신설동_경계_보류() {
        assertTrue(SubwayDirectionResolver.resolve("250", "156", "1002").isEmpty());
        assertTrue(SubwayDirectionResolver.resolve("156", "250", "1002").isEmpty());
    }

    @Test
    @DisplayName("신정네거리↔까치산(2호선 신정지선 경계)은 반전 링크라 판정을 보류한다")
    void 신정네거리_까치산_경계_보류() {
        assertTrue(SubwayDirectionResolver.resolve("249", "200", "1002").isEmpty());
        assertTrue(SubwayDirectionResolver.resolve("200", "249", "1002").isEmpty());
    }

    @Test
    @DisplayName("동묘앞↔신설동(1호선, 나중 개통역)은 반전 링크라 판정을 보류한다")
    void 동묘앞_신설동_경계_보류() {
        assertTrue(SubwayDirectionResolver.resolve("159", "156", "1001").isEmpty());
        assertTrue(SubwayDirectionResolver.resolve("156", "159", "1001").isEmpty());
    }

    @Test
    @DisplayName("역번호가 숫자가 아니면(수도권 확장 역 등) 판정을 보류한다")
    void 숫자아닌_역번호_보류() {
        assertTrue(SubwayDirectionResolver.resolve("D004", "A01", "1113").isEmpty());
    }
}
