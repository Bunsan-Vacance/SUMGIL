package com.ssafy.s15p21a104.collect.source;

import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

/** 호출 0회 검증용 가짜 (api-survey 4절 결정 4). URL 을 기록하고 미리 정한 본문을 돌려준다. */
final class FakeFetcher implements HttpFetcher {

    final List<URI> calls = new ArrayList<>();
    private final Function<URI, String> bodies;

    FakeFetcher(Function<URI, String> bodies) {
        this.bodies = bodies;
    }

    static FakeFetcher always(String body) {
        return new FakeFetcher(uri -> body);
    }

    /** 호출 순서대로 본문을 돌려준다. 준비한 것보다 많이 부르면 실패. */
    static FakeFetcher sequence(String... bodies) {
        List<String> list = List.of(bodies);
        int[] index = {0};
        return new FakeFetcher(uri -> {
            if (index[0] >= list.size()) {
                throw new AssertionError("준비한 응답 " + list.size() + "개보다 많이 호출했다: " + uri);
            }
            return list.get(index[0]++);
        });
    }

    static FakeFetcher failing(SourceCallException e) {
        return new FakeFetcher(uri -> {
            throw e;
        });
    }

    @Override
    public String get(URI uri) {
        calls.add(uri);
        return bodies.apply(uri);
    }
}
