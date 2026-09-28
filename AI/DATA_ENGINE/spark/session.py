"""Spark 세션 빌더 (274) — 273 벤치의 설정을 서버 실제 자원에 맞춰 정식화한다.

273(`validation/INFRA/spark-bike-candidates-check`)의 로컬 벤치는 22코어·`driver.memory=8g`로
쟀다. 실제 배포 대상인 EC2 야간창은 팀원 제안서 기준 **3코어·4GB**뿐이다 — 이 기본값은 로컬
벤치 그대로 옮기면 안 되고, 배포 전 반드시 서버 자원으로 다시 재야 한다(`RESULTS.md` "서버
실측" 절 예정, 아직 미기록).

`shuffle.partitions=32`는 165 §2.6에서 기본값 200 대비 32% 개선을 실측한 값이다(단일 머신
기준, 코어 수가 3개뿐인 서버에서는 재검증 필요 — 파티션이 코어 수보다 너무 많으면 오히려
오버헤드가 커진다).

`session.timeZone=Asia/Seoul`은 273에서 실측으로 확인한 필수 설정이다 — bike.stock raw
컬럼(`ingested_at` 등)이 이미 Asia/Seoul tz-aware로 parquet에 저장돼 있어서, 세션 타임존을
안 맞추면 `hour()`/`dayofweek()` 계산이 pandas(KST 기준)와 어긋난다(273에서 이걸 놓쳐서
정확도 검증이 두 번 실패했다 — RESULTS.md 4번 참고).
"""

from __future__ import annotations

DEFAULT_CORES = "3"
DEFAULT_DRIVER_MEMORY = "3g"
DEFAULT_SHUFFLE_PARTITIONS = "32"


def build_spark_session(
    app_name: str,
    *,
    cores: str = DEFAULT_CORES,
    driver_memory: str = DEFAULT_DRIVER_MEMORY,
    shuffle_partitions: str = DEFAULT_SHUFFLE_PARTITIONS,
):
    """`local[{cores}]` SparkSession을 만든다. torch·PySpark 규약대로 이 함수 안에서만
    `pyspark`를 import한다 — 모듈 최상단 import로 무거운 의존성이 번지지 않게 한다."""
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.appName(app_name)
        .master(f"local[{cores}]")
        .config("spark.driver.memory", driver_memory)
        .config("spark.sql.shuffle.partitions", shuffle_partitions)
        .config("spark.sql.session.timeZone", "Asia/Seoul")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
