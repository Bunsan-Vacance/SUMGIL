# TLS 절차 (S15P21A104-210 ④). node1에서 실행. 멱등.

# 0. 전제: 80/443 inbound 개방(ufw 고정) + 노드 outbound(HTTPS) + 도메인이 노드로 붙음.
#    ACME_EMAIL을 실제 주소로 교체한다 (cluster-issuer.yaml 2곳, ⬜).
#    cert-manager 버전은 적용 시점에 최신 안정인지 확인한다 (kustomization.yaml 핀).
#
# 1. staging으로 먼저 발급 확인 (rate limit 회피):
#    kubectl apply -k Infra/k8s/cert-manager --server-side   # 이름 그대로 두 번 적용해도 됨
#    # certificate.yaml의 issuerRef를 letsencrypt-staging으로 바꿔 1회 적용·확인 후 prod로 복귀.
#    # (기본값은 prod. staging 확인은 최초 1회만.)
#
# 2. prod 적용 (apply.sh가 순서대로 한다: namespaces → ingress-nginx → cert-manager → prod → BE/FE):
#    bash Infra/k8s/scripts/apply.sh
#
# 3. 확인:
#    kubectl get certificate -n prod            # Ready True
#    kubectl get secret sumgil-tls -n prod      # tls.crt·tls.key 존재
#    echo | openssl s_client -connect j15a104.p.ssafy.io:443 -servername j15a104.p.ssafy.io 2>/dev/null \
#      | openssl x509 -noout -issuer -dates     # issuer: Let's Encrypt
#
# 4. 갱신: cert-manager가 만료 30일 전 자동 갱신. 별도 크론 불필요.
#    갱신 실패 시 ClusterIssuer/Challenge 이벤트 확인:
#    kubectl describe challenge -n prod
#
# 주의: HTTP 리다이렉트 강제(ssl-redirect)는 켜지 않는다.
# 클러스터 내부·헬스체크가 HTTP를 쓰므로, 443 개통 확인 후에 별도 티켓으로 검토한다.
