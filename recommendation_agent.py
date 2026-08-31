import sqlite3

DB_FILE = "icd11_complete.db"

def get_recommendations(symptoms_text, top_k=5):
    print(f"\nAnalyzing symptoms: '{symptoms_text}'...\n")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Process symptoms_text into an FTS query.
    # We will treat each word as a required token for a simpler strict search,
    # or use OR to find any matching symptoms.
    # Let's replace commas and spaces with OR so it matches documents containing ANY of the symptoms,
    # ranked by relevance (bm25).
    words = [w.strip() for w in symptoms_text.replace(',', ' ').split() if len(w.strip()) > 2]
    if not words:
        print("No valid symptoms provided.")
        return []
        
    fts_query = " OR ".join(words)
    
    query = """
    SELECT 
        disease_name, 
        icd_code, 
        definition,
        bm25(diseases_fts) as score
    FROM diseases_fts
    WHERE diseases_fts MATCH ?
    ORDER BY score ASC
    LIMIT ?
    """
    
    cursor.execute(query, (fts_query, top_k))
    results = cursor.fetchall()
    
    print(f"Top {top_k} Most Likely ICD-11 Matches (using BM25 search):\n")
    print("-" * 60)
    for i, row in enumerate(results, 1):
        disease_name, icd_code, definition, score = row
        print(f"{i}. {disease_name} (ICD: {icd_code})")
        # Note: SQLite BM25 score is negative (more negative = more relevant)
        print(f"   Relevance Score: {abs(score):.4f}")
        
        definition_snippet = (definition[:150] + "...") if definition else "No definition available."
        print(f"   Definition snippet: {definition_snippet}")
        print("-" * 60)
        
    conn.close()
    return results

if __name__ == "__main__":
    print("=" * 60)
    print("AI Symptom Analysis Agent (Phase 2 Demo - FTS5)")
    print("=" * 60)
    
    # Test cases
    test_symptoms = [
        "severe headache with nausea and light sensitivity",
        "chest pain shortness breath",
        "runny nose coughing sneezing"
    ]
    
    for symptom in test_symptoms:
        get_recommendations(symptom, top_k=3)
