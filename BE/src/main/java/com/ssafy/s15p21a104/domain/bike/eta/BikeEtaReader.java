package com.ssafy.s15p21a104.domain.bike.eta;

import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.Optional;
import lombok.extern.slf4j.Slf4j;
import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

/**
 * AI 실시간 재고 예측 {@code GET /bike/stations/{id}/eta-stock?eta_minutes=N} 조회 (S15P21A104-309).
 *
 * <p>AI 는 09-17 부터 v4-weather-final LightGBM 으로 "지금 재고 + N분 뒤 순증감" 을 실시간으로 준다(티켓 160).
 * AI 쪽 계약(`AI/app/BIKE/router.py`)이 "BE 가 조회 때마다 부르고, 실패하면 자기 DB 배치 통계로 폴백" 이다.
 *
 * <p><b>예외를 밖으로 던지지 않는다. 모델 값을 못 쓰면 빈 값이다</b> — 빈 값이면 도착 예측은 지금처럼 평균표로 나간다.
 * 빈 값이 되는 경우:
 * <ul>
 *   <li>도착까지 {@code maxMinutes} 초과 또는 이미 지남 — 모델은 30분 앞까지 학습했고 그 너머는 30분으로 근사한다.
 *       멀리 떨어진 도착에 "지금 재고 + 30분" 을 붙이면 평균보다 나을 근거가 없다. 이때는 부르지도 않는다</li>
 *   <li>호출 실패 — 404(실시간 재고 없음)·503(모델 장애)·타임아웃·연결 실패</li>
 *   <li>응답이 JSON 이 아니거나 필요한 값({@code predicted_stock}·{@code p_empty})이 없음</li>
 *   <li>{@code source} 가 {@code lightgbm} 이 아님 — 학습에 없던 대여소는 AI 가 전역 평균
 *       ({@code lightgbm_global_fallback})을 주는데, 우리 평균표는 대여소별이라 그쪽이 낫다</li>
 * </ul>
 *
 * <p>재시도는 하지 않는다. 사용자 요청 안에서 도는 조회라 한 번 실패하면 평균표로 넘기는 편이 낫다(버스 혼잡도 297 과 같다).
 */
@Slf4j
public class BikeEtaReader {

    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() {
    };
    private static final String MODEL_SOURCE = "lightgbm";

    private final HttpFetcher fetcher;
    private final JsonMapper mapper;
    private final Clock clock;
    private final String baseUrl;
    private final int maxMinutes;

    /**
     * @param baseUrl    AI 서버 주소 (예: {@code http://100.64.193.109:8000}). 끝의 {@code /} 는 떼어 쓴다
     * @param maxMinutes 이 분을 넘는 도착에는 부르지 않는다
     */
    public BikeEtaReader(HttpFetcher fetcher, JsonMapper mapper, Clock clock, String baseUrl, int maxMinutes) {
        this.fetcher = fetcher;
        this.mapper = mapper;
        this.clock = clock;
        this.baseUrl = baseUrl == null ? null : baseUrl.replaceAll("/+$", "");
        this.maxMinutes = maxMinutes;
    }

    /** AI 주소가 없을 때 쓰는 리더. 항상 빈 값이다 — 배포 순서가 뒤집혀도 도착 예측이 깨지지 않는다. */
    public static BikeEtaReader disabled() {
        return new BikeEtaReader(null, null, null, null, -1);
    }

    public Optional<BikeEtaStock> find(String rentalId, OffsetDateTime arrival) {
        if (fetcher == null) {
            return Optional.empty();
        }
        // FE 가 new Date() 로 읽는다 — JS 표준 ISO 는 소수 3자리까지라 밀리초로 자른다.
        OffsetDateTime now = OffsetDateTime.now(clock).truncatedTo(ChronoUnit.MILLIS);
        long etaMinutes = Math.round(Duration.between(now, arrival).toSeconds() / 60.0);
        if (etaMinutes < 0 || etaMinutes > maxMinutes) {
            return Optional.empty();
        }
        URI uri = URI.create(baseUrl + "/bike/stations/" + URLEncoder.encode(rentalId, StandardCharsets.UTF_8)
                + "/eta-stock?eta_minutes=" + etaMinutes);
        try {
            return toStock(mapper.readValue(fetcher.get(uri), MAP), now);
        } catch (SourceCallException e) {
            log.warn("따릉이 실시간 예측 호출 실패 — 평균표로 대신한다: {}", e.getMessage());
            return Optional.empty();
        } catch (JacksonException e) {
            log.warn("따릉이 실시간 예측 응답을 읽지 못함 — 평균표로 대신한다: {} ({})", uri, e.getOriginalMessage());
            return Optional.empty();
        }
    }

    private static Optional<BikeEtaStock> toStock(Map<String, Object> body, OffsetDateTime now) {
        if (body == null || !MODEL_SOURCE.equals(body.get("source"))
                || !(body.get("predicted_stock") instanceof Number predicted)
                || !(body.get("p_empty") instanceof Number pEmpty)) {
            return Optional.empty();
        }
        int bikes = (int) Math.round(Math.max(0.0, predicted.doubleValue()));
        double probability = Math.min(1.0, Math.max(0.0, 1.0 - pEmpty.doubleValue()));
        return Optional.of(new BikeEtaStock(bikes, probability, now));
    }
}
