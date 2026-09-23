package com.ssafy.s15p21a104.load.bikepreddaily;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.MasterValidator;
import com.ssafy.s15p21a104.load.ValidationReport;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * bike_stock_pred_daily 적재 전 검증 (S15P21A104-309). 기존 재고 예측 검증과 같은 규칙에
 * 키만 (대여소, <b>날짜</b>, 슬롯) 이다. 마스터에 없는 대여소는 같은 이유로 경고다.
 */
class BikeStockPredDailyValidatorTest {

    private static final Set<String> MASTER = Set.of("ST-10", "ST-11");
    private static final LocalDate D = LocalDate.of(2026, 9, 23);
    private static final OffsetDateTime AT = OffsetDateTime.parse("2026-09-23T00:30:00+00:00");

    private static BikeStockPredDailyRow row(String rentalId, LocalDate date, int slot, String pEmpty) {
        return new BikeStockPredDailyRow(rentalId, date, slot, new BigDecimal("4.4"),
                new BigDecimal(pEmpty), new BigDecimal("0.138"), "model", null, AT);
    }

    private static BikeStockPredDailyRow ok(String rentalId, LocalDate date, int slot) {
        return row(rentalId, date, slot, "0.273");
    }

    @Test
    @DisplayName("309-V1: 정상 데이터는 오류·경고가 없다 — 같은 대여소·슬롯이라도 날짜가 다르면 다른 행이다")
    void v1_정상() {
        ValidationReport report = MasterValidator.validateBikeStockPredDaily(
                List.of(ok("ST-10", D, 0), ok("ST-10", D.plusDays(1), 0), ok("ST-11", D, 47)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
        assertTrue(report.warnings().isEmpty(), String.valueOf(report.warnings()));
    }

    @Test
    @DisplayName("309-V2: 같은 (대여소, 날짜, 슬롯) 이 두 번이면 오류 — 기본키가 깨진다")
    void v2_키_중복() {
        ValidationReport report = MasterValidator.validateBikeStockPredDaily(
                List.of(ok("ST-10", D, 0), ok("ST-10", D, 0)), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("309-V3: 슬롯이 0~47 밖이거나 확률이 0~1 밖이면 오류")
    void v3_범위() {
        ValidationReport report = MasterValidator.validateBikeStockPredDaily(
                List.of(ok("ST-10", D, 48), row("ST-10", D, 1, "1.200")), MASTER);

        assertEquals(2, report.errors().size());
    }

    @Test
    @DisplayName("309-V4: 마스터에 없는 대여소는 경고만 하고 적재한다")
    void v4_마스터_밖() {
        ValidationReport report = MasterValidator.validateBikeStockPredDaily(
                List.of(ok("ST-99", D, 0)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
        assertEquals(1, report.warnings().size());
    }
}
