package com.ssafy.s15p21a104.domain.route.transfer;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.Map;
import java.util.Set;
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
     * 환승 판정 결과. 비용 계산에 쓸 이전 노선까지 함께 돌려줘 호출 4곳이 같은 판정을 쓴다.
     *
     * @param transfer 환승 여부
     * @param costLine 환승이면 실측·상수 조회용 이전 노선. 비환승이면 null
     */
    public record TransferDecision(boolean transfer, String costLine) {
    }

    /**
     * 대중교통 수단인지 판정한다. SUBWAY·BUS만 대중교통으로 본다.
     * WALK는 접근, BIKE는 단독 탑승으로 보고 노선 유지 대상에서 뺀다.
     */
    public static boolean isTransit(TravelMode mode) {
        return mode == TravelMode.SUBWAY || mode == TravelMode.BUS;
    }

    /**
     * 직전 대중교통 노선을 갱신한다(S15P21A104-232). 대중교통 구간을 지나면 그 노선으로,
     * 그 외 수단(WALK·BIKE)이면 그대로 둔다 — WALK를 지나도 이전 대중교통이 유지된다.
     */
    public static String keptTransitLine(String keptLine, TravelMode mode, String routeId) {
        if (!isTransit(mode)) {
            return keptLine;
        }
        return routeId;
    }

    /**
     * 환승 여부를 판정한다(S15P21A104-232). 탐색기·매퍼·조립기가 같은 판정을 호출한다.
     *
     * <p>직전 대중교통 노선과 다음 대중교통이 다르면 환승이다 — 사이에 WALK가 있어도
     * 유지된 노선으로 비교한다. 첫 탑승(kept 없음)은 환승이 아니다. 대중교통↔BIKE
     * 직접 경계는 기존대로 환승으로 본다 (WALK가 낀 접근과 다름).
     *
     * @param keptLine 직전 대중교통 노선. 없으면 null
     * @param prevMode 이전 구간 수단. null이면 경로 시작으로 보고 환승 아님
     * @param prevLine 이전 구간 노선
     * @param nextMode 다음 구간 수단
     * @param nextLine 다음 구간 노선
     */
    public static TransferDecision decide(String keptLine, TravelMode prevMode, String prevLine,
                                          TravelMode nextMode, String nextLine) {
        if (prevMode != null && isTransit(nextMode)
                && keptLine != null && !keptLine.isEmpty()
                && nextLine != null && !keptLine.equals(nextLine)) {
            return new TransferDecision(true, keptLine);
        }
        if (prevMode != null && prevLine != null && nextLine != null
                && !prevLine.equals(nextLine)
                && !isAccessBoundary(prevMode, nextMode)) {
            return new TransferDecision(true, prevLine);
        }
        return new TransferDecision(false, null);
    }

    /**
     * 환승 없이 현재까지 이어서 탈 수 있는 대중교통 노선 집합을 갱신한다(S15P21A104-234).
     * 비대중교통 구간에서는 기존 집합을 유지하고, 첫 대중교통 구간에서는 현재 옵션을 쓴다.
     * 이후에는 교집합을 누적하며, 교집합이 비면 환승 경계 뒤 새 탑승으로 보고 현재 옵션으로
     * 다시 시작한다.
     */
    public static Set<String> keptTransitLines(
            Set<String> kept, TravelMode mode, Set<String> options) {
        Set<String> keptSafe = kept == null ? Set.of() : Set.copyOf(kept);
        if (!isTransit(mode)) {
            return keptSafe;
        }
        Set<String> optionsSafe = options == null ? Set.of() : Set.copyOf(options);
        if (keptSafe.isEmpty()) {
            return optionsSafe;
        }
        Set<String> intersection = new java.util.HashSet<>(keptSafe);
        intersection.retainAll(optionsSafe);
        return intersection.isEmpty() ? optionsSafe : Set.copyOf(intersection);
    }

    /**
     * 환승 여부를 노선 집합 교집합으로 판정한다(S15P21A104-234). 연속 탑승 구간에 공통
     * 노선이 없으면 환승이다 (같은 정류장 108→143 포함). 첫 탑승(kept 비어 있음)은 아니다.
     * 기존 문자열 `decide`는 SUBWAY 등 단일 노선 경로에서 그대로 쓴다.
     */
    public static TransferDecision decideLines(
            Set<String> kept, TravelMode prevMode, Set<String> prevOptions,
            TravelMode nextMode, Set<String> nextOptions) {
        Set<String> keptSafe = kept == null ? Set.of() : kept;
        Set<String> nextSafe = nextOptions == null ? Set.of() : nextOptions;
        if (prevMode != null && isTransit(nextMode) && !keptSafe.isEmpty() && !nextSafe.isEmpty()) {
            for (String line : nextSafe) {
                if (keptSafe.contains(line)) {
                    return new TransferDecision(false, null);
                }
            }
            return new TransferDecision(true, null);
        }
        return new TransferDecision(false, null);
    }

    /**
     * 경계 환승 비용. 후보 쌍 중 실측 최소값, 전부 miss면 상수(Q3 결정).
     */
    public long transferCost(String stationId, Set<String> fromLines, Set<String> toLines) {
        long best = defaultSec;
        boolean found = false;
        if (fromLines != null && toLines != null && stationId != null) {
            for (String from : fromLines) {
                for (String to : toLines) {
                    Integer measured = transferTimes.get(new TransferKey(stationId, from, to));
                    if (measured != null && (!found || measured < best)) {
                        best = measured;
                        found = true;
                    }
                }
            }
        }
        return best;
    }

    /**
     * @return 환승 1회당 가산 초
     */
    public long getDefaultSec() {
        return defaultSec;
    }
}
