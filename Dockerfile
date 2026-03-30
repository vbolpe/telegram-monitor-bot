FROM python:3.12-slim

# Instalar iputils-ping para soporte de ping con privilegios de red
RUN apt-get update && apt-get install -y \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Directorio donde se montará el Excel
RUN mkdir -p /data

CMD ["python", "-u", "bot.py"]
