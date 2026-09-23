import pytest

pyspark = pytest.importorskip("pyspark")

from DATA_ENGINE.spark.session import build_spark_session


def test_build_spark_session_applies_expected_config():
    spark = build_spark_session(
        "test-session", cores="1", driver_memory="1g", shuffle_partitions="4"
    )
    try:
        assert spark.conf.get("spark.sql.shuffle.partitions") == "4"
        assert spark.conf.get("spark.sql.session.timeZone") == "Asia/Seoul"
        # 간단한 쿼리로 세션이 실제로 도는지 확인한다(설정값만 보고 끝내지 않는다).
        assert spark.range(3).count() == 3
    finally:
        spark.stop()
