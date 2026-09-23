package com.ssafy.s15p21a104.load.bikepreddaily;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.ssafy.s15p21a104.load.bikepred.BikePredProperties;
import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 날짜축 예측 원천 선택 (S15P21A104-309).
 *
 * <p>기본 경로가 avg 산출물 폴더와 <b>달라야 한다.</b> 두 산출물의 파일명 규칙이 같아서 한 폴더에 섞이면
 * avg 로더가 파일명 최신으로 lightgbm 파일을 집어 적재가 깨진다.
 */
class BikePredDailyPropertiesTest {

    @Test
    @DisplayName("309-R1: csv 원천은 설정한 경로로 파일 원천을 만든다")
    void r1_csv() {
        Path dir = Path.of("/ai-data/BIKE/serving-daily");
        var props = new BikePredDailyProperties("csv", dir);

        assertInstanceOf(CsvBikeStockPredDailySource.class, props.toSource());
        assertEquals(dir, props.path());
    }

    @Test
    @DisplayName("309-R2: 비우면 csv · 기본 경로 — 기본 경로는 avg 폴더와 다르다")
    void r2_기본값() {
        var props = new BikePredDailyProperties(null, null);

        assertEquals("csv", props.source());
        assertEquals(Path.of(BikePredDailyProperties.DEFAULT_CSV_PATH), props.path());
        assertNotEquals(Path.of(BikePredProperties.DEFAULT_CSV_PATH), props.path());
    }

    @Test
    @DisplayName("309-R3: 모르는 원천은 멈춘다")
    void r3_모르는_원천() {
        assertThrows(IllegalArgumentException.class, () -> new BikePredDailyProperties("api", null));
    }
}
