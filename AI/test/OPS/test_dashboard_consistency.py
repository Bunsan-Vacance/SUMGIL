"""Grafana 대시보드 구성 드리프트 방지 — 정본·Infra 복사본·프로비저닝·버전 핀·라우트를 정적으로 대조한다.

실제로 겪은 사고를 막는 것이 목적이다.
(a) Infra 복사본이 정본과 어긋남, (b) Infinity 플러그인 버전 미고정으로 4.x가 설치돼
Grafana 11.6.0에서 패널이 전부 깨짐, (c) 패널이 프로비저닝되지 않은 datasource uid를 참조.
Grafana·Docker 없이 파일만 읽으므로 CI(`cd AI && pytest -q`)에서 그대로 돈다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from app.main import app

ROOT = Path(__file__).resolve().parents[3]
CANON = ROOT / "AI" / "validation" / "INFRA" / "observability-check"
INFRA = ROOT / "Infra" / "k8s" / "ops"
CANON_DASH = CANON / "grafana" / "dashboards"
INFRA_DASH = INFRA / "grafana" / "dashboards"
DS_FILES = [
    CANON / "grafana" / "provisioning" / "datasources" / "datasources.yml",
    INFRA / "grafana" / "provisioning" / "datasources.yml",
]
SYNC_HINT = "Infra/k8s/ops/sync-dashboards.sh 를 실행해 정본을 복사하고 같이 커밋하라"
EXPECTED_UIDS = {
    "sumgil-model-quality",
    "sumgil-pipeline-health",
    "sumgil-spark-jobs",
    "sumgil-data-quality",
}
BUILTIN_DS = {"-- Grafana --", "-- Mixed --", "-- Dashboard --", "grafana"}
DASH_NAMES = sorted(p.name for p in CANON_DASH.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_panels(panels: list[dict]):
    for panel in panels:
        yield panel
        yield from _walk_panels(panel.get("panels", []))


def _datasource_refs(board: dict) -> list[tuple[str, dict]]:
    """(위치 설명, datasource 객체) — 패널과 targets[] 모두."""
    refs = []
    for panel in _walk_panels(board.get("panels", [])):
        title = panel.get("title", "?")
        if isinstance(panel.get("datasource"), dict):
            refs.append((f"패널 '{title}'", panel["datasource"]))
        for target in panel.get("targets", []):
            if isinstance(target.get("datasource"), dict):
                refs.append((f"패널 '{title}' target", target["datasource"]))
    return refs


def _targets(board: dict):
    for panel in _walk_panels(board.get("panels", [])):
        for target in panel.get("targets", []):
            yield panel.get("title", "?"), target


def _provisioned(path: Path) -> dict[str, str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {d["uid"]: d["type"] for d in doc["datasources"]}


def _containers(path: Path) -> list[dict]:
    """멀티 문서 YAML 매니페스트의 모든 컨테이너 스펙."""
    out = []
    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        spec = ((doc or {}).get("spec", {}).get("template", {}) or {}).get("spec", {})
        out.extend(spec.get("containers", []))
    return out


def _k8s_image(manifest: str, container: str) -> str:
    for c in _containers(INFRA / manifest):
        if c["name"] == container:
            return c["image"]
    pytest.fail(f"Infra/k8s/ops/{manifest} 에 컨테이너 '{container}' 가 없다")


def _compose() -> dict:
    return yaml.safe_load((CANON / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _tag(image: str) -> str:
    last = image.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else ""


def _infinity_version(plugins: str) -> str:
    m = re.search(r"yesoreyeram-infinity-datasource\s+(\S+)", plugins)
    assert m, f"GF_INSTALL_PLUGINS 에 버전이 명시된 Infinity 플러그인이 없다: {plugins!r}"
    return m.group(1)


def _k8s_plugins() -> str:
    for c in _containers(INFRA / "grafana.yaml"):
        for env in c.get("env", []):
            if env["name"] == "GF_INSTALL_PLUGINS":
                return env["value"]
    pytest.fail("Infra/k8s/ops/grafana.yaml 에 GF_INSTALL_PLUGINS 가 없다")


def test_1_정본과_복사본_파일_집합과_내용이_같다():
    infra_names = sorted(p.name for p in INFRA_DASH.glob("*.json"))
    assert infra_names == DASH_NAMES, f"대시보드 파일 목록이 다르다. {SYNC_HINT}"
    for name in DASH_NAMES:
        same = (CANON_DASH / name).read_bytes() == (INFRA_DASH / name).read_bytes()
        assert same, f"{name} 복사본이 정본과 다르다. {SYNC_HINT} (복사본을 직접 고치지 않는다)"


@pytest.mark.parametrize("name", DASH_NAMES)
@pytest.mark.parametrize("ds_file", DS_FILES, ids=["정본", "Infra"])
def test_2_대시보드의_datasource_uid가_프로비저닝돼_있다(name, ds_file):
    known = set(_provisioned(ds_file))
    for where, ds in _datasource_refs(_load(CANON_DASH / name)):
        uid = ds.get("uid")
        if not uid or uid in BUILTIN_DS or uid.startswith("$"):
            continue
        assert uid in known, (
            f"{name} {where} 의 datasource uid '{uid}' 가 {ds_file.relative_to(ROOT)} 에 없다 "
            f"(프로비저닝된 uid: {sorted(known)}). uid 를 맞추거나 데이터소스를 추가하라"
        )


def test_2_두_프로비저닝의_uid_type_쌍이_같다():
    canon, infra = (_provisioned(p) for p in DS_FILES)
    assert canon == infra, (
        f"데이터소스 (uid, type) 가 정본 {canon} 과 Infra {infra} 에서 다르다. "
        "url 만 환경별로 달라야 한다 - uid·type 을 맞춰라"
    )


def test_3_grafana_이미지_태그가_고정되고_같다():
    compose = _compose()["grafana"]["image"]
    k8s = _k8s_image("grafana.yaml", "grafana")
    for where, image in (("docker-compose.yml", compose), ("grafana.yaml", k8s)):
        assert _tag(image) not in (
            "",
            "latest",
        ), f"{where} 의 Grafana 이미지 태그를 고정하라: {image}"
    assert compose == k8s, f"Grafana 이미지가 compose({compose}) 와 grafana.yaml({k8s}) 에서 다르다"


def test_3_infinity_플러그인_버전이_명시되고_같다():
    plugins = _compose()["grafana"]["environment"]["GF_INSTALL_PLUGINS"]
    v_compose = _infinity_version(plugins)
    v_k8s = _infinity_version(_k8s_plugins())
    assert v_compose == v_k8s, (
        f"Infinity 버전이 compose({v_compose}) 와 grafana.yaml({v_k8s}) 에서 다르다. "
        "Grafana 11.6.0 은 Infinity 3.x 만 지원하므로 둘 다 같은 값으로 고정하라"
    )


@pytest.mark.parametrize(
    ("service", "manifest"),
    [("prometheus", "prometheus.yaml"), ("node-exporter", "node-exporter.yaml")],
)
def test_3_prometheus_계열_이미지가_같다(service, manifest):
    compose = _compose()[service]["image"]
    k8s = _k8s_image(manifest, service)
    assert compose == k8s, f"{service} 이미지가 compose({compose}) 와 {manifest}({k8s}) 에서 다르다"


def test_4_대시보드_uid가_비어있지_않고_고유하며_기대값과_같다():
    uids = []
    for name in DASH_NAMES:
        uid = _load(CANON_DASH / name).get("uid")
        assert uid, f"{name} 에 uid 가 없다"
        uids.append(uid)
    assert len(uids) == len(set(uids)), f"대시보드 uid 가 중복이다: {uids}"
    assert set(uids) == EXPECTED_UIDS, (
        f"대시보드 uid {sorted(uids)} 가 기대값 {sorted(EXPECTED_UIDS)} 와 다르다 "
        "(FE 링크·문서가 이 uid 를 참조한다)"
    )


def _route_regexes() -> list[re.Pattern]:
    # app.routes 는 include_router 결과를 래퍼로 감싸 path 가 없을 수 있어 OpenAPI 경로를 쓴다
    paths = list(app.openapi()["paths"])
    return [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$") for p in paths]


@pytest.mark.parametrize("name", DASH_NAMES)
def test_5_infinity_url이_실제_라우트와_맞는다(name):
    regexes = _route_regexes()
    for title, target in _targets(_load(CANON_DASH / name)):
        if target.get("datasource", {}).get("uid") != "infinity-ai":
            continue
        url = target.get("url", "")
        assert url, f"{name} 패널 '{title}' 의 Infinity target 에 url 이 없다"
        path = urlsplit(url).path  # 쿼리 문자열(${days} 등)은 버린다
        assert any(rx.match(path) for rx in regexes), (
            f"{name} 패널 '{title}' 의 URL 경로 '{path}' 가 app.main.app 의 어느 라우트와도 맞지 않는다. "
            "AI/app/ops/router.py 의 경로와 맞춰라"
        )


def _ai_source_text() -> str:
    parts = []
    for p in (ROOT / "AI").rglob("*.py"):
        rel = p.relative_to(ROOT / "AI").parts
        if rel[0] in ("test", "validation") or any(
            x in rel for x in (".venv", "venv", "site-packages")
        ):
            continue
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


@pytest.mark.parametrize("name", DASH_NAMES)
def test_6_promql_지표_이름이_emitter에_있다(name):
    source = _ai_source_text()
    for title, target in _targets(_load(CANON_DASH / name)):
        for metric in re.findall(r"sumgil_[a-z0-9_]+", target.get("expr", "")):
            base = re.sub(r"_(bucket|sum|count|total)$", "", metric)
            assert metric in source or base in source, (
                f"{name} 패널 '{title}' 의 지표 '{metric}' 를 AI 소스(예: DATA_ENGINE/observability/"
                "export_textfile.py)에서 찾지 못했다. 지표 이름을 맞춰라"
            )
