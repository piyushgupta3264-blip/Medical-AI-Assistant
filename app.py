import streamlit as st
import sqlite3
import os
from google import genai
from dotenv import load_dotenv
import warnings

# Suppress deprecation warnings
warnings.filterwarnings("ignore")

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

client = None
if API_KEY:
    client = genai.Client(api_key=API_KEY)

DB_FILE = "icd11_complete.db"

def search_diseases(symptoms_text, top_k=5):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    words = [w.strip() for w in symptoms_text.replace(',', ' ').split() if len(w.strip()) > 2]
    if not words:
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
    except Exception as e:
        results = []
    conn.close()
    return results

def get_llm_recommendation(symptoms_text):
    if not API_KEY:
        return "⚠️ Error: API Key not configured. Please add GEMINI_API_KEY to your .env file.", []
        
    matches = search_diseases(symptoms_text, top_k=3)
    
    if matches:
        context = "Based on a search of the WHO ICD-11 database, here are the most likely matching conditions:\n"
        for name, icd, definition in matches:
            snippet = (definition[:200] + "...") if definition else "No definition available."
            context += f"- Condition: {name} (ICD-11 Code: {icd})\n  Details: {snippet}\n\n"
    else:
        context = "No specific medical conditions matching the user's input were found in the ICD-11 database. If the user is just saying hello or making general conversation, respond politely and ask them how you can help with their symptoms. If they are describing medical symptoms, let them know you don't have specific information for that in your database, but recommend seeing a doctor."

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
    try:
        if not client:
            return "⚠️ Error: API Key not configured.", []
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt
        )
        return response.text, matches
    except Exception as e:
        return f"Error connecting to LLM: {str(e)}", []

# UI Setup
st.set_page_config(page_title="AI Medical Assistant", page_icon="🩺", layout="centered")

st.title("🩺 AI Medical Assistant")
st.write("Describe your symptoms below, and I will search the WHO ICD-11 database and provide recommendations.")

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "matches" in message:
            with st.expander("View Database Matches (ICD-11)"):
                for m in message["matches"]:
                    st.write(f"**{m[0]}** (ICD: {m[1]})")

# Input
if prompt := st.chat_input("E.g., I have a severe headache, nausea, and sensitivity to light."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing symptoms and consulting ICD-11 database..."):
            response_text, matches = get_llm_recommendation(prompt)
            st.markdown(response_text)
            if matches:
                with st.expander("View Database Matches (ICD-11)"):
                    for m in matches:
                        st.write(f"**{m[0]}** (ICD: {m[1]})")
                        
    st.session_state.messages.append({"role": "assistant", "content": response_text, "matches": matches})
