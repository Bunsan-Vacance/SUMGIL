package com.ssafy.s15p21a104.collect;

import java.util.List;

/**
 * 기동 시 확정된 폴러 목록. 활성화됐고 인증키가 있는 소스만 들어간다.
 * List 빈은 원소 타입 주입과 헷갈리므로 레코드로 감싼다.
 */
public record CollectPlan(List<SourcePoller> pollers) {

    public CollectPlan {
        pollers = List.copyOf(pollers);
    }
}
