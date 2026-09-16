package com.ssafy.s15p21a104.load;

import java.util.List;

/**
 * 적재 전 검증 결과. errors 가 하나라도 있으면 적재하지 않는다. warnings 는 로그로 남기고 진행한다.
 * 지하철(LoadValidator)·버스·따릉이(MasterValidator) 검증기가 함께 쓴다.
 */
public record ValidationReport(List<String> errors, List<String> warnings) {

    public boolean ok() {
        return errors.isEmpty();
    }
}
