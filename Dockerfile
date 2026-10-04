# Snapshot API server + reference viewer. Serves public/snapshots/ (committed or volume-mounted).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY internet_snapshot internet_snapshot
COPY seed seed
COPY viewer viewer
COPY public public
# Download the PDDL/CC0/CC BY lookup tables at startup so /v1/whereami can map caller IPs to ASNs.
ENV SNAPSHOT_FETCH_LOOKUPS=1
EXPOSE 8000
CMD ["python", "-m", "internet_snapshot", "serve", "--host", "0.0.0.0", "--port", "8000"]
