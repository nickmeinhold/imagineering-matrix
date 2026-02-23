FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY appservice/ appservice/

VOLUME /data

CMD ["python", "-u", "-m", "appservice"]
