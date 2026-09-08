package com.ssafy.s15p21a104.domain.station.entity;

import jakarta.persistence.Column;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "transfer_meta")
public class TransferMeta {

    @EmbeddedId
    private TransferMetaId id;

    @Column(name = "walk_sec", nullable = false)
    private Integer walkSec;

    @Column(name = "stair_count")
    private Integer stairCount;

    @Column(name = "has_elevator")
    private Boolean hasElevator;

    @Column(name = "outdoor", nullable = false)
    private Boolean outdoor;

    @Column(name = "source", length = 16, nullable = false)
    private String source;
}
