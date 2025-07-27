FROM --platform=linux/amd64 python:3.9-slim

WORKDIR /app

RUN pip install --no-cache-dir pymupdf

COPY main.py .

CMD ["python", "main.py"]
