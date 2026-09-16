package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.time.OffsetDateTime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 도착예정시각 산출 (S15P21A104-224).
 *
 * <p>규칙과 비율은 2026-09-16 prod 덤프 6,500행(3회차) 실측이다.
 * <b>{@code arvlCd} 로 가르지 않는다</b> — {@code arvlCd=1}(도착) 932건 중 153건이 실제로는 {@code [N]번째 전역} 이고,
 * {@code arvlCd=99}(운행중) 중 1,807건은 오히려 {@code barvlDt} 를 가지고 있다.
 * {@code arvlMsg3 == statnNm}(열차가 지금 그 역에 있나)이 깨끗하게 갈린다.
 */
class ArrivalEtaTest {

    /** 컨슈머가 Redis 에 쓰는 시각. 가드의 기준점이다. */
    private static final OffsetDateTime NOW = OffsetDateTime.parse("2026-09-16T13:38:23+09:00");

    private static OffsetDateTime at(String kst) {
        return OffsetDateTime.parse(kst);
    }

    // ── 규칙 1: 원천이 잔여시간을 준다 (실측 38.7%) ────────────────────────────

    @Test
    @DisplayName("barvl_sec > 0 이면 recptn_dt 에 더한다")
    void 잔여시간이_있으면_더한다() {
        ArrivalEta eta = ArrivalEta.of(at("2026-09-16T13:37:43+09:00"), 150, "서초", "강남", NOW);

        assertEquals(at("2026-09-16T13:40:13+09:00"), eta.etaAt());
        assertEquals(ArrivalEta.Source.BARVL, eta.source());
    }

    // ── 규칙 2: 열차가 지금 그 역에 있다 (실측 14.4%) ──────────────────────────

    @Test
    @DisplayName("arvl_msg3 가 그 역 이름과 같으면 지금 도착한 것이다")
    void 그_역에_있으면_지금이다() {
        ArrivalEta eta = ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), 0, "강남", "강남", NOW);

        assertEquals(at("2026-09-16T13:38:05+09:00"), eta.etaAt());
        assertEquals(ArrivalEta.Source.ARRIVED, eta.source());
    }

    @Test
    @DisplayName("역 이름 앞뒤 공백은 무시하고 비교한다")
    void 역_이름_공백() {
        ArrivalEta eta = ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), 0, "  강남 ", "강남", NOW);

        assertEquals(ArrivalEta.Source.ARRIVED, eta.source());
    }

    // ── 규칙 3: 산출 불가 (실측 46.9%) ────────────────────────────────────────

    @Test
    @DisplayName("몇 정거장 전이면 산출하지 않는다 — 위치만 알고 시간은 모른다")
    void 몇_정거장_전이면_모른다() {
        ArrivalEta eta = ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), 0, "청계산입구", "강남", NOW);

        assertNull(eta.etaAt());
        assertEquals(ArrivalEta.Source.NONE, eta.source());
    }

    @Test
    @DisplayName("기준 시각이 없으면 아무것도 못 만든다")
    void 기준시각이_없으면_모른다() {
        assertEquals(ArrivalEta.Source.NONE, ArrivalEta.of(null, 150, "강남", "강남", NOW).source());
        assertNull(ArrivalEta.of(null, 150, "강남", "강남", NOW).etaAt());
    }

    @Test
    @DisplayName("잔여시간이 null 이거나 음수면 규칙 1 을 건너뛴다")
    void 잔여시간이_없거나_음수() {
        assertEquals(ArrivalEta.Source.NONE, ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), null, "서초", "강남", NOW).source());
        assertEquals(ArrivalEta.Source.NONE, ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), -10, "서초", "강남", NOW).source());
    }

    @Test
    @DisplayName("역 이름이 비어 있으면 같다고 보지 않는다")
    void 역_이름이_비면_아니다() {
        assertEquals(ArrivalEta.Source.NONE, ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), 0, null, "강남", NOW).source());
        assertEquals(ArrivalEta.Source.NONE, ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), 0, "", "", NOW).source());
        assertEquals(ArrivalEta.Source.NONE, ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), 0, "  ", "  ", NOW).source());
    }

    // ── 우선순위: 실측 204건이 규칙 1·2 에 함께 걸린다 ─────────────────────────

    @Test
    @DisplayName("둘 다 해당하면 잔여시간이 우선한다 — 원천이 직접 준 값이 더 정확하다")
    void 잔여시간이_우선() {
        ArrivalEta eta = ArrivalEta.of(at("2026-09-16T13:37:43+09:00"), 90, "강남", "강남", NOW);

        assertEquals(at("2026-09-16T13:39:13+09:00"), eta.etaAt());
        assertEquals(ArrivalEta.Source.BARVL, eta.source());
    }

    // ── 이상치 가드: written_at 기준 -5분 ~ +30분 ─────────────────────────────

    @Test
    @DisplayName("너무 먼 미래는 버린다 — 8호선에 recptn_dt 가 13시간 미래인 행이 실재한다")
    void 먼_미래는_버린다() {
        ArrivalEta eta = ArrivalEta.of(at("2026-09-17T02:38:00+09:00"), 60, "강남", "강남", NOW);

        assertNull(eta.etaAt());
        assertEquals(ArrivalEta.Source.NONE, eta.source());
    }

    @Test
    @DisplayName("이미 지난 열차도 버린다 — 곧 도착으로 보여주면 안 된다")
    void 지난_것은_버린다() {
        ArrivalEta eta = ArrivalEta.of(at("2026-09-16T12:38:00+09:00"), 0, "강남", "강남", NOW);

        assertNull(eta.etaAt());
        assertEquals(ArrivalEta.Source.NONE, eta.source());
    }

    @Test
    @DisplayName("가드 경계 — 정확히 +30분·-5분은 통과, 1초라도 넘으면 버린다")
    void 가드_경계() {
        // +30분 정각
        assertEquals(ArrivalEta.Source.BARVL,
                ArrivalEta.of(NOW, 30 * 60, "서초", "강남", NOW).source());
        // +30분 1초
        assertEquals(ArrivalEta.Source.NONE,
                ArrivalEta.of(NOW, 30 * 60 + 1, "서초", "강남", NOW).source());
        // -5분 정각 (그 역에 있음)
        assertEquals(ArrivalEta.Source.ARRIVED,
                ArrivalEta.of(NOW.minusMinutes(5), 0, "강남", "강남", NOW).source());
        // -5분 1초
        assertEquals(ArrivalEta.Source.NONE,
                ArrivalEta.of(NOW.minusMinutes(5).minusSeconds(1), 0, "강남", "강남", NOW).source());
    }

    // ── 계약에 나가는 문자열 ──────────────────────────────────────────────────

    @Test
    @DisplayName("eta_source 는 소문자 문자열로 나간다 — 192 가 그대로 쓰는 계약 값이다")
    void 계약_문자열() {
        assertEquals("barvl", ArrivalEta.Source.BARVL.wire());
        assertEquals("arrived", ArrivalEta.Source.ARRIVED.wire());
        assertEquals("none", ArrivalEta.Source.NONE.wire());
    }

    @Test
    @DisplayName("산출 못 하면 eta_at 은 null 이고 source 는 none — 0 이나 빈 문자열로 속이지 않는다")
    void 못_만들면_null() {
        ArrivalEta eta = ArrivalEta.NONE;

        assertNull(eta.etaAt());
        assertEquals(ArrivalEta.Source.NONE, eta.source());
    }

    // ── 가드에 걸린 것과 애초에 못 만든 것을 구분한다 (관측용) ──────────────────

    @Test
    @DisplayName("가드에 걸린 것은 guarded 로 표시한다 — 원천 이상치가 늘어나는 것을 로그로 보려면 필요하다")
    void 가드에_걸린_것을_표시한다() {
        ArrivalEta rejected = ArrivalEta.of(at("2026-09-17T02:38:00+09:00"), 60, "강남", "강남", NOW);

        assertEquals(ArrivalEta.Source.NONE, rejected.source(), "계약 값은 none 그대로다");
        assertNull(rejected.etaAt());
        org.junit.jupiter.api.Assertions.assertTrue(rejected.guarded(), "가드가 버린 값이다");
    }

    @Test
    @DisplayName("애초에 만들 수 없던 것은 guarded 가 아니다 — 대부분(46.9%)이 여기다")
    void 못_만든_것은_가드가_아니다() {
        ArrivalEta far = ArrivalEta.of(at("2026-09-16T13:38:05+09:00"), 0, "청계산입구", "강남", NOW);

        assertEquals(ArrivalEta.Source.NONE, far.source());
        org.junit.jupiter.api.Assertions.assertFalse(far.guarded(), "위치만 아는 정상 상황이지 이상치가 아니다");
        org.junit.jupiter.api.Assertions.assertFalse(ArrivalEta.NONE.guarded());
    }

    @Test
    @DisplayName("정상 산출은 guarded 가 아니다")
    void 정상_산출은_가드가_아니다() {
        org.junit.jupiter.api.Assertions.assertFalse(
                ArrivalEta.of(at("2026-09-16T13:37:43+09:00"), 150, "서초", "강남", NOW).guarded());
    }
}
