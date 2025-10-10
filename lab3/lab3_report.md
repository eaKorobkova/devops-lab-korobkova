University: ITMO University
Faculty: FICT

Course: Cloud platforms as the basis of technology entrepreneurship ADD link

Year: 2025/2026

Group: U4225

Author: KOROBKOVA EKATERINA ANDREEVNA

Lab: Lab3

Date of create: 09.10.2025

Date of finished: 10.10.2025

Обычная лабораторная работа

**1. Создание конфигурации Prometheus**

Создала папку prometheus для конфигурации и файл prometheus/prometheus.yml со следующим содержимым

![alt text](screenshots/1.png)

**2. Запуск Node Exporter**

Запустила контейнер Node Exporter для сбора системных метрик

![alt text](screenshots/2.png)

Проверила работу http://localhost:9100/metrics

![alt text](screenshots/3.png)

**3. Запуск Prometheus**

Создала том для данных Prometheus и запустила контейнер Prometheus:

![alt text](screenshots/4.png)

Проверила работу http://localhost:9090

![alt text](screenshots/5.png)

**4. Запуск Grafana**

Создала том для данных Grafana и запустила контейнер Grafana

![alt text](screenshots/6.png)

Проверила работу http://localhost:3000

![alt text](screenshots/7.png)

**5. Настройка Grafana**

Вошла в Grafana (admin/admin)], добавила источник данных Prometheus, URL: http://prometheus:9090

![alt text](screenshots/8.png)

Создала дашборд: источник данных Prometheus, метрика: node_cpu_seconds_total

![alt text](screenshots/D.png)

**6. Тестирование системы**

Проверила все контейнеры: docker ps

![alt text](screenshots/9.png)

Открыла Prometheus и убедилась, что метрики собираются

![alt text](screenshots/10.png)

Создала график для CPU

![alt text](screenshots/13.png)

Создала график для памяти

![alt text](screenshots/11.png)

Создала график для диска

![alt text](screenshots/12.png)


