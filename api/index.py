import os
import sqlite3
import warnings

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai

# ============================================================
# CONFIGURATION
# ============================================================

warnings.filterwarnings("ignore")

# Load environment variables
load_dotenv()

# Get Gemini API key from environment
API_KEY = os.getenv("GEMINI_API_KEY")

# ============================================================
# PATHS
# ============================================================

# Project root directory
# api/index.py
#     ↑
# parent = api
# parent of api = project root
BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

# ICD-11 database
DB_FILE = os.path.join(
    BASE_DIR,
    "icd11_complete.db"
)

# Frontend
FRONTEND_FILE = os.path.join(
    BASE_DIR,
    "index.html"
)

# ============================================================
# GEMINI CLIENT
# ============================================================

client = None

if API_KEY:
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception as e:
        print("Gemini client initialization error:", e)
        client = None


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="Medical AI Assistant API",
    description="AI Medical Assistant using ICD-11 database and Gemini",
    version="1.0.0"
)


# ============================================================
# REQUEST MODEL
# ============================================================

class ChatRequest(BaseModel):
    symptoms: str


# ============================================================
# FRONTEND ROUTE
# ============================================================

@app.get("/")
def frontend():
    """
    Serve the frontend index.html
    """

    if not os.path.exists(FRONTEND_FILE):
        return {
            "error": "index.html not found",
            "path": FRONTEND_FILE
        }

    return FileResponse(
        FRONTEND_FILE,
        media_type="text/html"
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api")
def health_check():
    """
    Check whether the Medical AI Assistant API is running.
    """

    return {
        "message": "Medical AI Assistant API is running",
        "status": "healthy"
    }


@app.get("/api/health")
def health():
    """
    Detailed health check.
    """

    return {
        "status": "healthy",
        "database_exists": os.path.exists(DB_FILE),
        "gemini_configured": bool(API_KEY)
    }


# ============================================================
# ICD-11 DATABASE SEARCH
# ============================================================

def search_diseases(symptoms_text, top_k=5):
    """
    Search the local ICD-11 SQLite database using FTS.
    """

    if not symptoms_text:
        return []

    if not os.path.exists(DB_FILE):
        print("Database not found:", DB_FILE)
        return []

    conn = None

    try:

        conn = sqlite3.connect(DB_FILE)

        cursor = conn.cursor()

        # Convert input into searchable words
        words = [
            word.strip()
            for word in symptoms_text
            .replace(",", " ")
            .split()
            if len(word.strip()) > 2
        ]

        if not words:
            return []

        # SQLite FTS query
        fts_query = " OR ".join(words)

        query = """
        SELECT
            disease_name,
            icd_code,
            definition
        FROM diseases_fts
        WHERE diseases_fts MATCH ?
        ORDER BY bm25(diseases_fts) ASC
        LIMIT ?
        """

        cursor.execute(
            query,
            (fts_query, top_k)
        )

        results = cursor.fetchall()

        return results

    except Exception as e:

        print("Database search error:", e)

        return []

    finally:

        if conn:
            conn.close()


# ============================================================
# CREATE MEDICAL CONTEXT
# ============================================================

def create_medical_context(matches):
    """
    Convert ICD-11 search results into context for Gemini.
    """

    if not matches:

        return (
            "No specific medical conditions matching the user's "
            "input were found in the ICD-11 database."
        )

    context = (
        "The following conditions were retrieved from the "
        "local WHO ICD-11 database. They are possible matches "
        "and NOT confirmed diagnoses:\n\n"
    )

    for name, icd, definition in matches:

        if definition:

            snippet = definition[:500]

            if len(definition) > 500:
                snippet += "..."

        else:

            snippet = "No definition available."

        context += (
            f"Condition: {name}\n"
            f"ICD-11 Code: {icd}\n"
            f"Details: {snippet}\n\n"
        )

    return context


# ============================================================
# GEMINI MEDICAL RESPONSE
# ============================================================

def get_llm_recommendation(symptoms_text):
    """
    Search ICD-11 database and generate a response using Gemini.
    """

    # --------------------------------------------------------
    # Check API key
    # --------------------------------------------------------

    if not API_KEY:

        return (
            "Gemini API key is not configured on the server. "
            "Please configure GEMINI_API_KEY in Vercel Environment Variables.",
            []
        )

    # --------------------------------------------------------
    # Search ICD-11 database
    # --------------------------------------------------------

    matches = search_diseases(
        symptoms_text,
        top_k=3
    )

    # --------------------------------------------------------
    # Create context
    # --------------------------------------------------------

    context = create_medical_context(matches)

    # --------------------------------------------------------
    # Prompt
    # --------------------------------------------------------

    prompt = f"""
You are an empathetic and professional AI medical assistant.

A user has provided the following information:

"{symptoms_text}"

ICD-11 database context:

{context}

Your task is to provide helpful health information.

Follow these rules strictly:

1. Be empathetic and professional.

2. Do NOT provide a definitive medical diagnosis.

3. Explain that the conditions retrieved from the ICD-11
   database are possible matches, not confirmed diagnoses.

4. Explain relevant symptoms or conditions in simple language.

5. Recommend appropriate professional medical evaluation
   when necessary.

6. If symptoms appear potentially urgent or severe, advise
   the user to seek immediate medical attention.

7. Do not prescribe medication or provide dangerous treatment
   instructions.

8. Do not claim certainty.

9. Keep the response understandable for a general user.

10. End with this disclaimer:

"Medical Disclaimer: This AI assistant provides general
health information and is not a substitute for diagnosis,
treatment, or advice from a qualified healthcare professional."
"""

    # --------------------------------------------------------
    # Generate Gemini response
    # --------------------------------------------------------

    try:

        if not client:

            return (
                "Gemini client is not available. "
                "Please check GEMINI_API_KEY configuration.",
                matches
            )

        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt
        )

        if response and response.text:

            return response.text, matches

        return (
            "The AI service did not return a response.",
            matches
        )

    except Exception as e:

        print("Gemini error:", e)

        return (
            "Sorry, I was unable to connect to the AI service "
            "at the moment. Please try again later.",
            matches
        )


# ============================================================
# CHAT API
# ============================================================

@app.post("/api/chat")
def chat(request: ChatRequest):
    """
    Main medical assistant endpoint.
    """

    symptoms = request.symptoms.strip()

    # --------------------------------------------------------
    # Validate input
    # --------------------------------------------------------

    if not symptoms:

        return {
            "success": False,
            "response": "Please describe your symptoms.",
            "message": "Please describe your symptoms.",
            "matches": []
        }

    # --------------------------------------------------------
    # Generate response
    # --------------------------------------------------------

    response_text, matches = get_llm_recommendation(
        symptoms
    )

    # --------------------------------------------------------
    # Format database matches
    # --------------------------------------------------------

    formatted_matches = []

    for name, icd, definition in matches:

        formatted_matches.append(
            {
                "disease_name": name,
                "icd_code": icd,
                "definition": definition
            }
        )

    # --------------------------------------------------------
    # Return response
    # --------------------------------------------------------

    return {
        "success": True,
        "response": response_text,
        "message": response_text,
        "matches": formatted_matches
    }


# ============================================================
# DATABASE TEST ENDPOINT
# ============================================================

@app.get("/api/database")
def database_status():
    """
    Check whether the ICD-11 database exists.
    """

    if not os.path.exists(DB_FILE):

        return {
            "database": "not found",
            "path": DB_FILE
        }

    size = os.path.getsize(DB_FILE)

    return {
        "database": "available",
        "size_bytes": size,
        "size_mb": round(size / (1024 * 1024), 2)
    }