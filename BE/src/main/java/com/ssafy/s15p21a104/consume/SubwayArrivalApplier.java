package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import lombok.extern.slf4j.Slf4j;

/**
 * {@code subway.arrival} → Redis {@code subway:arrival:{station_id}} (S15P21A104-171).
 *
 * <p><b>역 단위 통째 교체.</b> 열차별로 부분 갱신하면 이미 떠난 열차가 TTL 까지 남아 "탑승 확인" 을 오염시킨다.
 * 그런데 한 배치가 회차 하나와 일치한다는 보장이 없다 — 회차가 약 3,000건이라 {@code max.poll.records} 로 잘린다.
 * 그래서 배치 경계에 기대지 않고 <b>저장된 {@code poll_run_at} 과 비교해서</b> 결정한다.
 *
 * <ul>
 *   <li>새 회차가 더 최신 → 그 역의 {@code trains} 를 통째로 새로 쓴다</li>
 *   <li>저장된 것과 같은 회차 → 이어붙인다 (배치가 잘려 들어온 경우). 같은 열차는 한 번만</li>
 *   <li>저장된 것보다 옛 회차 → 건너뛴다 (NFR-STREAM-004)</li>
 * </ul>
 *
 * <p>대응표에 없는 역은 쓰지 않고 센다 — 아무 역에나 쓰면 틀린 역의 도착 정보가 된다. 2026-09-16 기준
 * 안 붙는 것은 GTX-A 9역과 1호선 지제뿐이다 ({@code docs/infra/consumer.md} 1절).
 *
 * <p>도착예정시각({@code eta_at})은 v1 에서 추정하지 않는다 — API 의 {@code barvlDt} 가 0 으로 오는 경우가
 * 60.4%(2026-09-15 실측 2,872행)라 그대로는 만들 수 없고, 구간 합산 알고리즘이 따로 필요하다. 후속 티켓.
 */
@Slf4j
public final class SubwayArrivalApplier implements EventApplier {

    private final RedisWriter redis;
    private final StatnIdMap statnIds;
    private final OperatingWindow window;
    private final Clock clock;

    public SubwayArrivalApplier(RedisWriter redis, StatnIdMap statnIds, OperatingWindow window, Clock clock) {
        this.redis = redis;
        this.statnIds = statnIds;
        this.window = window;
        this.clock = clock;
    }

    @Override
    public String topic() {
        return "subway.arrival";
    }

    @Override
    public ApplyResult apply(List<CollectEvent> batch) {
        if (batch.isEmpty()) {
            return ApplyResult.NOTHING;
        }
        OffsetDateTime writtenAt = OffsetDateTime.now(clock.withZone(CollectEvent.KST));

        Map<String, List<CollectEvent>> byStation = new LinkedHashMap<>();
        Map<String, String> stationNames = new LinkedHashMap<>();
        OffsetDateTime latestRun = null;
        int unmapped = 0;

        for (CollectEvent event : batch) {
            // 회차 시각은 매핑 여부와 무관하게 "우리가 이 회차를 받았다" 는 사실이라 상태 키에 쓴다
            latestRun = later(latestRun, event.pollRunAt());
            Optional<StatnIdMap.Mapped> mapped = statnIds.find(event.entityId());
            if (mapped.isEmpty()) {
                unmapped++;
                continue;
            }
            String stationId = mapped.get().stationId();
            byStation.computeIfAbsent(stationId, k -> new ArrayList<>()).add(event);
            stationNames.putIfAbsent(stationId, mapped.get().name());
        }

        int written = 0;
        int skipped = 0;
        for (Map.Entry<String, List<CollectEvent>> entry : byStation.entrySet()) {
            ApplyResult one = applyStation(entry.getKey(), stationNames.get(entry.getKey()), entry.getValue(), writtenAt);
            written += one.written();
            skipped += one.skipped();
        }

        writeStatus(latestRun, writtenAt);
        return new ApplyResult(written, skipped, unmapped);
    }

    private ApplyResult applyStation(String stationId, String stationName, List<CollectEvent> events,
                                     OffsetDateTime writtenAt) {
        OffsetDateTime run = null;
        for (CollectEvent event : events) {
            run = later(run, event.pollRunAt());
        }

        String key = CacheKeys.subwayArrival(stationId);
        Optional<Map<String, Object>> stored = redis.get(key);
        OffsetDateTime storedRun = stored.map(v -> Times.parse(v.get("poll_run_at"))).orElse(null);

        if (storedRun != null && run != null && run.isBefore(storedRun)) {
            return new ApplyResult(0, events.size(), 0);
        }

        boolean sameRun = storedRun != null && run != null && run.isEqual(storedRun);
        List<Map<String, Object>> trains = sameRun ? existingTrains(stored.get()) : new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Map<String, Object> train : trains) {
            seen.add(String.valueOf(train.get("train_no")));
        }

        int skipped = 0;
        int added = 0;
        for (CollectEvent event : events) {
            // 잘려 들어온 배치에 이전 회차 행이 섞여 있으면 그 행만 버린다
            if (run != null && event.pollRunAt() != null && !event.pollRunAt().isEqual(run)) {
                skipped++;
                continue;
            }
            Map<String, Object> train = toTrain(event);
            if (!seen.add(String.valueOf(train.get("train_no")))) {
                skipped++;
                continue;
            }
            trains.add(train);
            added++;
        }
        if (added == 0) {
            // 전부 중복이면 값이 그대로다 — 굳이 다시 쓰지 않는다
            return new ApplyResult(0, skipped, 0);
        }

        Map<String, Object> value = new LinkedHashMap<>();
        value.put("station_id", stationId);
        value.put("station_name", stationName);
        value.put("poll_run_at", Times.format(run));
        value.put("source_generated_at", Times.format(newestRecptnDt(trains)));
        value.put("written_at", Times.format(writtenAt));
        value.put("trains", trains);
        redis.set(key, value, CacheKeys.SUBWAY_ARRIVAL_TTL);
        return new ApplyResult(1, skipped, 0);
    }

    private void writeStatus(OffsetDateTime latestRun, OffsetDateTime writtenAt) {
        OffsetDateTime lastRun = latestRun;
        // 이번 배치가 전부 매핑 실패여도 회차는 받은 것이다. 저장된 값이 더 최신이면 그것을 유지한다.
        OffsetDateTime stored = redis.get(CacheKeys.SUBWAY_ARRIVAL_STATUS)
                .map(v -> Times.parse(v.get("last_poll_run_at"))).orElse(null);
        lastRun = later(lastRun, stored);

        ArrivalStatus.State state = ArrivalStatus.evaluate(writtenAt, window, lastRun, ArrivalStatus.STALE_AFTER);
        redis.set(CacheKeys.SUBWAY_ARRIVAL_STATUS, ArrivalStatus.value(state, lastRun, window, writtenAt), null);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> existingTrains(Map<String, Object> value) {
        Object trains = value.get("trains");
        return trains instanceof List<?> list ? new ArrayList<>((List<Map<String, Object>>) list) : new ArrayList<>();
    }

    /** API 행 하나 → 열차 한 대. 코드·문구는 원본 그대로 넘기고 해석은 읽는 쪽에 맡긴다 (kafka.md 5절과 같은 원칙). */
    private static Map<String, Object> toTrain(CollectEvent event) {
        Map<String, Object> row = event.payload();
        Map<String, Object> train = new LinkedHashMap<>();
        train.put("line_id", text(row.get("subwayId")));
        train.put("updn_line", text(row.get("updnLine")));
        train.put("train_line_nm", text(row.get("trainLineNm")));
        train.put("train_no", text(row.get("btrainNo")));
        train.put("train_sttus", text(row.get("btrainSttus")));
        train.put("dest_station_nm", text(row.get("bstatnNm")));
        train.put("barvl_sec", number(row.get("barvlDt")));
        train.put("arvl_cd", text(row.get("arvlCd")));
        train.put("arvl_msg2", text(row.get("arvlMsg2")));
        train.put("arvl_msg3", text(row.get("arvlMsg3")));
        train.put("last_car_at", text(row.get("lstcarAt")));
        train.put("recptn_dt", Times.format(event.sourceGeneratedAt()));
        train.put("eta_at", null);
        train.put("eta_source", "none");
        return train;
    }

    private static OffsetDateTime newestRecptnDt(List<Map<String, Object>> trains) {
        OffsetDateTime newest = null;
        for (Map<String, Object> train : trains) {
            newest = later(newest, Times.parse(train.get("recptn_dt")));
        }
        return newest;
    }

    private static OffsetDateTime later(OffsetDateTime a, OffsetDateTime b) {
        if (a == null) {
            return b;
        }
        return b == null || a.isAfter(b) ? a : b;
    }

    private static String text(Object value) {
        return value == null ? null : value.toString();
    }

    private static Integer number(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return Integer.valueOf(value.toString().trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
