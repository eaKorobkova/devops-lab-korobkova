Обычная лабораторная работа

**Установка Docker**

1.1. Установила Docker Desktop
   
1.2. Проверила установку командой docker --version

![alt text](version.png)

1.3. Запустила тестовый контейнер: docker run hello-world

![alt text](hello-world.png)

1.4. Изучила базовые команды: docker images, docker ps, docker ps -a

![alt text](команды.png)

**2. Работа с готовыми образами**

2.1. Скачала образ Ubuntu: docker pull ubuntu:latest

![alt text](docker_pull_ubuntu_latest.png)

2.2. Запустила интерактивный контейнер: docker run -it ubuntu bash и установила пакет curl: apt update && apt install -y curl

![alt text](1.png)

![alt text](2.png) 

2.3. Проверила установку: curl --version и вышла из контейнера: exit

![alt text](version_exit.png) 

**3. Запуск веб-сервера**

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
