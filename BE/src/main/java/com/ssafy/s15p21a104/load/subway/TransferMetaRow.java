package com.ssafy.s15p21a104.load.subway;

/** transfer_meta 테이블 1행. source 는 extract(원천 파일) | manual(수동 입력). */
public record TransferMetaRow(String stationId, String fromLine, String toLine, int walkSec, String source) {
}
