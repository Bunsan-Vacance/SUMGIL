package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 원천마다 다른 역명 표기를 하나의 물리 역 이름으로 맞춘다.
 * 정본은 서울교통공사 좌표 파일·실시간 API 표기("서울", "총신대입구", "신내")다.
 */
class StationNameNormalizerTest {

    private final StationNameNormalizer normalizer = new StationNameNormalizer(Map.of(
            "서울역", "서울",
            "신내역", "신내",
            "이수", "총신대입구",
            "뚝섬유원지", "자양"));

    @Test
    @DisplayName("괄호 부기를 제거한다 — 이촌(국립중앙박물관) → 이촌")
    void stripsParentheses() {
        assertEquals("이촌", normalizer.normalize("이촌(국립중앙박물관)"));
        assertEquals("총신대입구", normalizer.normalize("총신대입구(이수)"));
    }

    @Test
    @DisplayName("앞뒤 공백을 제거한다")
    void trims() {
        assertEquals("시청", normalizer.normalize("  시청 "));
    }

    @Test
    @DisplayName("별칭 표를 적용한다 — 서울역 → 서울, 이수 → 총신대입구")
    void appliesAliases() {
        assertEquals("서울", normalizer.normalize("서울역"));
        assertEquals("신내", normalizer.normalize("신내역"));
        assertEquals("총신대입구", normalizer.normalize("이수"));
        // 2024년 역명 변경: 뚝섬유원지 → 자양(뚝섬한강공원). 최신 공식 이름을 정본으로 둔다
        assertEquals("자양", normalizer.normalize("뚝섬유원지"));
    }

    @Test
    @DisplayName("괄호 제거 후에도 별칭을 적용한다 — 서울역(1호선) → 서울")
    void aliasAfterStrip() {
        assertEquals("서울", normalizer.normalize("서울역(1호선)"));
    }

    @Test
    @DisplayName("별칭에 없는 이름은 그대로 둔다 — '역'으로 끝나도 자르지 않는다")
    void leavesUnknownNamesAlone() {
        assertEquals("역삼", normalizer.normalize("역삼"));
        assertEquals("동대문역사문화공원", normalizer.normalize("동대문역사문화공원"));
    }

    @Test
    @DisplayName("normalizeStation: 끝의 '역'까지 뗀다 — KTDB 노드·표준데이터처럼 역명에 '역'을 붙이는 원천용. 청량리역 → 청량리, 서울역(경의) → 서울")
    void normalizeStationStripsSuffix() {
        assertEquals("청량리", normalizer.normalizeStation("청량리역"));
        assertEquals("석남", normalizer.normalizeStation("석남(거북시장)역"));
        assertEquals("서울", normalizer.normalizeStation("서울역(경의)"));
        assertEquals("역촌", normalizer.normalizeStation("역촌역"));
        assertEquals("역삼", normalizer.normalizeStation("역삼"));
        assertEquals("역", normalizer.normalizeStation("역"));
    }
}
