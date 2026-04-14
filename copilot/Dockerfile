FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt copilot/requirements-copilot.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-copilot.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "copilot.webhook:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
