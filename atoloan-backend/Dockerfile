FROM python:3.12.16-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Unprivileged runtime user (UID matches runAsUser in the k8s manifests).
# Legacy upload dirs stay writable for the compose volumes that mount them.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p user_uploaded_documents upload_pdf \
    && chown app:app user_uploaded_documents upload_pdf
USER 10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
