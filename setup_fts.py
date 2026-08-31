import sqlite3

DB_FILE = "icd11_complete.db"

def setup_fts():
    print("Connecting to database...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print("Creating FTS5 virtual table for diseases...")
    # Drop if exists
    cursor.execute("DROP TABLE IF EXISTS diseases_fts;")
    
    # Create FTS5 table
    cursor.execute("""
        CREATE VIRTUAL TABLE diseases_fts USING fts5(
            disease_name,
            icd_code,
            definition,
            synonyms
        );
    """)
    
    print("Populating FTS5 table with data from diseases table...")
    # Insert data
    cursor.execute("""
        INSERT INTO diseases_fts (disease_name, icd_code, definition, synonyms)
        SELECT disease_name, icd_code, definition, synonyms
        FROM diseases
        WHERE disease_name IS NOT NULL AND disease_name != '';
    """)
    
    conn.commit()
    
    # Check count
    cursor.execute("SELECT COUNT(*) FROM diseases_fts")
    count = cursor.fetchone()[0]
    
    print(f"Successfully indexed {count} diseases for full-text search!")
    conn.close()

if __name__ == "__main__":
    setup_fts()
