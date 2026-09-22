# BE 이미지 (S15P21A104-125). 컨텍스트: BE/ (docker build -f Dockerfile .).
# single jar 전제 (bootJar 산출물 1개). jar가 2개 이상이면 COPY가 실패한다.
FROM eclipse-temurin:21-jdk-jammy AS build
WORKDIR /src
COPY gradle gradle
COPY gradlew settings.gradle build.gradle ./
COPY src src
RUN chmod +x gradlew && ./gradlew bootJar --no-daemon -x test

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /src/build/libs/*.jar app.jar
EXPOSE 8080
# 시간대를 서울로 고정한다 (S15P21A104-306). 베이스 이미지가 Etc/UTC 라, 시간대 없는
# LocalDateTime.now() 가 9시간 이른 값을 준다 — 버스 실시간 혼잡도의 "지금 출발" 판정이
# 통째로 미래 검색으로 걸렸고(297), edge_time·혼잡도 조회 슬롯도 어긋난다.
# be·be-consumer·be-collector·be-collector-evening 이 같은 이미지라 이 한 줄이 넷에 다 걸린다.
# 수집기·컨슈머는 자체 Clock.systemUTC() + CollectEvent.KST 를 써서 영향이 없다.
# 주의: prod 로그(CONSOLE_JSON)의 @timestamp 가 Z → +09:00 으로 바뀐다.
ENTRYPOINT ["java", "-Duser.timezone=Asia/Seoul", "-jar", "app.jar"]
