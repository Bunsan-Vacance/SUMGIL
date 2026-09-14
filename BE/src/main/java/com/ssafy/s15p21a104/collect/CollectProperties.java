package com.ssafy.s15p21a104.collect;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 수집기 실행 옵션. 기본값은 application-collect.yml 에 있고 환경변수·명령행 --collect.* 로 덮어쓴다.
 *
 * @param dryRun  true 면 외부 API 는 호출하되 Kafka 에 보내지 않고 로그만 남긴다 (Kafka 빈 자체를 만들지 않는다).
 *                브로커 없이 호출·파싱만 확인할 때 쓴다
 * @param runOnce true 면 활성 소스를 한 회차씩만 돌리고 끝낸다 (스키마 확인·배포 전 점검용). false 면 주기 실행
 * @param kafka   브로커 주소·전송 대기 한계
 * @param topics  토픽 3개에 공통으로 거는 보관 정책 (S15P21A104-168)
 * @param http    외부 API 호출 타임아웃·재시도 (NFR-EXT-002: 타임아웃·5xx 만 최대 2회)
 * @param budget  소스별 하루 호출 예산. 열린데이터광장 키가 하루 1,000회라 그 안에서만 돈다 (S15P21A104-170)
 * @param subway  지하철 실시간 도착 (OA-15799) 설정
 * @param bike    따릉이 대여소 재고 bikeList (OA-15493) 설정
 * @param weather 기상청 초단기 실황·예보 (API허브) 설정
 */
@ConfigurationProperties("collect")
public record CollectProperties(boolean dryRun, boolean runOnce, Kafka kafka, Topics topics, Http http, Budget budget,
                                Source subway, Source bike, Weather weather) {

    public CollectProperties {
        if (kafka == null) {
            kafka = new Kafka(null, null);
        }
        if (topics == null) {
            topics = new Topics(0, 0);
        }
        if (http == null) {
            http = new Http(null, null, -1);
        }
        if (budget == null) {
            budget = new Budget(0);
        }
    }

    /**
     * @param bootstrapServers 브로커 주소. 로컬 compose 는 localhost:9092, 클러스터 파드는 kafka:9092
     * @param sendTimeout      한 회차 이벤트 전송 완료를 기다리는 한계
     */
    public record Kafka(String bootstrapServers, Duration sendTimeout) {
        public Kafka {
            if (bootstrapServers == null || bootstrapServers.isBlank()) {
                bootstrapServers = "localhost:9092";
            }
            if (sendTimeout == null) {
                sendTimeout = Duration.ofSeconds(30);
            }
        }
    }

    /**
     * @param retentionHours 토픽 보관 시간. 48h — prod 볼륨 5Gi 에 기본값 7일은 넘친다 (168 티켓 본문 계산)
     * @param segmentHours   세그먼트 롤링 주기. 보관 삭제는 닫힌 세그먼트 단위라 이 값이 커지면 보관 시간이 그만큼 늘어난다
     */
    public record Topics(int retentionHours, int segmentHours) {
        public Topics {
            if (retentionHours <= 0) {
                retentionHours = 48;
            }
            if (segmentHours <= 0) {
                segmentHours = 6;
            }
        }
    }

    /**
     * @param connectTimeout TCP 연결 한계. 실습실 망에서 8088 이 막혀 있으면 여기서 걸린다
     * @param readTimeout    응답 완료 한계. bikeList 1페이지가 실측 1.2초·194KB 라 사용자 요청용 2초 통일값보다 여유를 둔다
     * @param maxRetries     타임아웃·5xx 재시도 횟수 (4xx 는 재시도하지 않는다)
     */
    public record Http(Duration connectTimeout, Duration readTimeout, int maxRetries) {
        public Http {
            if (connectTimeout == null) {
                connectTimeout = Duration.ofSeconds(2);
            }
            if (readTimeout == null) {
                readTimeout = Duration.ofSeconds(5);
            }
            if (maxRetries < 0) {
                maxRetries = 2;
            }
        }
    }

    /** @param dailyCalls 소스별 하루 호출 상한. 예산이 다 차면 그날은 폴링을 멈춘다 */
    public record Budget(int dailyCalls) {
        public Budget {
            if (dailyCalls <= 0) {
                dailyCalls = 1000;
            }
        }
    }

    /**
     * @param enabled        false 면 이 소스는 폴링하지 않는다 (토픽은 그래도 만든다)
     * @param topic          이벤트를 넣을 토픽. source 필드 값으로도 쓴다
     * @param interval       회차 간격. 이전 회차 종료 시점부터 잰다(fixed delay) — 회차가 길어져도 호출이 몰리지 않는다
     * @param window         운영 시간 창 "HH:mm-HH:mm" (KST). 창 밖에서는 호출하지 않는다. 00:00-24:00 이면 하루 종일
     * @param retentionBytes 토픽 보관 상한(바이트). 파티션 1이라 토픽 전체 상한과 같다
     * @param key            인증키. 비어 있으면 이 소스는 기동 시 비활성화된다
     */
    public record Source(boolean enabled, String topic, Duration interval, String window, long retentionBytes,
                         String key) {

        public boolean hasKey() {
            return key != null && !key.isBlank();
        }
    }

    /** {@link Source} 에 격자 좌표를 더한 것. 기본값 서울 종로구 nx=60 ny=127 (AI 폴러 weather_nowcast.py 와 같다). */
    public record Weather(boolean enabled, String topic, Duration interval, String window, long retentionBytes,
                          String key, int nx, int ny) {
        public Weather {
            if (nx <= 0) {
                nx = 60;
            }
            if (ny <= 0) {
                ny = 127;
            }
        }

        public Source asSource() {
            return new Source(enabled, topic, interval, window, retentionBytes, key);
        }
    }
}
