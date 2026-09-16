"""getStnPsgr D−1 수집기 — 페이지 합치기·봉투 파싱·슬롯 매핑·합산·날짜 교체. 외부 호출 없음."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from DATA_ENGINE.collect import subway_ridership_daily as m


def _row(
    hour: str,
    stn: str = "0222",
    card: str = "1",
    user: str = "01",
    ride: int = 1,
    gff: int = 2,
    day: str = "20260911",
):
    return {
        "pasngDe": day,
        "pasngHr": hour,
        "lineNm": "2호선",
        "stnCd": stn,
        "stnNo": "222",
        "stnNm": "강남",
        "trnscdSeCd": card,
        "trnscdSeCdNm": "선불카드",
        "trnscdUserSeCd": user,
        "trnscdUserSeCdNm": "일반",
        "rideNope": ride,
        "gffNope": gff,
        "crtrYmd": day,
    }


def _body(rows, total, page_no=1):
    return {"items": {"item": rows}, "pageNo": page_no, "numOfRows": len(rows), "totalCount": total}


def test_hour_to_slot_mapping():
    assert m.hour_to_slot(0) == "24~" and m.hour_to_slot(3) == "24~"
    assert m.hour_to_slot(4) == "~06" and m.hour_to_slot(5) == "~06"
    assert m.hour_to_slot(6) == "06-07" and m.hour_to_slot(23) == "23-24"
    with pytest.raises(ValueError):
        m.hour_to_slot(24)
    assert set(m.HOUR_TO_SLOT.values()) <= set(
        __import__("app.CROWD.pipeline.features", fromlist=["SLOT_ORDER"]).SLOT_ORDER
    )


def test_parse_response_rejects_text_error_and_bad_code():
    with pytest.raises(RuntimeError, match="ERROR-336"):
        m._parse_response("<RESULT><CODE>ERROR-336</CODE><MESSAGE>too many</MESSAGE></RESULT>")
    with pytest.raises(RuntimeError, match="resultCode=99"):
        m._parse_response(
            '{"response": {"header": {"resultCode": "99", "resultMsg": "x"}, "body": {}}}'
        )
    body = m._parse_response(
        '{"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 0, "items": ""}}}'
    )
    assert body["totalCount"] == 0 and m._body_rows(body) == []


def test_fetch_day_pages_and_zero(monkeypatch):
    calls = []

    def fake_page(day, start, end):
        calls.append((start, end))
        if day == "20260904":
            return _body([], 0)
        total = 5
        rows = [_row("07", stn=f"{start + i:04d}") for i in range(min(2, total - start + 1))]
        return _body(rows, total)

    monkeypatch.setattr(m, "_fetch_page", fake_page)
    df = m.fetch_day("20260911", page_size=2)
    assert calls == [(1, 2), (3, 4), (5, 5)]
    assert len(df) == 5 and list(df.columns[:13]) == m.RAW_COLUMNS
    assert m.fetch_day("20260904", page_size=2).empty


def test_to_long_sums_card_and_user_types():
    raw = pd.DataFrame(
        [
            _row("07", card="1", user="01", ride=10, gff=20),
            _row("07", card="2", user="04", ride=5, gff=1),
            _row("00", ride=3, gff=9),
            _row("05", ride=7, gff=0),
        ]
    )
    lg = m.to_long(raw, collected_at=pd.Timestamp("2026-09-12 09:00"))
    assert list(lg.columns) == [*m.LONG_COLUMNS, "source", "collected_at"]
    assert lg["station_no"].dtype == "int64" and lg["station_no"].iloc[0] == 222
    piv = lg.pivot_table(index="time_slot", columns="direction", values="passengers", aggfunc="sum")
    assert piv.loc["07-08", "boarding"] == 15 and piv.loc["07-08", "alighting"] == 21
    assert piv.loc["24~", "boarding"] == 3 and piv.loc["~06", "boarding"] == 7
    assert lg["date"].dt.strftime("%Y%m%d").eq("20260911").all()
    assert m.to_long(pd.DataFrame(columns=m.RAW_COLUMNS)).empty


def test_merge_recent_replaces_same_date_and_keeps_others():
    old = m.to_long(
        pd.DataFrame(
            [
                _row("07", ride=1, gff=1, day="20260910"),
                _row("07", ride=100, gff=100, day="20260911"),
            ]
        )
    )
    new = m.to_long(pd.DataFrame([_row("07", ride=5, gff=5, day="20260911")]))
    merged = m.merge_recent(old, new)
    assert sorted(merged["date"].dt.strftime("%Y%m%d").unique()) == ["20260910", "20260911"]
    assert merged.loc[merged["date"] == "2026-09-11", "passengers"].tolist() == [5.0, 5.0]
    assert m.merge_recent(None, new).equals(new.reset_index(drop=True))


def test_run_writes_raw_and_recent_long(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "CROWD_RAW_DAILY", tmp_path / "raw")
    monkeypatch.setattr(m, "RECENT_LONG", tmp_path / "interim" / "recent.parquet")

    def fake_fetch(day, page_size=m.PAGE_SIZE):
        if day == "20260904":
            return pd.DataFrame(columns=m.RAW_COLUMNS)
        return pd.DataFrame([_row("08", ride=int(day[-2:]), gff=1, day=day)])

    monkeypatch.setattr(m, "fetch_day", fake_fetch)
    out = m.run(["20260911", "20260904"])
    assert (tmp_path / "raw" / "dt=2026-09-11" / "getStnPsgr.parquet").exists()
    assert not (tmp_path / "raw" / "dt=2026-09-04").exists()
    assert out["date"].nunique() == 1
    # 두 번째 실행: 이미 있는 20260911은 건너뛰고(호출 없음) 20260910만 추가
    fetched = []
    monkeypatch.setattr(
        m, "fetch_day", lambda day, page_size=m.PAGE_SIZE: (fetched.append(day), fake_fetch(day))[1]
    )
    out2 = m.run(["20260910", "20260911"])
    assert fetched == ["20260910"]
    assert (
        out2["date"].nunique() == 2
        and pd.read_parquet(tmp_path / "interim" / "recent.parquet")["date"].nunique() == 2
    )
    # --refetch면 둘 다 다시 받아 교체
    fetched.clear()
    m.run(["20260910", "20260911"], refetch=True)
    assert fetched == ["20260910", "20260911"]


def test_default_days_is_yesterday_back_n():
    days = m.default_days(3, today=date(2026, 9, 13))
    assert days == ["20260912", "20260911", "20260910"]
