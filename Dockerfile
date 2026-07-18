# Container for the Data Analyst Agent (Azure Container Apps / any host).
#
# Notable choices:
# - The Olist dataset is DOWNLOADED AT BUILD TIME from Kaggle's public
#   URL and compiled into data/olist.db by our own build_db.py; the raw
#   CSVs are then deleted. The repo ships no data, and the image ships
#   only the 149MB database it actually serves.
# - No ML runtime needed at all (unlike the RAG project): the agent's
#   intelligence is remote (OpenRouter) and its computation is SQLite.
#   The image stays small and starts in about a second.
# - OPENROUTER_API_KEY is injected as an environment variable by the
#   host — never baked into the image.

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pandas requests python-dotenv flask gunicorn

COPY src/ src/
COPY data/eval/ data/eval/

# Download public dataset -> build SQLite db -> discard the CSVs
RUN mkdir -p data/raw \
    && curl -L -o /tmp/olist.zip \
       "https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce" \
    && unzip -q /tmp/olist.zip -d data/raw \
    && rm /tmp/olist.zip \
    && python src/build_db.py \
    && rm -rf data/raw

EXPOSE 7860
CMD ["gunicorn", "--chdir", "src", "-w", "1", "-b", "0.0.0.0:7860", \
     "--timeout", "300", "app:app"]
