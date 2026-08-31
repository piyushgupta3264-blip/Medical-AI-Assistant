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

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")


# ============================================================
# PROJECT PATHS
# ============================================================

# Current file:
# data set/api/index.py
#
# BASE_DIR:
# data set/

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DB_FILE = os.path.join(
    BASE_DIR,
    "icd11_complete.db"
)

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
        client = genai.Client(
            api_key=API_KEY
        )
    except Exception as e:
        print("Gemini initialization error:", e)
        client = None


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Medical AI Assistant API",
    description="AI Medical Assistant using ICD-11 and Gemini",
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
    Serve index.html from the project root.
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
# API HEALTH CHECK
# ============================================================

@app.get("/api")
def api_health():
    """
    Basic API health check.
    """

    return {
        "message": "Medical AI Assistant API is running",
        "status": "healthy"
    }


# ============================================================
# DETAILED HEALTH CHECK
# ============================================================

@app.get("/api/health")
def detailed_health():
    """
    Check API, database and Gemini configuration.
    """

    return {
        "status": "healthy",
        "database_exists": os.path.exists(DB_FILE),
        "gemini_configured": bool(API_KEY)
    }


# ============================================================
# SEARCH ICD-11 DATABASE
# ============================================================

def search_diseases(symptoms_text, top_k=5):
    """
    Search the local ICD-11 SQLite database.

    Uses the diseases_fts Full Text Search table.
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

        # Convert symptoms into individual words
        words = [
            word.strip()
            for word in symptoms_text
            .replace(",", " ")
            .split()
            if len(word.strip()) > 2
        ]

        if not words:
            return []

        # Example:
        # fever cough headache
        #
        # becomes:
        # fever OR cough OR headache

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

        print(
            "Database search error:",
            str(e)
        )

        return []

    finally:

        if conn:
            conn.close()


# ============================================================
# CREATE MEDICAL CONTEXT
# ============================================================

def create_medical_context(matches):
    """
    Convert ICD-11 database results into
    context for the LLM.
    """

    if not matches:

        return (
            "No specific medical conditions matching "
            "the user's input were found in the "
            "ICD-11 database."
        )

    context = (
        "The following possible conditions were retrieved "
        "from the local WHO ICD-11 database.\n"
        "These are NOT confirmed diagnoses.\n\n"
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
# GEMINI RESPONSE
# ============================================================

def get_llm_recommendation(symptoms_text):
    """
    Search ICD-11 and generate an AI response.
    """

    # --------------------------------------------------------
    # Check API key
    # --------------------------------------------------------

    if not API_KEY:

        return (
            "Gemini API key is not configured. "
            "Please configure GEMINI_API_KEY "
            "in Vercel Environment Variables.",
            []
        )

    # --------------------------------------------------------
    # Search ICD-11
    # --------------------------------------------------------

    matches = search_diseases(
        symptoms_text,
        top_k=3
    )

    # --------------------------------------------------------
    # Create context
    # --------------------------------------------------------

    context = create_medical_context(
        matches
    )

    # --------------------------------------------------------
    # LLM Prompt
    # --------------------------------------------------------

    prompt = f"""
You are an empathetic, professional AI medical assistant.

The user has provided the following symptoms or message:

"{symptoms_text}"

Here is information retrieved from the local
WHO ICD-11 database:

{context}

Provide a helpful conversational response.

IMPORTANT RULES:

1. Be empathetic and professional.

2. Do NOT provide a definitive medical diagnosis.

3. The ICD-11 conditions are possible matches only,
   not confirmed diagnoses.

4. Explain relevant conditions in simple language.

5. Recommend seeing a qualified healthcare professional
   when appropriate.

6. If symptoms could indicate an emergency, recommend
   seeking immediate medical attention.

7. Do not prescribe medication.

8. Do not provide dangerous treatment instructions.

9. Do not claim certainty.

10. Keep the response understandable to a general user.

11. End with this disclaimer:

Medical Disclaimer: This AI assistant provides general
health information and is not a substitute for diagnosis,
treatment, or advice from a qualified healthcare professional.
"""

    # --------------------------------------------------------
    # Call Gemini
    # --------------------------------------------------------

    try:

        if not client:

            return (
                "Gemini client is not available. "
                "Please check your GEMINI_API_KEY.",
                matches
            )

        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt
        )

        if response and response.text:

            return (
                response.text,
                matches
            )

        return (
            "The AI service did not return a response.",
            matches
        )

    except Exception as e:

        print(
            "Gemini API error:",
            str(e)
        )

        return (
            "Sorry, I was unable to connect to "
            "the AI service. Please try again later.",
            matches
        )


# ============================================================
# CHAT API
# ============================================================

@app.post("/api/chat")
def chat(request: ChatRequest):
    """
    Main Medical AI Assistant endpoint.
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
    # Get AI response
    # --------------------------------------------------------

    response_text, matches = get_llm_recommendation(
        symptoms
    )

    # --------------------------------------------------------
    # Format ICD-11 matches
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
    # Return JSON
    # --------------------------------------------------------

    return {
        "success": True,
        "response": response_text,
        "message": response_text,
        "matches": formatted_matches
    }


# ============================================================
# DATABASE STATUS
# ============================================================

@app.get("/api/database")
def database_status():
    """
    Check whether the ICD-11 database is available.
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
        "size_mb": round(
            size / (1024 * 1024),
            2
        )
    }


# ============================================================
# ROOT INFORMATION
# ============================================================

@app.get("/api/info")
def api_info():

    return {
        "project": "Medical AI Assistant",
        "version": "1.0.0",
        "frontend": "/",
        "chat_endpoint": "/api/chat",
        "health_endpoint": "/api/health",
        "database_endpoint": "/api/database"
    }