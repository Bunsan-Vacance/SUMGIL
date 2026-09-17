package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 노선별 표정속도 표(conf/line-speeds.csv). 거리만 있는 구간의 소요시간 추정에 쓴다.
 * 표에 없는 노선은 기본값(load.avg-speed-mps, 9.2)으로 떨어진다 — GTX 급행과 경전철은 2~3배 다르므로 노선별 값이 필요하다.
 */
class LineSpeedsTest {

    @Test
    @DisplayName("표에 있는 노선은 그 값, 없는 노선은 기본값")
    void lookupWithFallback() {
        LineSpeeds speeds = LineSpeeds.from(List.of(
                Map.of("line_id", "1081", "mps", "19.4", "근거", "코레일 보도자료 판교~여주 48분"),
                Map.of("line_id", "1094", "mps", "7.8")), 9.2);

        assertEquals(19.4, speeds.speedOf("1081"));
        assertEquals(7.8, speeds.speedOf("1094"));
        assertEquals(9.2, speeds.speedOf("1063"));
        assertTrue(speeds.isDefault("1063"));
        assertFalse(speeds.isDefault("1081"));
    }

    @Test
    @DisplayName("속도가 비어 있거나 0 이하이거나 숫자가 아니면 표를 만들지 않는다 — 조용히 기본값으로 넘어가지 않게")
    void rejectsInvalidRows() {
        assertThrows(IllegalArgumentException.class, () -> LineSpeeds.from(List.of(Map.of("line_id", "1081", "mps", "0")), 9.2));
        assertThrows(IllegalArgumentException.class, () -> LineSpeeds.from(List.of(Map.of("line_id", "1081", "mps", "빠름")), 9.2));
        assertThrows(IllegalArgumentException.class, () -> LineSpeeds.from(List.of(Map.of("line_id", "", "mps", "10")), 9.2));
    }

    @Test
    @DisplayName("같은 노선이 두 번 나오면 표가 잘못된 것이다")
    void rejectsDuplicateLine() {
        assertThrows(IllegalArgumentException.class, () -> LineSpeeds.from(List.of(
                Map.of("line_id", "1081", "mps", "19.4"), Map.of("line_id", "1081", "mps", "20")), 9.2));
    }
}
