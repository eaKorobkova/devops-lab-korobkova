Обычная лабораторная работа

Изучение основ Docker:

Установка Docker:
Установить Docker Desktop (для Windows/Mac) или Docker Engine (для Linux)
Проверить установку командой docker --version
Запустить тестовый контейнер: docker run hello-world
Изучить базовые команды: docker images, docker ps, docker ps -a

Работа с готовыми образами:

Скачать образ Ubuntu: docker pull ubuntu:latest
Запустить интерактивный контейнер: docker run -it ubuntu bash
Внутри контейнера установить пакет (например, curl): apt update && apt install -y curl
Проверить установку: curl --version
Выйти из контейнера: exit

Запуск веб-сервера:

Запустить контейнер с nginx: docker run -d -p 8080:80 --name web-server nginx:alpine
Проверить работу в браузере: http://localhost:8080
Посмотреть логи контейнера: docker logs web-server
Подключиться к контейнеру: docker exec -it web-server sh

Управление контейнерами:

Посмотреть запущенные контейнеры: docker ps
Посмотреть все контейнеры: docker ps -a
Остановить контейнер: docker stop web-server
Запустить остановленный контейнер: docker start web-server
Удалить контейнер: docker rm web-server
Удалить образ: docker rmi nginx:alpine

Работа с томами (volumes):

Создать том: docker volume create my-volume
Запустить контейнер с томом: docker run -d -v my-volume:/data --name volume-test ubuntu
Подключиться к контейнеру: docker exec -it volume-test bash
Создать файл в томе: echo "Hello from volume" > /data/test.txt
Удалить контейнер и создать новый с тем же томом
Проверить, что файл сохранился
