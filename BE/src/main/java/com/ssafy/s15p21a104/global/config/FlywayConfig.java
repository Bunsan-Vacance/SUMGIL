package com.ssafy.s15p21a104.global.config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.beans.factory.config.BeanFactoryPostProcessor;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Boot 4에는 Flyway 자동 설정이 없으므로 수동 배선한다.
 * 마이그레이션을 JPA보다 먼저 실행하도록 의존성을 강제한다.
 */
@Configuration
public class FlywayConfig {

    @Bean(initMethod = "migrate")
    public Flyway flyway(DataSource dataSource) {
        return Flyway.configure()
                .dataSource(dataSource)
                .locations("classpath:db/migration")
                .load();
    }

    @Bean
    static BeanFactoryPostProcessor entityManagerFactoryDependsOnFlyway() {
        return beanFactory -> {
            if (!beanFactory.containsBeanDefinition("entityManagerFactory")) {
                return;
            }
            BeanDefinition bd = ((BeanDefinitionRegistry) beanFactory)
                    .getBeanDefinition("entityManagerFactory");
            List<String> dependsOn = new ArrayList<>(Arrays.asList(
                    bd.getDependsOn() == null ? new String[0] : bd.getDependsOn()));
            dependsOn.add("flyway");
            bd.setDependsOn(dependsOn.toArray(new String[0]));
        };
    }
}
