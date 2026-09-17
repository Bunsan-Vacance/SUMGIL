package com.ssafy.s15p21a104.load.bikepred;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.MasterValidator;
import com.ssafy.s15p21a104.load.ValidationReport;
import java.math.BigDecimal;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * bike_stock_pred 적재 전 검증. 스키마가 강제하지 않는 규칙만 본다.
 * <p>
 * <b>마스터에 없는 대여소는 오류가 아니라 경고다.</b> 혼잡도(congestion)는 적재되지 않은 역을 오류로 막지만
 * 여기서는 그럴 수 없다 — 예측 표가 대여소 마스터보다 최근이라 신설 대여소가 정상적으로 섞이고,
 * 그걸 막으면 그 대여소의 예측을 통째로 버리게 된다. 마스터를 갱신해야 한다는 신호로 남긴다.
 */
class BikeStockPredValidatorTest {

    private static final Set<String> MASTER = Set.of("ST-10", "ST-11");

    private static BikeStockPredRow row(String rentalId, int dow, int slot,
                                        String expBikes, String pEmpty, String pFull, String source) {
        return new BikeStockPredRow(rentalId, dow, slot, new BigDecimal(expBikes),
                new BigDecimal(pEmpty), new BigDecimal(pFull), source, "observed_avg");
    }

    private static BikeStockPredRow ok(String rentalId, int dow, int slot) {
        return row(rentalId, dow, slot, "4.4", "0.273", "0.138", "avg");
    }

    @Test
    @DisplayName("정상 데이터는 오류·경고가 없다")
    void okData() {
        ValidationReport report = MasterValidator.validateBikeStockPred(
                List.of(ok("ST-10", 0, 0), ok("ST-11", 2, 47)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
        assertTrue(report.warnings().isEmpty(), String.valueOf(report.warnings()));
    }

    @Test
    @DisplayName("같은 (대여소, 요일, 슬롯) 이 두 번이면 오류 — 기본키가 깨진다")
    void duplicateKeyIsError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(
                List.of(ok("ST-10", 0, 0), ok("ST-10", 0, 0)), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("요일 유형이 0~2 밖이면 오류")
    void dowTypeOutOfRangeIsError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(
                List.of(ok("ST-10", 3, 0)), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("시간 슬롯이 0~47 밖이면 오류")
    void timeSlotOutOfRangeIsError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(
                List.of(ok("ST-10", 0, 48)), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("확률이 0~1 밖이면 오류 — 원천 단위가 % 로 바뀐 것이다")
    void probabilityOutOfRangeIsError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(List.of(
                row("ST-10", 0, 0, "4.4", "1.200", "0.138", "avg"),
                row("ST-10", 0, 1, "4.4", "0.273", "-0.100", "avg")), MASTER);

        assertEquals(2, report.errors().size());
    }

    @Test
    @DisplayName("예상 대수가 음수면 오류")
    void negativeExpBikesIsError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(
                List.of(row("ST-10", 0, 0, "-1.0", "0.273", "0.138", "avg")), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("source 가 비었거나 열 폭(16자)을 넘으면 오류")
    void badSourceIsError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(List.of(
                row("ST-10", 0, 0, "4.4", "0.273", "0.138", ""),
                row("ST-10", 0, 1, "4.4", "0.273", "0.138", "a".repeat(17))), MASTER);

        assertEquals(2, report.errors().size());
    }

    @Test
    @DisplayName("prediction_source 가 열 폭(32자)을 넘으면 오류 — 실제 값이 23자라 여유가 크지 않다")
    void tooLongPredictionSourceIsError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(List.of(
                new BikeStockPredRow("ST-10", 0, 0, new BigDecimal("4.4"), new BigDecimal("0.273"),
                        new BigDecimal("0.138"), "avg", "a".repeat(33))), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("prediction_source 가 없어도 오류가 아니다 — 옛 산출물에는 그 열이 없다")
    void nullPredictionSourceIsOk() {
        ValidationReport report = MasterValidator.validateBikeStockPred(List.of(
                new BikeStockPredRow("ST-10", 0, 0, new BigDecimal("4.4"), new BigDecimal("0.273"),
                        new BigDecimal("0.138"), "avg", null)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
    }

    @Test
    @DisplayName("마스터에 없는 대여소는 오류가 아니라 경고 한 줄이다 — 건수와 예시를 담는다")
    void unknownRentalIdIsWarningNotError() {
        ValidationReport report = MasterValidator.validateBikeStockPred(List.of(
                ok("ST-10", 0, 0), ok("ST-9999", 0, 0), ok("ST-9999", 0, 1)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
        assertEquals(1, report.warnings().size());
        assertTrue(report.warnings().get(0).contains("ST-9999"), report.warnings().get(0));
    }

    @Test
    @DisplayName("마스터가 비어 있으면 대조를 건너뛴다 — dry-run 은 DB 를 읽지 않는다")
    void emptyMasterSkipsCrossCheck() {
        ValidationReport report = MasterValidator.validateBikeStockPred(
                List.of(ok("ST-9999", 0, 0)), Set.of());

        assertTrue(report.ok(), String.valueOf(report.errors()));
        assertTrue(report.warnings().isEmpty(), String.valueOf(report.warnings()));
    }
}
