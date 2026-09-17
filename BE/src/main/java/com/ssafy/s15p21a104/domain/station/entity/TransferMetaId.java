package com.ssafy.s15p21a104.domain.station.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.io.Serializable;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@EqualsAndHashCode
@Embeddable
public class TransferMetaId implements Serializable {

    @Column(name = "station_id", length = 24)
    private String stationId;

    @Column(name = "from_line", length = 16)
    private String fromLine;

    @Column(name = "to_line", length = 16)
    private String toLine;
}
