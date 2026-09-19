# AI 서빙 — EC2 배포·운영 (S15P21A104-160)

작성 2026-09-17. `app/main.py`(FastAPI, `CROWD`+`BIKE` 전체 서빙 게이트웨이)를 두 번째 EC2에 올리고
`ai-api` systemd 서비스로 상시 구동시킨 절차·운영 방법을 담는다. [Infra/README.md](../Infra/README.md)가
다루는 k3s 클러스터(BE·FE·Postgres·Redis, EC2 2대: control-plane/worker)와는 **별개의 서버**다 —
AI·DATA_ENGINE 쪽은 k3s에 안 올라가고, 아래 서버에서 systemd로 직접 돈다.

## 0. 서버 정보

| 항목 | 값 |
| --- | --- |
| 접속 | `ssh -i <pem> ubuntu@j15a104a.p.ssafy.io` (내부 호스트명 `ip-172-26-10-6`) |
| 저장소 경로 | `~/Soomgil-INFRA-ai-data-monitoring/AI` |
| Python venv | `~/Soomgil-INFRA-ai-data-monitoring/AI/.venv` (3.12) |
| **git clone 아님** | `.git`이 상위 폴더(`~/Soomgil-INFRA-ai-data-monitoring/`)에 있고 커밋 0개·리모트 0개 — 이 서버의 파일은 전부 untracked, 애초에 `git clone`이 아니라 수동 업로드로 배포됐다. **`git fetch`/`checkout`/`pull`로 갱신 시도하지 말 것** — 코드 배포는 1절처럼 파일 단위 `scp`로 한다. |

## 1. 코드 배포 — `scp`, git 아님

이 서버의 `AI/` 파일들은(다른 팀원의 카프카 컨슈머·avg 배치 산출물 포함) git 이력과 무관하게 직접 얹혀 있는
상태라, `git push`/`pull` 기반 배포를 쓸 수 없다. **바뀐 파일만 골라 로컬→서버로 직접 `scp`한다.**

```powershell
# 로컬 PowerShell — $key(pem 경로)·$server(ubuntu@j15a104a.p.ssafy.io)·$ai(로컬 AI 폴더) 변수 사용
scp -i $key "$ai\app\BIKE\service.py" ${server}:~/Soomgil-INFRA-ai-data-monitoring/AI/app/BIKE/service.py
```

- **한 줄에 scp 명령 두 개를 붙여서 실행하지 않는다.** 개행 없이 이어 붙으면 인자가 서로 섞여
  scp가 목적지를 디렉터리로 잘못 생성하는 사고가 난다(실제로 `predictor_eta.py`가 파일 대신 빈
  디렉터리로 만들어졌던 사례 — `rm -rf`로 지우고 한 줄씩 다시 실행해서 해결).
- 새 파일을 처음 올릴 때 목적지 디렉터리가 없으면 `scp`가 실패한다. 먼저 서버에서
  `mkdir -p <디렉터리>`. 폴더 통째로 올릴 때(`scp -r`, 모델 아티팩트 등)는 부모 디렉터리만
  있으면 leaf 디렉터리는 자동 생성된다.
- **어느 파일을 올려야 하는지 확신이 안 서면**, 로컬에서 브랜치 diff로 확인한다:
  ```bash
  git diff --name-only $(git merge-base HEAD origin/main) HEAD -- AI/app/
  ```
  단, 이 서버가 애초에 `main`보다도 오래된 코드로 배포돼 있을 수 있다(실제로 `schemas.py`·
  `calendar.py`가 그랬다 — 브랜치 diff엔 안 잡히는데 서버엔 없었음). import 에러가 나면 그 모듈을
  추가로 올린다.
- **다른 팀원이 같은 파일(`config.py` 등)을 고치고 있다면, scp 전에 로컬에서 `develop-AI`를
  먼저 merge**해서 두 변경사항이 다 반영된 버전을 올린다 — 안 그러면 우리가 올리는 순간 팀원이
  이미 서버에 올려둔 변경사항이 지워진다.

## 2. 모델 아티팩트·데이터 파일 배포

`AI/models/`·`AI/data/`는 `.gitignore` 대상이라 애초에 git으로 옮길 수 없다 — 코드와 별개로
직접 옮긴다.

```powershell
scp -i $key -r "$ai\models\BIKE\<태그>_<타임스탬프>" ${server}:~/Soomgil-INFRA-ai-data-monitoring/AI/models/BIKE/
```

새 아티팩트로 교체할 때는 `app/core/config.py`의 `bike_eta_model_dir`(또는 해당 도메인의
모델 경로 설정)을 새 폴더명으로 바꾸고, 그 `config.py`도 같이 올린 뒤 서비스를 재시작한다(3절).

## 3. `ai-api` systemd 서비스

`app.main:app`을 `uvicorn`으로 상시 구동한다. 유닛 템플릿은 `AI/scripts/ai-api.service`
(`bike-realtime-poller.service`와 같은 `<REPO_ROOT>`/`<VENV_PATH>` 플레이스홀더 방식).

### 최초 설치 (이미 완료돼 있음 — 재설치할 때만)

```bash
sed \
  -e "s|<REPO_ROOT>|/home/ubuntu/Soomgil-INFRA-ai-data-monitoring|g" \
  -e "s|<VENV_PATH>|/home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI/.venv|g" \
  ~/Soomgil-INFRA-ai-data-monitoring/AI/scripts/ai-api.service | sudo tee /etc/systemd/system/ai-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now ai-api
```

### 평소 운영 명령

```bash
sudo systemctl status ai-api --no-pager    # 상태 확인
sudo systemctl restart ai-api              # 코드 배포 후 재시작 — 이거 하나면 된다
tail -f ~/Soomgil-INFRA-ai-data-monitoring/AI/logs/ai-api.log   # 로그
```

`Restart=always`라 프로세스가 죽거나 서버가 재부팅돼도 자동으로 다시 뜬다. 코드를 scp로
올린 뒤에는 **`restart`만 하면 되고, venv 활성화나 `nohup`을 수동으로 할 필요 없다** —
`ExecStart`가 venv의 절대경로 `uvicorn`을 직접 부른다.

**Tailscale IP(`100.64.193.109`)로 바인딩돼 있다** — 퍼블릭 IP·VPC 대역으로는 안 열리고,
같은 Tailscale 네트워크(tailnet)에 있는 노드만 접근 가능하다. BE 서버(EC2 기본,
`j15a104.p.ssafy.io` = Tailscale `100.103.156.53`)에서 실제로 호출해 교차 검증했다
(2026-09-17, `ubuntu@ip-172-26-14-16`에서 curl → 정상 응답).

**BE가 호출할 주소**
```
http://100.64.193.109:8000
예: GET http://100.64.193.109:8000/bike/stations/{rental_id}/eta-stock?eta_minutes={0~30}
```

k3s 파드 안에서 도는 BE 앱이 호스트의 Tailscale IP로 나갈 수 있는지는 호스트 레벨
curl로만 확인했다 — 파드 네트워크 정책에 따라 다를 수 있어, 연동 중 문제가 있으면
BE 팀원이 `kubectl exec`로 파드 안에서 같은 curl을 한 번 더 확인해보는 게 좋다.

### 동작 확인

```bash
curl -s "http://100.64.193.109:8000/bike/stations/ST-10/eta-stock?eta_minutes=15" | python3 -m json.tool
```

`"source": "lightgbm"`이 나오면 배치표가 아니라 실시간 모델 추론이 정상 동작 중인 것.
(`ST-10`은 `data/BIKE/raw/realtime/latest_stock.parquet`에 있는 실제 역 ID 예시 — 다른
역으로 테스트하려면 그 parquet에서 `rental_id`를 하나 골라 쓴다.)

## 4. 이 서버에서 같이 도는 다른 서비스

| 서비스 | 역할 | 소유 |
| --- | --- | --- |
| `ai-api.service` | FastAPI 게이트웨이(`CROWD`+`BIKE` 전체), 방금 추가 | 이 문서 |
| `bike-realtime-poller.service` | 카프카에서 실시간 재고 받아 `latest_stock.parquet` 갱신 | 별도 브랜치 |
| `weather-nowcast-poller.service` | 실시간 날씨 스냅샷 갱신 | 별도 브랜치 |
| `bike-avg-batch.timer`/`.service` | `bike_stock_pred` 배치표(폴백용) 주기 갱신 | S15P21A104-225 |
| `subway-ridership-daily.timer`/`.service` | D-1 승하차 일 2회 수집 | 별도 브랜치 |

`ai-api`는 `bike-realtime-poller`가 쓰는 `latest_stock.parquet`을 읽기만 하고, `bike-avg-batch`가
만드는 배치표는 **읽지 않는다**(`/bike/stations/{id}/eta-stock`은 실시간 모델 직접 호출 — 배치표는
BE가 자기 DB로 가져가 쓰는 폴백 전용, `router.py` 모듈 docstring 참고). 그래서 이 서비스들끼리는
서로 재시작 순서를 맞출 필요가 없다.

## 5. 트러블슈팅

| 증상 | 원인·해결 |
| --- | --- |
| `scp`: `UNPROTECTED PRIVATE KEY FILE` / `bad permissions` | Windows에서 `.pem`에 현재 계정 외 권한(정체불명 SID 포함)이 남아있을 때. `icacls <pem> /reset` → `icacls <pem> /inheritance:r` → `icacls <pem> /grant:r "$($env:USERNAME):R"` 순서로 정리 |
| `nohup: failed to run command 'uvicorn'` | venv 비활성 상태. `source .venv/bin/activate` 먼저(단, `ai-api` 서비스로 돌린다면 애초에 필요 없음 — 3절) |
| `ModuleNotFoundError`/`ImportError` (import 체인 중간) | 그 모듈 파일이 서버에 구버전이거나 없음. 1절의 diff 확인 절차로 최신 버전 scp |
| `find: 'app/BIKE': No such file or directory` | `cd ~/Soomgil-INFRA-ai-data-monitoring/AI`가 실제로 안 먹은 상태에서 상대경로로 찾은 것. 절대경로로 다시 시도하거나 `pwd`로 위치 먼저 확인 |
| `rmdir: Directory not empty` | scp가 파일 대신 디렉터리를 만든 사고(1절 참고) — 내용물 확인 후 `rm -rf`로 통째로 지우고 다시 scp |

## 문의

배포 대상 코드·모델 배경은 `app/BIKE/router.py` 모듈 docstring, 피처·검증 근거는
`validation/BYC/anchor-horizon-feature-check/RESULTS.md`.
