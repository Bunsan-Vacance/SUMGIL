package com.ssafy.s15p21a104.domain.route.transfer;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 환승 비용 규칙(상수).
 *
 * <p>1주차 PoC는 그래프에 환승 정점/엣지를 두지 않고 탐색 시 상수를 가산한다.
 * {@code edge_time}의 TRANSFER 행·{@code transfer_meta}는 읽지 않는다.
 *
 * <p>95(최단경로)가 호출하는 구현 정본이다. 시그니처를 임의 변경하지 않는다.
 */
@Component
public class TransferRule {

    private final long defaultSec;

    /**
     * @param defaultSec 환승 1회당 가산 초. {@code transfer.default-sec}, 기본 180.
     */
    public TransferRule(@Value("${transfer.default-sec:180}") long defaultSec) {
        this.defaultSec = defaultSec;
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
     * @return 환승 1회당 가산 초
     */
    public long getDefaultSec() {
        return defaultSec;
    }
}
