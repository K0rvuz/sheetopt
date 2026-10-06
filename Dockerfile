FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["uvicorn", "sheetopt.api:app", "--host", "0.0.0.0", "--port", "8080"]
