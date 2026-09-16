package com.ssafy.s15p21a104.consume;

/**
 * 배치 하나를 반영한 결과 (S15P21A104-171). 회차마다 로그로 남겨 "받고는 있는데 안 써지는" 상태를 눈에 보이게 한다.
 *
 * @param written  Redis 에 실제로 쓴 건수
 * @param skipped  건너뛴 건수 — 오래된 이벤트(멱등), 중복, 값이 깨진 행
 * @param unmapped 역 대응표에 없어 버린 건수 (지하철만. 따릉이는 매핑이 없어 항상 0)
 */
public record ApplyResult(int written, int skipped, int unmapped) {

    public static final ApplyResult NOTHING = new ApplyResult(0, 0, 0);

    public ApplyResult plus(ApplyResult other) {
        return new ApplyResult(written + other.written, skipped + other.skipped, unmapped + other.unmapped);
    }
}
