FROM python:3.12-slim

WORKDIR /app

# Dependencias primero, para aprovechar la caché de capas de Docker.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El resto del proyecto (core, pipeline, api, static, data, tests).
COPY . .

# El reloj del contenedor. Sin esto va en UTC, y a las 00:30 en España en UTC
# todavia es ayer: un pedido de "hoy" seria futuro y se descartaria durante dos
# horas cada noche. La fecha de corte tiene que ser la del calendario de quien
# escribe los pedidos, no la de Greenwich.
ENV TZ=Europe/Madrid
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VENTAS_DATA_DIR=/app/data

EXPOSE 8000

# La orden real (ingesta → pytest → API) la da docker-compose, para que el
# fallo de un test impida arrancar la API. Este CMD es solo el arranque directo.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
