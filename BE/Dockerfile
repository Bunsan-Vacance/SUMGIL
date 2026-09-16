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
ENTRYPOINT ["java", "-jar", "app.jar"]
