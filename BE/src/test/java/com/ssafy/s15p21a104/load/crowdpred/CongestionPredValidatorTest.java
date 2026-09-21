package com.ssafy.s15p21a104.load.crowdpred;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.load.MasterValidator;
import com.ssafy.s15p21a104.load.ValidationReport;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 혼잡도 예측 적재 전 검증 (S15P21A104-305).
 *
 * <p>172(재고 예측)와 다른 점: <b>마스터에 없는 역·노선은 오류다.</b> 재고 예측은 표가 대여소
 * 마스터보다 최근이라 신설 대여소가 정상적으로 섞였지만, 혼잡도 예측은 우리가 이미 가진 역
 * 안에서만 나온다 — 없다는 것은 매핑이 깨졌다는 뜻이다.
 */
class CongestionPredValidatorTest {

    private static final LocalDate DATE = LocalDate.of(2026, 9, 20);
    private static final Set<String> STATIONS = Set.of("150", "151", "218");
    private static final Set<String> LINES = Set.of("1001", "1009");

    private static CongestionPredRow row(String from, String to, String lineId, String direction,
                                         int slot, String level, String status, String source, String version) {
        return new CongestionPredRow(DATE, from, to, lineId, direction, slot,
                level == null ? null : new BigDecimal(level), status, source, version);
    }

    private static CongestionPredRow ok() {
        return row("150", "151", "1001", "하선", 0, "1.7", "ok", "model", "lightgbm:x");
    }

    private static ValidationReport validate(List<CongestionPredRow> rows) {
        return MasterValidator.validateCongestionPred(rows, STATIONS, LINES, 128);
    }

    @Test
    @DisplayName("305-V1: 정상 행은 오류·경고가 없다")
    void v1_정상() {
        ValidationReport r = validate(List.of(ok()));

        assertTrue(r.errors().isEmpty(), () -> "" + r.errors());
        assertTrue(r.warnings().isEmpty(), () -> "" + r.warnings());
    }

    @Test
    @DisplayName("305-V2: 같은 키가 두 번이면 오류 — 표의 기본키와 같은 조합이다")
    void v2_키_중복() {
        ValidationReport r = validate(List.of(ok(), ok()));

        assertEquals(1, r.errors().size(), () -> "" + r.errors());
        assertTrue(r.errors().get(0).contains("두 번"), r.errors().get(0));
    }

    @Test
    @DisplayName("305-V3: to 만 다르면 중복이 아니다 — 강동처럼 한 역에서 여러 링크가 나간다")
    void v3_강동_이중_링크() {
        ValidationReport r = validate(List.of(
                row("150", "151", "1001", "하선", 0, "1.0", "ok", "model", "v"),
                row("150", "218", "1001", "하선", 0, "2.0", "ok", "model", "v")));

        assertTrue(r.errors().isEmpty(), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V4: 슬롯이 0~47 밖이면 오류")
    void v4_슬롯_범위() {
        ValidationReport r = validate(List.of(
                row("150", "151", "1001", "하선", 48, "1.0", "ok", "model", "v")));

        assertTrue(r.errors().stream().anyMatch(e -> e.contains("0~47")), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V5: 방향이 4종 밖이면 오류 — 오타가 조용히 들어가면 조회가 안 된다")
    void v5_방향() {
        ValidationReport r = validate(List.of(
                row("150", "151", "1001", "윗선", 0, "1.0", "ok", "model", "v")));

        assertTrue(r.errors().stream().anyMatch(e -> e.contains("방향")), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V6: level 은 null 이어도 되지만 음수는 오류")
    void v6_level() {
        ValidationReport nullOk = validate(List.of(
                row("150", "151", "1001", "하선", 0, null, "no_calibration", "model", "v")));
        assertTrue(nullOk.errors().isEmpty(), () -> "" + nullOk.errors());

        ValidationReport negative = validate(List.of(
                row("150", "151", "1001", "하선", 0, "-1.0", "ok", "model", "v")));
        assertTrue(negative.errors().stream().anyMatch(e -> e.contains("음수")), () -> "" + negative.errors());
    }

    @Test
    @DisplayName("305-V7: level 이 100 을 넘어도 통과한다 — 상한이 없다")
    void v7_100_초과() {
        ValidationReport r = validate(List.of(
                row("150", "151", "1001", "하선", 0, "164.4", "ok", "model", "v")));

        assertTrue(r.errors().isEmpty(), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V8: predictor_version 이 한도를 넘으면 오류 — DB 가 중간에 끊기기 전에 막는다")
    void v8_버전_길이() {
        ValidationReport r = MasterValidator.validateCongestionPred(
                List.of(row("150", "151", "1001", "하선", 0, "1.0", "ok", "model", "x".repeat(129))),
                STATIONS, LINES, 128);

        assertTrue(r.errors().stream().anyMatch(e -> e.contains("predictor_version")), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V9: data_status·pred_source 가 32자를 넘으면 오류")
    void v9_열_길이() {
        ValidationReport r = validate(List.of(
                row("150", "151", "1001", "하선", 0, "1.0", "s".repeat(33), "model", "v"),
                row("150", "151", "1001", "상선", 0, "1.0", "ok", "p".repeat(33), "v")));

        assertEquals(2, r.errors().size(), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V10: 마스터에 없는 역·노선은 오류 — 매핑이 깨진 것이다")
    void v10_마스터_없음() {
        ValidationReport r = validate(List.of(
                row("999", "151", "1001", "하선", 0, "1.0", "ok", "model", "v"),
                row("150", "151", "9999", "하선", 1, "1.0", "ok", "model", "v")));

        assertTrue(r.errors().stream().anyMatch(e -> e.contains("999")), () -> "" + r.errors());
        assertTrue(r.errors().stream().anyMatch(e -> e.contains("9999")), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V11: 마스터 집합이 비면 대조를 건너뛴다 — dry-run 은 DB 를 읽지 않는다")
    void v11_dry_run() {
        ValidationReport r = MasterValidator.validateCongestionPred(
                List.of(row("999", "888", "9999", "하선", 0, "1.0", "ok", "model", "v")),
                Set.of(), Set.of(), 128);

        assertTrue(r.errors().isEmpty(), () -> "" + r.errors());
    }

    @Test
    @DisplayName("305-V12: 실물 샘플 278행이 검증을 통과한다")
    void v12_실물_샘플() {
        var parser = new CongestionPredParser(SampleFixtures.codes());
        SampleFixtures.sampleRows().forEach(parser::accept);
        List<CongestionPredRow> rows = parser.finish().rows();

        ValidationReport r = MasterValidator.validateCongestionPred(
                rows, SampleFixtures.stationIds(), SampleFixtures.lineIds(), 128);

        assertEquals(278, rows.size());
        assertTrue(r.errors().isEmpty(), () -> "" + r.errors());
    }
}
