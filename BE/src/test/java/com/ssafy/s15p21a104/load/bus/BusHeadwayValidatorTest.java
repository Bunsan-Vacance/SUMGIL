package com.ssafy.s15p21a104.load.bus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.MasterValidator;
import com.ssafy.s15p21a104.load.ValidationReport;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 배차간격 적재 전 검증.
 * <p>
 * <b>마스터에 없는 노선은 오류다.</b> 재고 예측(bike_stock_pred)과 반대인데, 이쪽은 기존 {@code bus_route} 행을
 * <b>갱신</b>하는 적재라 대상이 없으면 갱신될 것도 없기 때문이다. 수집 CSV 는 이미 마스터 노선만 남기고 잘라 두므로
 * 여기서 걸리면 CSV 생성 단계가 잘못된 것이다.
 */
class BusHeadwayValidatorTest {

    private static final Set<String> MASTER = Set.of("123000010", "100100587");

    @Test
    @DisplayName("정상 데이터는 오류·경고가 없다")
    void okData() {
        ValidationReport report = MasterValidator.validateBusHeadway(
                List.of(new BusHeadwayRow("123000010", 10), new BusHeadwayRow("100100587", null)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
        assertTrue(report.warnings().isEmpty(), String.valueOf(report.warnings()));
    }

    @Test
    @DisplayName("같은 노선이 두 번이면 오류 — 어느 값을 쓸지 정해지지 않는다")
    void duplicateRouteIsError() {
        ValidationReport report = MasterValidator.validateBusHeadway(
                List.of(new BusHeadwayRow("123000010", 10), new BusHeadwayRow("123000010", 12)), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("배차간격이 0 이하이면 오류 — 0 은 파서가 NULL 로 바꿔야 한다")
    void nonPositiveHeadwayIsError() {
        ValidationReport report = MasterValidator.validateBusHeadway(List.of(
                new BusHeadwayRow("123000010", 0),
                new BusHeadwayRow("100100587", -5)), MASTER);

        assertEquals(2, report.errors().size());
    }

    @Test
    @DisplayName("배차간격이 비현실적으로 크면 오류 — 원천 단위가 초로 바뀐 것이다")
    void hugeHeadwayIsError() {
        ValidationReport report = MasterValidator.validateBusHeadway(
                List.of(new BusHeadwayRow("123000010", 1441)), MASTER);

        assertEquals(1, report.errors().size());
    }

    @Test
    @DisplayName("NULL 은 오류가 아니다 — 원천이 값을 주지 않은 노선이다")
    void nullHeadwayIsOk() {
        ValidationReport report = MasterValidator.validateBusHeadway(
                List.of(new BusHeadwayRow("123000010", null)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
    }

    @Test
    @DisplayName("마스터에 없는 노선은 오류다 — 갱신할 대상이 없다")
    void unknownRouteIsError() {
        ValidationReport report = MasterValidator.validateBusHeadway(
                List.of(new BusHeadwayRow("999999999", 10)), MASTER);

        assertEquals(1, report.errors().size());
        assertTrue(report.errors().get(0).contains("999999999"), report.errors().get(0));
    }

    @Test
    @DisplayName("마스터가 비어 있으면 대조를 건너뛴다 — dry-run 은 DB 를 읽지 않는다")
    void emptyMasterSkipsCrossCheck() {
        ValidationReport report = MasterValidator.validateBusHeadway(
                List.of(new BusHeadwayRow("999999999", 10)), Set.of());

        assertTrue(report.ok(), String.valueOf(report.errors()));
    }

    @Test
    @DisplayName("값이 있는 노선이 하나도 없으면 경고한다 — 수집이 실패했을 수 있다")
    void warnsWhenNothingHasHeadway() {
        ValidationReport report = MasterValidator.validateBusHeadway(
                List.of(new BusHeadwayRow("123000010", null), new BusHeadwayRow("100100587", null)), MASTER);

        assertTrue(report.ok(), String.valueOf(report.errors()));
        assertEquals(1, report.warnings().size());
    }
}
