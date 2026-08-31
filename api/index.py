from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "icd11_complete.db")

app = FastAPI(
    title="Medical AI Assistant",
    description="AI-powered disease recognition and recommendation API",
    version="1.0.0"
)

# =========================
# Configuration
# =========================

API_KEY = os.getenv("GEMINI_API_KEY")
DB_FILE = "icd11_complete.db"

client = None

if API_KEY:
    client = genai.Client(api_key=API_KEY)


# =========================
# Request Model
# =========================

class SymptomRequest(BaseModel):
    symptoms: str


# =========================
# Disease Search
# =========================

def search_diseases(symptoms_text, top_k=5):

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    words = [
        w.strip()
        for w in symptoms_text.replace(",", " ").split()
        if len(w.strip()) > 2
    ]

    if not words:
        conn.close()
        return []

    fts_query = " OR ".join(words)

    query = """
    SELECT disease_name, icd_code, definition
    FROM diseases_fts
    WHERE diseases_fts MATCH ?
    ORDER BY bm25(diseases_fts) ASC
    LIMIT ?
    """

    try:
        cursor.execute(query, (fts_query, top_k))
        results = cursor.fetchall()
    except Exception:
        results = []

    conn.close()

    return results


# =========================
# Gemini Recommendation
# =========================

def get_llm_recommendation(symptoms_text):

    if not API_KEY:
        return "API key is not configured.", []

    matches = search_diseases(symptoms_text, top_k=3)

    if matches:

        context = (
            "Based on a search of the WHO ICD-11 database, "
            "here are potentially relevant matching conditions:\n"
        )

        for name, icd, definition in matches:

            snippet = (
                (definition[:200] + "...")
                if definition
                else "No definition available."
            )

            context += (
                f"- Condition: {name} "
                f"(ICD-11 Code: {icd})\n"
                f"  Details: {snippet}\n\n"
            )

    else:

        context = (
            "No specific medical conditions matching the user's "
            "input were found in the ICD-11 database."
        )

    prompt = f"""
You are an empathetic, professional AI medical assistant.

The user reported:

"{symptoms_text}"

{context}

Provide a helpful conversational response.

Rules:
1. Be empathetic and professional.
2. Explain potentially relevant conditions simply.
3. DO NOT provide a definitive medical diagnosis.
4. Recommend professional medical advice when appropriate.
5. Mention emergency care if symptoms appear potentially serious.
6. Include a medical disclaimer when discussing medical conditions.
"""

    try:

        if not client:
            return "API key is not configured.", []

        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt
        )

        return response.text, matches

    except Exception as e:

        return f"Error connecting to LLM: {str(e)}", []


# =========================
# Routes
# =========================

@app.get("/")
def root():

    return {
        "message": "Medical AI Assistant API is running",
        "status": "healthy"
    }


@app.get("/health")
def health():

    return {
        "status": "healthy"
    }


@app.post("/api/chat")
def chat(request: SymptomRequest):

    response, matches = get_llm_recommendation(
        request.symptoms
    )

    return {
        "symptoms": request.symptoms,
        "response": response,
        "matches": [
            {
                "disease": m[0],
                "icd_code": m[1],
                "definition": m[2]
            }
            for m in matches
        ]
    }