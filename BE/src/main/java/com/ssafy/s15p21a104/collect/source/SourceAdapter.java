package com.ssafy.s15p21a104.collect.source;

import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.time.OffsetDateTime;

/**
 * 외부 소스 하나를 한 회차 폴링해 이벤트로 바꾸는 어댑터. 호출·파싱·이벤트 변환까지만 하고
 * 주기·시간 창·예산·전송은 {@code SourcePoller} 가 맡는다 — 어댑터는 "어디서 무엇을 어떻게 읽는가"만 안다.
 */
public interface SourceAdapter {

    /** 이벤트를 넣을 토픽. 이벤트의 source 필드 값으로도 쓴다. */
    String topic();

    /** 한 회차에 계획된 호출 수. 예산 확인용(재시도는 별도로 센다). */
    int callsPerRun();

    /**
     * @param pollRunAt 이 회차의 시각. 회차 안의 모든 이벤트가 같은 값을 갖는다
     * @throws SourceCallException 호출·응답 코드·파싱 실패. 부분 결과는 돌려주지 않는다 — 오류 응답에 섞인 데이터를 성공으로 오해하지 않기 위해서다
     */
    PollResult poll(OffsetDateTime pollRunAt);
}
