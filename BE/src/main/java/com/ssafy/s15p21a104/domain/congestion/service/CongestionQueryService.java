package com.ssafy.s15p21a104.domain.congestion.service;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchResponse;
import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchSlot;
import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchTarget;
import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.Congestion;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 혼잡도 조회(S15P21A104-150). 대상·시간대로 {@code congestion} 테이블 값을 그대로 꺼낸다.
 *
 * <p>데이터 없는 조합은 에러가 아니라 {@code null} — 컨트롤러가 {@code 200 + data 없음}으로 응답한다.
 * 값을 추정·보간하지 않는다.
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class CongestionQueryService {

    public static final int MAX_BATCH_TARGETS = 50;
    public static final int MAX_BATCH_TIMES = 12;
    public static final int MAX_BATCH_COMBINATIONS = 200;

    private final CongestionRepository congestionRepository;

    private record SlotKey(String targetId, int dowType, int timeSlot) {
    }

    /**
     * @param targetType 대상 종류(역/노선 등)
     * @param targetId 대상 ID
     * @param departureTime 기준 시각. 생략 시 현재 시각
     * @return 조회된 혼잡도. 데이터 없으면 {@code null}
     */
    public CongestionResponse find(CongestionTarget targetType, String targetId, LocalDateTime departureTime) {
        DepartureSlot slot = DepartureSlot.of(departureTime != null ? departureTime : LocalDateTime.now());
        return congestionRepository
                .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                        targetType, targetId, slot.dowType(), slot.timeSlot())
                .map(this::toResponse)
                .orElse(null);
    }

    /**
     * 여러 대상·여러 시각의 혼잡도를 한 번의 쿼리로 조회한다(S15P21A104-354). 단건 {@link #find}와
     * 같은 값을 돌려주며, 모든 (대상, 시각) 조합을 응답에 포함한다 — 데이터 없는 조합은 값이 null이다.
     *
     * @param targetIds 대상 ID 목록. 불투명 문자열로 다루며 공백·빈 값·중복은 정리한다. 비면 {@code BAD_REQUEST}
     * @param departureTimes 기준 시각 목록. 생략·빈 목록이면 현재 시각 하나. 중복은 정리한다
     * @throws DomainException 대상이 없으면 {@code BAD_REQUEST}, 상한 초과면 {@code CONGESTION_BATCH_TOO_LARGE}
     */
    public CongestionBatchResponse findBatch(
            CongestionTarget targetType, List<String> targetIds, List<LocalDateTime> departureTimes) {
        List<String> ids = normalizeTargetIds(targetIds);
        if (ids.isEmpty()) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
        List<LocalDateTime> times = normalizeTimes(departureTimes);
        if (ids.size() > MAX_BATCH_TARGETS
                || times.size() > MAX_BATCH_TIMES
                || ids.size() * times.size() > MAX_BATCH_COMBINATIONS) {
            throw new DomainException(ErrorType.CONGESTION_BATCH_TOO_LARGE);
        }

        List<DepartureSlot> slots = times.stream().map(DepartureSlot::of).toList();
        Set<Integer> dowTypes = new LinkedHashSet<>();
        Set<Integer> timeSlots = new LinkedHashSet<>();
        for (DepartureSlot slot : slots) {
            dowTypes.add(slot.dowType());
            timeSlots.add(slot.timeSlot());
        }
        Map<SlotKey, Congestion> found = new HashMap<>();
        for (Congestion congestion : congestionRepository
                .findById_TargetTypeAndId_TargetIdInAndId_DowTypeInAndId_TimeSlotIn(
                        targetType, ids, dowTypes, timeSlots)) {
            found.put(new SlotKey(
                    congestion.getId().getTargetId(),
                    congestion.getId().getDowType(),
                    congestion.getId().getTimeSlot()), congestion);
        }

        List<CongestionBatchTarget> targets = new ArrayList<>(ids.size());
        for (String id : ids) {
            List<CongestionBatchSlot> rows = new ArrayList<>(times.size());
            for (int i = 0; i < times.size(); i++) {
                DepartureSlot slot = slots.get(i);
                Congestion congestion = found.get(new SlotKey(id, slot.dowType(), slot.timeSlot()));
                rows.add(new CongestionBatchSlot(
                        times.get(i),
                        slot.dowType(),
                        slot.timeSlot(),
                        congestion != null ? congestion.getLevel() : null,
                        congestion != null ? congestion.getSource() : null,
                        congestion != null ? congestion.getUpdatedAt() : null));
            }
            targets.add(new CongestionBatchTarget(id, rows));
        }
        return new CongestionBatchResponse(targetType, times, targets);
    }

    private List<String> normalizeTargetIds(List<String> targetIds) {
        Set<String> unique = new LinkedHashSet<>();
        if (targetIds != null) {
            for (String id : targetIds) {
                if (id == null) {
                    continue;
                }
                String stripped = id.strip();
                if (!stripped.isEmpty()) {
                    unique.add(stripped);
                }
            }
        }
        return List.copyOf(unique);
    }

    private List<LocalDateTime> normalizeTimes(List<LocalDateTime> departureTimes) {
        if (departureTimes == null || departureTimes.isEmpty()) {
            return List.of(LocalDateTime.now());
        }
        Set<LocalDateTime> unique = new LinkedHashSet<>();
        for (LocalDateTime time : departureTimes) {
            if (time != null) {
                unique.add(time);
            }
        }
        return unique.isEmpty() ? List.of(LocalDateTime.now()) : List.copyOf(unique);
    }

    private CongestionResponse toResponse(Congestion congestion) {
        return new CongestionResponse(
                congestion.getId().getTargetType(),
                congestion.getId().getTargetId(),
                congestion.getId().getDowType(),
                congestion.getId().getTimeSlot(),
                congestion.getLevel(),
                congestion.getSource(),
                congestion.getUpdatedAt());
    }
}
