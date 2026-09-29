package com.ssafy.s15p21a104.load.bikepred;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 재고 예측 원천 선택. 티켓의 "원천 전환이 설정값 하나로 된다" 는 이 키 하나를 뜻한다.
 * <p>
 * 지금 고를 수 있는 값은 {@code csv} 뿐이다. AI 서빙 API 는 원천이 아니라 같은 산출물의 조회 창구라
 * ({@code BikeStockPredSource} javadoc) 적재 원천 후보가 아니다 — 모르는 값을 조용히 csv 로 넘기지 않고
 * 무엇이 가능한지 밝히며 멈춘다.
 */
class BikePredPropertiesTest {

    private static final Path DIR = Path.of("../AI/data/BIKE/serving");

    @Test
    @DisplayName("csv 원천은 설정한 경로로 파일 원천을 만든다")
    void csvSourceUsesConfiguredPath() {
        BikePredProperties props = new BikePredProperties("csv", DIR);

        BikeStockPredSource source = props.toSource();

        assertInstanceOf(CsvBikeStockPredSource.class, source);
        assertEquals(DIR, props.path());
    }

    @Test
    @DisplayName("원천을 비우면 csv 가 기본값이다")
    void defaultsToCsv() {
        assertEquals("csv", new BikePredProperties(null, DIR).source());
        assertEquals("csv", new BikePredProperties("  ", DIR).source());
    }

    @Test
    @DisplayName("대소문자·공백은 무시한다")
    void sourceIsCaseInsensitive() {
        assertEquals("csv", new BikePredProperties(" CSV ", DIR).source());
    }

    @Test
    @DisplayName("경로를 비우면 기본 경로를 쓴다 — 받아 둔 산출물 폴더")
    void defaultsToServingDirectory() {
        Path expected = Path.of(BikePredProperties.DEFAULT_CSV_PATH);

        assertEquals(expected, new BikePredProperties("csv", null).path());
        // yml 의 csv-path 를 값 없이 두면 빈 경로로 바인딩된다
        assertEquals(expected, new BikePredProperties("csv", Path.of("")).path());
    }

    @Test
    @DisplayName("모르는 원천은 무엇이 가능한지 밝히며 멈춘다 — 조용히 csv 로 넘기지 않는다")
    void unknownSourceFailsFast() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> new BikePredProperties("parquet", DIR));

        assertTrue(e.getMessage().contains("parquet"), e.getMessage());
        assertTrue(e.getMessage().contains("csv"), e.getMessage());
    }

    @Test
    @DisplayName("api 는 이유를 밝히며 거절한다 — 조회 창구이지 적재 원천이 아니다")
    void apiSourceIsRejectedWithReason() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> new BikePredProperties("api", DIR));

        assertTrue(e.getMessage().contains("api"), e.getMessage());
        assertTrue(e.getMessage().contains("대여소"), e.getMessage());
    }
}
