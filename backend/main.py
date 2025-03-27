import os
import time
import logging
from fastapi import FastAPI, HTTPException, Request
from elasticsearch import Elasticsearch, exceptions as es_exceptions
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

ELASTICSEARCH_HOST = os.getenv("ELASTICSEARCH_HOST", "elasticsearch")
ELASTICSEARCH_PORT = int(os.getenv("ELASTICSEARCH_PORT", "9200"))
INDEX_NAME = "my_index"
WIKI_URL = "https://en.wikipedia.org/wiki/India"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic Model(defining the schema) for Insert
class InsertItem(BaseModel):
    text: str

es = None

app = FastAPI()

def wait_for_elasticsearch():
    global es
    logger.info(f"Attempting to connect to Elasticsearch at {ELASTICSEARCH_HOST}:{ELASTICSEARCH_PORT}...")
    retries = 30
    while retries > 0:
        try:
            temp_es = Elasticsearch(
                [f"http://{ELASTICSEARCH_HOST}:{ELASTICSEARCH_PORT}"],
                request_timeout=10
            )
            if temp_es.ping():
                es = temp_es
                logger.info("Successfully connected to Elasticsearch.")
                return True
            else:
                logger.warning("Elasticsearch ping failed.")
        except es_exceptions.ConnectionError as e:
            logger.warning(f"Elasticsearch connection failed: {e}. Retrying...")
        except Exception as e:
            logger.error(f"An unexpected error occurred during ES connection: {e}. Retrying...")

        retries -= 1
        time.sleep(5)

    logger.error("Could not connect to Elasticsearch after multiple retries.")
    return False

def create_index_if_not_exists():
    if not es:
        logger.error("Elasticsearch client not initialized.")
        return
    try:
        if not es.indices.exists(index=INDEX_NAME):
            logger.info(f"Index '{INDEX_NAME}' not found. Creating...")
            mapping = {
                "properties": {
                    "id": {"type": "keyword"},
                    "text": {"type": "text"} 
                }
            }
            es.indices.create(index=INDEX_NAME, mappings=mapping)
            logger.info(f"Index '{INDEX_NAME}' created successfully.")
        else:
            logger.info(f"Index '{INDEX_NAME}' already exists.")
    except es_exceptions.ElasticsearchException as e:
        logger.error(f"Failed to check or create index '{INDEX_NAME}': {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during index creation: {e}")


def insert_initial_data():
    if not es:
        logger.error("Elasticsearch client not initialized.")
        return
    

    try:
        count_response = es.count(index=INDEX_NAME)
        if count_response['count'] > 0:
            logger.info("Initial data already seems to be present. Skipping insertion.")
            return

        logger.info(f"Fetching content from {WIKI_URL} for initial data...")
        response = requests.get(WIKI_URL)
        response.raise_for_status() 

        soup = BeautifulSoup(response.content, 'html.parser')

        content_div = soup.find(id='mw-content-text')
        if not content_div:
            logger.error("Could not find main content div ('mw-content-text') on Wikipedia page.")
            return

        paragraphs = content_div.find_all('p', recursive=True, limit=6) 

        docs_to_insert = []
        doc_id_counter = 1
        for p in paragraphs:
            text = p.get_text().strip()
            if text and len(text) > 50:
                 docs_to_insert.append({
                     "id": f"wiki_{doc_id_counter}",
                     "text": text


                 })
                 doc_id_counter += 1
                 if doc_id_counter > 4: 
                     break

        if not docs_to_insert:
            logger.warning("No suitable paragraphs found for initial insertion.")
            return

        logger.info(f"Inserting {len(docs_to_insert)} initial documents...")
        for doc in docs_to_insert:
            try:
                es.index(index=INDEX_NAME, id=doc["id"], document={"text": doc["text"]})
            except es_exceptions.ElasticsearchException as e:
                 logger.error(f"Error indexing document id {doc['id']}: {e}")

        es.indices.refresh(index=INDEX_NAME)
        logger.info("Initial data insertion complete.")

    except requests.exceptions.RequestException as e:

        logger.error(f"Error fetching Wikipedia page: {e}")
    except es_exceptions.ElasticsearchException as e:
        logger.error(f"Elasticsearch error during initial data insertion: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during initial data insertion: {e}")


@app.on_event("startup")
async def startup_event():
    logger.info("Backend service starting up...")
    if wait_for_elasticsearch():
        create_index_if_not_exists()
        insert_initial_data()
    else:
        logger.critical("Failed to connect to Elasticsearch. Backend might not function correctly.")

@app.get("/search/{query}")
async def search_documents(query: str):
    """
    Performs a match search on the 'text' field and returns the best scoring hit.
    """
    if not es:
        raise HTTPException(status_code=503, detail="Elasticsearch not available")
    try:
        search_body = {
            "query": {
                "match": {
                    "text": {
                        "query": query
                    }
                }
            },
            "size": 1 # Get only the topmost result
        }
        response = es.search(index=INDEX_NAME, body=search_body)

        hits = response['hits']['hits']
        if not hits:
            return {"message": "No matching documents found.", "document": None}

        best_hit = hits[0]
        return {
            "message": f"Found document with score {best_hit['_score']}",
            "document": best_hit['_source'],
            "id": best_hit['_id']
        }

    except es_exceptions.ElasticsearchException as e:
        logger.error(f"Elasticsearch search error: {e}")
        raise HTTPException(status_code=500, detail=f"Elasticsearch error: {e.info}")
    except Exception as e:
        logger.error(f"Unexpected error during search: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during search")
@app.post("/insert")
async def insert_document(item: InsertItem):
    """
    Inserts a new document with the provided text  from the textbox.
    Lets Elastic search generate the document ID automatically.
    """
    if not es:
        raise HTTPException(status_code=503, detail="Elasticsearch not available")
    if not item.text or not item.text.strip():
         raise HTTPException(status_code=400, detail="Input text cannot be empty.")

    try:
        doc_body = {"text": item.text}
        response = es.index(index=INDEX_NAME, document=doc_body)
        es.indices.refresh(index=INDEX_NAME)

        return {
            "message": "Document inserted successfully!",
            "inserted_id": response['_id'],
            "result": response['result']
        }
    except es_exceptions.ElasticsearchException as e:
        logger.error(f"Elasticsearch insert error: {e}")
        raise HTTPException(status_code=500, detail=f"Elasticsearch error: {e.info}")
    except Exception as e:
        logger.error(f"Unexpected error during insert: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during insert")

@app.get("/")
async def read_root():
    
    return {"message": "Backend is running"}