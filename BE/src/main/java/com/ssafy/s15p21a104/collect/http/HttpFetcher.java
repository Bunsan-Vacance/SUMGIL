package com.ssafy.s15p21a104.collect.http;

import java.net.URI;

/**
 * 외부 API 1회 GET. 소스 어댑터가 HTTP 클라이언트에 직접 붙지 않게 하는 얇은 경계다 —
 * 테스트에서는 저장된 샘플(docs/external/samples)을 돌려주는 가짜로 바꿔 호출 0회로 검증한다 (api-survey 4절 결정 4).
 */
public interface HttpFetcher {

    /**
     * @return 응답 본문 (2xx 일 때만)
     * @throws SourceCallException 타임아웃·IO 오류·4xx·5xx. {@link SourceCallException#retryable()} 로 재시도 여부를 가른다
     */
    String get(URI uri);
}
