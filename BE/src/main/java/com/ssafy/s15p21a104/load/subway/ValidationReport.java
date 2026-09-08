package com.ssafy.s15p21a104.load.subway;

import java.util.List;

/** errors 가 하나라도 있으면 적재하지 않는다. warnings 는 로그로 남기고 진행한다. */
public record ValidationReport(List<String> errors, List<String> warnings) {

    public boolean ok() {
        return errors.isEmpty();
    }
}
