package com.ssafy.s15p21a104.domain.route.transfer;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 환승 비용 규칙. 적재된 역별 실측이 있으면 쓰고, 없으면 상수로 폴백한다.
 *
 * <p>1주차 PoC는 그래프에 환승 정점/엣지를 두지 않고 탐색 시 비용을 가산한다.
 * {@code edge_time}의 TRANSFER 행은 읽지 않는다.
 *
 * <p>95(최단경로)가 호출하는 구현 정본이다. 기존 {@link #cost} 시그니처는 유지한다.
 */
@Component
public class TransferRule {

    /**
     * 역별 실측 조회 키. 방향이 있어 (역, 이전 노선, 다음 노선) 순서대로 적는다.
     */
    public record TransferKey(String stationId, String fromLine, String toLine) {
    }

    private final long defaultSec;
    private final Map<TransferKey, Integer> transferTimes;

    /**
     * @param defaultSec 환승 1회당 가산 초. {@code transfer.default-sec}, 기본 180.
     */
    @Autowired
    public TransferRule(@Value("${transfer.default-sec:180}") long defaultSec) {
        this(defaultSec, Map.of());
    }

    private TransferRule(long defaultSec, Map<TransferKey, Integer> transferTimes) {
        this.defaultSec = defaultSec;
        this.transferTimes = Map.copyOf(transferTimes);
    }

    /**
     * 적재 실측표를 얹은 규칙을 만든다. 원본은 그대로 둔다.
     *
     * @param transferTimes (역, 이전 노선, 다음 노선)별 실측 초
     * @return 실측 우선 규칙
     */
    public TransferRule withTable(Map<TransferKey, Integer> transferTimes) {
        return new TransferRule(defaultSec, transferTimes == null ? Map.of() : transferTimes);
    }

    /**
     * 구간 소요에 환승 상수를 더한 비용을 반환한다.
     *
     * @param travelSec   엣지 구간 소요(초)
     * @param currentLine 현재 노선. 없음(출발 직후 첫 엣지)은 null·빈 문자열 허용
     * @param nextLine    다음 엣지의 routeId
     * @return 같은 노선·첫 엣지면 travelSec, 노선 전환이면 travelSec + 상수
     */
    public long cost(long travelSec, String currentLine, String nextLine) {
        if (isTransfer(currentLine, nextLine)) {
            return travelSec + defaultSec;
        }
        return travelSec;
    }

    /**
     * 구간 소요에 역별 실측(없으면 상수)을 더한 비용을 반환한다.
     *
     * @param travelSec 엣지 구간 소요(초)
     * @param stationId 환승이 일어나는 역 ID. null이면 실측 없이 상수
     * @param currentLine 현재 노선. 없음(출발 직후 첫 엣지)은 null·빈 문자열 허용
     * @param nextLine 다음 엣지의 routeId
     * @return 같은 노선·첫 엣지면 travelSec, 노선 전환이면 travelSec + 실측(없으면 상수)
     */
    public long costWithStation(long travelSec, String stationId,
                                String currentLine, String nextLine) {
        if (!isTransfer(currentLine, nextLine)) {
            return travelSec;
        }
        Integer measured = null;
        if (stationId != null && currentLine != null && nextLine != null) {
            measured = transferTimes.get(new TransferKey(stationId, currentLine, nextLine));
        }
        return travelSec + (measured != null ? measured : defaultSec);
    }

    /**
     * 환승 여부를 판정한다. 상수 1회 부과 = 환승 1회이므로 외부에서 환승 횟수 집계에 쓴다.
     *
     * @param currentLine 현재 노선. null·빈 문자열이면 첫 엣지로 보고 환승 아님
     * @param nextLine    다음 엣지의 routeId
     * @return 노선이 바뀌면 true, 같거나 첫 엣지면 false
     */
    public boolean isTransfer(String currentLine, String nextLine) {
        if (currentLine == null || currentLine.isEmpty()) {
            return false;
        }
        if (nextLine == null || nextLine.isEmpty()) {
            return false;
        }
        return !currentLine.equals(nextLine);
    }

    /**
     * 구간 소요에 역별 실측(없으면 상수)을 더한 비용을 반환한다. 접근 경계에서는
     * 환승이 아니므로 가산 없이 구간 소요만 돌려준다(S15P21A104-213 T1).
     *
     * @param travelSec 엣지 구간 소요(초)
     * @param stationId 환승이 일어나는 역 ID. null이면 실측 없이 상수
     * @param currentLine 현재 노선. 없음(출발 직후 첫 엣지)은 null·빈 문자열 허용
     * @param nextLine 다음 엣지의 routeId
     * @param prevMode 이전 구간의 수단. null이면 경로 시작으로 보고 접근 아님
     * @param nextMode 다음 구간의 수단
     * @return 접근 경계면 travelSec, 노선 전환이면 travelSec + 실측(없으면 상수)
     */
    public long costWithStation(long travelSec, String stationId,
                                String currentLine, String nextLine,
                                TravelMode prevMode, TravelMode nextMode) {
        if (isAccessBoundary(prevMode, nextMode)) {
            return travelSec;
        }
        return costWithStation(travelSec, stationId, currentLine, nextLine);
    }

    /**
     * 접근 경계인지 판정한다(S15P21A104-213 T1). 접근은 환승이 아니다.
     *
     * <p>도보로 타는 곳까지 가거나(WALK → 주행), 내려서 걸어가거나(주행 → WALK),
     * 빌려서 타거나(WALK → BIKE) 반납하고 걷는(BIKE → WALK) 이동은 환승이 아니라
     * 접근·반납이다. TRANSFER leg를 만들지 않고 비용도 가산하지 않는다.
     *
     * <p>순수 모드 판정이라 인스턴스 상태와 무관하다 — static으로 두고 탐색기·매퍼·
     * 서비스가 같은 판정을 호출한다.
     *
     * @param prevMode 이전 구간의 수단. null이면 경로 시작으로 보고 접근 아님
     * @param nextMode 다음 구간의 수단
     * @return 접근 경계면 true, 환승 후보면 false
     */
    public static boolean isAccessBoundary(TravelMode prevMode, TravelMode nextMode) {
        if (prevMode == null || nextMode == null) {
            return false;
        }
        if (prevMode == nextMode) {
            return false;
        }
        return prevMode == TravelMode.WALK || nextMode == TravelMode.WALK;
    }

    /**
     * @return 환승 1회당 가산 초
     */
    public long getDefaultSec() {
        return defaultSec;
    }
}
