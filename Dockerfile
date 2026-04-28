FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir \
    "fastapi" \
    "uvicorn[standard]" \
    "pymupdf>=1.24.0,<1.26" \
    "python-multipart" \
    "qdrant-client>=1.9" \
    "python-dotenv>=1.0" \
    "minio>=7.0" \
    "streamlit>=1.35"

COPY . .

EXPOSE 8585

CMD ["streamlit", "run", "app.py", \
     "--server.port=8585", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
