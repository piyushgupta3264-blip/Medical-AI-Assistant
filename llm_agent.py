import sqlite3
import os
from google import genai
from dotenv import load_dotenv

# Load environment variables (API Key) from .env file
load_dotenv()

# Configure Gemini API
API_KEY = os.getenv("GEMINI_API_KEY")
client = None
if API_KEY:
    client = genai.Client(api_key=API_KEY)
else:
    print("WARNING: GEMINI_API_KEY not found in .env file. The LLM will not work.")

DB_FILE = "icd11_complete.db"

def search_diseases(symptoms_text, top_k=5):
    """Searches the SQLite database for diseases matching the symptoms."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    words = [w.strip() for w in symptoms_text.replace(',', ' ').split() if len(w.strip()) > 2]
    if not words:
        return []
        
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
    
    cursor.execute(query, (fts_query, top_k))
    results = cursor.fetchall()
    conn.close()
    return results

def get_llm_recommendation(symptoms_text):
    """Uses Gemini to generate a conversational response based on search results."""
    print(f"\n[1] Searching database for: '{symptoms_text}'...")
    
    # 1. Get matches from the database
    matches = search_diseases(symptoms_text, top_k=3)
    
    if matches:
        print(f"[2] Found {len(matches)} matching conditions in ICD-11. Generating AI response...")
        context = "Based on a search of the WHO ICD-11 database, here are the most likely matching conditions:\n"
        for name, icd, definition in matches:
            snippet = (definition[:200] + "...") if definition else "No definition available."
            context += f"- Condition: {name} (ICD-11 Code: {icd})\n  Details: {snippet}\n\n"
    else:
        print(f"[2] No matching conditions found in ICD-11. Generating conversational AI response...")
        context = "No specific medical conditions matching the user's input were found in the ICD-11 database. If the user is just saying hello or making general conversation, respond politely and ask them how you can help with their symptoms. If they are describing medical symptoms, let them know you don't have specific information for that in your database, but recommend seeing a doctor."

    # 3. Create the Prompt
    prompt = f"""
You are an empathetic, professional, and highly knowledgeable AI medical assistant. 
A user has sent the following message: "{symptoms_text}"

{context}

Please provide a conversational response to the user. Follow these rules strictly:
1. Be empathetic and professional.
2. If medical conditions are provided in the context, mention them simply and explain them.
3. DO NOT make a definitive medical diagnosis.
4. If they have medical concerns, strongly recommend that they seek professional medical advice or see a doctor.
5. Include a standard medical disclaimer at the end if discussing medical conditions.
"""

    # 4. Call the Gemini LLM
    try:
        if not client:
            return "Error: API Key not configured."
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Error connecting to LLM: {str(e)}"

if __name__ == "__main__":
    print("=" * 60)
    print("AI Medical Assistant (Phase 3 - LLM Integration)")
    print("=" * 60)
    
    if not API_KEY:
        print("Please add your GEMINI_API_KEY to the .env file to run this script.")
        exit(1)
        
    user_input = input("\nPlease describe your symptoms: ")
    
    response = get_llm_recommendation(user_input)
    
    print("\n" + "=" * 60)
    print("AI DOCTOR RESPONSE:")
    print("=" * 60)
    print(response)
    print("=" * 60)
