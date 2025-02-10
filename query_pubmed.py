from fastapi import APIRouter
import requests
from pydantic import BaseModel

router = APIRouter(prefix="/api/query_pubmed", tags=["PubMed Query"])

PUBMED_API_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
PUBMED_MAX_RESULTS = 3

class PubMedRequest(BaseModel):
    query: str

def fetch_pubmed_details(pubmed_ids):
    params = {
        "db": "pubmed",
        "id": ",".join(pubmed_ids),
        "retmode": "xml"
    }
    
    response = requests.get(f"{PUBMED_API_BASE_URL}efetch.fcgi", params=params)
    if response.status_code == 200:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(response.text)
        articles = []
        for article in root.findall(".//PubmedArticle"):
            title = article.find(".//ArticleTitle").text or "No title"
            abstract_elem = article.find(".//AbstractText")
            abstract = abstract_elem.text if abstract_elem is not None else "No abstract available"
            articles.append(f"- **{title}**\nAbstract: {abstract}")
        return {"results": articles}
    else:
        return {"error": f"Error fetching abstracts: {response.status_code}"}

@router.post("/")
def query_pubmed(request: PubMedRequest):
    params = {
        "db": "pubmed",
        "term": request.query,
        "retmode": "json",
        "retmax": PUBMED_MAX_RESULTS
    }
    
    response = requests.get(f"{PUBMED_API_BASE_URL}esearch.fcgi", params=params)
    
    if response.status_code == 200:
        result = response.json()
        pubmed_ids = result.get("esearchresult", {}).get("idlist", [])
        if pubmed_ids:
            return fetch_pubmed_details(pubmed_ids)
        else:
            return {"results": ["No relevant PubMed articles found."]}
    else:
        return {"results": [f"Error querying PubMed: {response.status_code}"]}