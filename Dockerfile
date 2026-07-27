FROM python:3.10

RUN mkdir /app

COPY requirements.txt /app/

RUN python -m pip install --upgrade pip

RUN python -m pip install -r /app/requirements.txt

# Устанавливаем часовой пояс (Москва)
RUN apt-get update && apt-get install -y tzdata && ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime && dpkg-reconfigure -f noninteractive tzdata && rm -rf /var/lib/apt/lists/*

COPY . /app/

WORKDIR /app

EXPOSE 8081

ENTRYPOINT ["python", "main.py"]
