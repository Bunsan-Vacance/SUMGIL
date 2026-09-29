package com.ssafy.s15p21a104.consume;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.Locale;

/**
 * 열차 한 대의 도착예정시각 산출 (S15P21A104-224).
 *
 * <p>재료는 이미 이벤트 안에 있다 — {@code recptn_dt}(원천이 정보를 만든 시각)와 {@code barvl_sec}(도착까지 남은 초).
 * 읽는 쪽이 더해도 되지만, <b>신뢰도 분류({@link Source})와 이상치 가드를 한 곳에 모으려고</b> 여기서 계산한다.
 * 읽는 쪽이 여럿이 되면 같은 덧셈과 같은 가드를 저마다 반복하게 된다.
 *
 * <p><b>{@code arvlCd} 로 가르지 않는다.</b> 2026-09-16 prod 덤프 6,500행 실측 기준,
 * {@code arvlCd=1}(도착) 932건 중 153건이 실제로는 {@code [N]번째 전역} 이고,
 * {@code arvlCd=99}(운행중) 중 1,807건은 오히려 {@code barvlDt} 를 가지고 있다. 코드값이 위치를 대표하지 못한다.
 * 대신 {@code arvlMsg3}(열차가 지금 있는 역)가 조회 대상 역과 같은지를 본다.
 *
 * <table>
 *   <caption>산출 규칙 (우선순위 순, 괄호는 실측 비율)</caption>
 *   <tr><th>조건</th><th>eta</th><th>source</th></tr>
 *   <tr><td>{@code barvl_sec > 0}</td><td>{@code recptn_dt + barvl_sec}</td><td>{@code barvl} (38.7%)</td></tr>
 *   <tr><td>{@code arvl_msg3 == statnNm}</td><td>{@code recptn_dt}</td><td>{@code arrived} (14.4%)</td></tr>
 *   <tr><td>그 외</td><td>null</td><td>{@code none} (46.9%)</td></tr>
 * </table>
 *
 * <p>둘 다 해당하는 행이 실측 204건 있다. 원천이 직접 준 잔여시간이 더 정확하므로 {@code barvl} 이 우선이다.
 *
 * <p>행 기준 커버는 53.1% 지만, 사용자가 보는 것은 역·방향별 "다음 열차" 라 체감은 더 높다 —
 * 573곳 중 421곳(73.5%)에서 최소 한 대는 시각이 나오고, 2·6·7·8·9호선·우이신설은 100% 다.
 * 코레일·민자 노선(경의중앙·수인분당·신분당·공항철도 등)은 {@code barvlDt} 를 아예 주지 않는다 —
 * 데이터 품질 문제가 아니라 운영사별 제공 정책 차이다.
 *
 * @param etaAt   도착예정시각. 산출 못 하면 null
 * @param source  어떻게 나온 값인지. 읽는 쪽이 "얼마나 믿을지" 를 판단하는 근거다
 * @param guarded 값을 만들었는데 가드가 버렸는지. <b>Redis 값에는 나가지 않는다</b> — 원천 이상치가 늘어나는 것을
 *                로그로 보기 위한 관측용이다. 애초에 만들 수 없던 경우(46.9%)와 구분해야 의미가 있다
 */
public record ArrivalEta(OffsetDateTime etaAt, Source source, boolean guarded) {

    /** 산출 불가. {@code eta_at} 을 0 이나 빈 문자열로 속이지 않는다. */
    public static final ArrivalEta NONE = new ArrivalEta(null, Source.NONE, false);

    /** 값은 만들었지만 가드 범위를 벗어나 버린 경우. 계약 값은 {@link #NONE} 과 같다. */
    static final ArrivalEta GUARDED = new ArrivalEta(null, Source.NONE, true);

    /**
     * 이상치 가드 상한. {@code recptn_dt} 가 13시간 미래인 행이 8호선에 실재한다(2026-09-16 실측).
     * 수집 주기가 60초라 30분을 넘는 도착예정은 정상 범위가 아니다.
     */
    static final Duration MAX_AHEAD = Duration.ofMinutes(30);

    /**
     * 이상치 가드 하한. 이미 지난 열차를 "곧 도착" 으로 보여주지 않기 위해 과거는 조금만 허용한다.
     * 원천이 정보를 만든 뒤 우리가 받기까지 26~100초가 걸리므로(노선별 실측) 0 으로 두면 정상값까지 잘린다.
     */
    static final Duration MAX_BEHIND = Duration.ofMinutes(5);

    public enum Source {
        /** 원천이 남은 초를 직접 줬다. 가장 믿을 만하다 */
        BARVL,
        /** 열차가 지금 그 역에 있다 */
        ARRIVED,
        /** 산출 못 함. 읽는 쪽은 {@code arvl_msg2} 문구를 그대로 보여주면 된다 */
        NONE;

        /** Redis 값에는 소문자로 나간다 — 192 가 그대로 쓰는 계약 문자열이다. */
        public String wire() {
            return name().toLowerCase(Locale.ROOT);
        }
    }

    /**
     * @param recptnDt 원천이 이 도착정보를 만든 시각. 없으면 아무것도 못 만든다
     * @param barvlSec 도착까지 남은 초. null·0·음수면 규칙 1 을 건너뛴다
     * @param arvlMsg3 열차가 지금 있는 역 이름 (원천 표기)
     * @param statnNm  조회 대상 역 이름 (원천 표기). 정본 표의 이름이 아니라 <b>원천 표기끼리</b> 비교해야 한다 —
     *                 우리 정본 이름은 부역명 괄호를 벗긴 것이라 {@code arvlMsg3} 와 표기가 다를 수 있다
     * @param now      컨슈머가 Redis 에 쓰는 시각. 가드의 기준점이다
     */
    public static ArrivalEta of(OffsetDateTime recptnDt, Integer barvlSec, String arvlMsg3, String statnNm,
                                OffsetDateTime now) {
        if (recptnDt == null) {
            return NONE;
        }
        if (barvlSec != null && barvlSec > 0) {
            return guarded(recptnDt.plusSeconds(barvlSec), Source.BARVL, now);
        }
        if (sameStation(arvlMsg3, statnNm)) {
            return guarded(recptnDt, Source.ARRIVED, now);
        }
        return NONE;
    }

    /** 가드를 벗어나면 값을 버린다 — 틀린 시각을 주느니 모른다고 하는 편이 낫다. */
    private static ArrivalEta guarded(OffsetDateTime eta, Source source, OffsetDateTime now) {
        if (now == null) {
            return new ArrivalEta(eta, source, false);
        }
        if (eta.isAfter(now.plus(MAX_AHEAD)) || eta.isBefore(now.minus(MAX_BEHIND))) {
            return GUARDED;
        }
        return new ArrivalEta(eta, source, false);
    }

    private static boolean sameStation(String arvlMsg3, String statnNm) {
        if (arvlMsg3 == null || statnNm == null) {
            return false;
        }
        String here = arvlMsg3.trim();
        return !here.isEmpty() && here.equals(statnNm.trim());
    }
}
