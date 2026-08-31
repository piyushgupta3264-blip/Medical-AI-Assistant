import sqlite3
import os
from langchain_community.document_loaders import DataFrameLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
import pandas as pd
from tqdm import tqdm

DB_FILE = "icd11_complete.db"
CHROMA_DIR = "chroma_db"

def load_data():
    print("Loading data from SQLite...")
    conn = sqlite3.connect(DB_FILE)
    
    # We want to embed the diseases. The definition and synonyms contain the symptoms.
    query = """
    SELECT 
        disease_name, 
        icd_code, 
        definition, 
        synonyms
    FROM diseases
    WHERE disease_name IS NOT NULL AND disease_name != ''
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Fill NA
    df.fillna('', inplace=True)
    
    # Create a rich text representation for embedding
    df['text_to_embed'] = df.apply(lambda row: f"Disease: {row['disease_name']}\nICD Code: {row['icd_code']}\nSymptoms and Definition: {row['definition']}\nSynonyms: {row['synonyms']}", axis=1)
    
    print(f"Loaded {len(df)} diseases.")
    return df

def create_vector_store():
    df = load_data()
    
    # Use Langchain DataFrameLoader
    loader = DataFrameLoader(df, page_content_column="text_to_embed")
    documents = loader.load()
    
    print("Initializing embedding model (all-MiniLM-L6-v2)...")
    # This is a fast and good local model for semantic search
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    print("Creating Chroma vector store... This might take a few minutes depending on your CPU.")
    
    # Batch the documents to avoid memory issues
    batch_size = 500
    vectorstore = Chroma(embedding_function=embeddings, persist_directory=CHROMA_DIR)
    
    for i in tqdm(range(0, len(documents), batch_size)):
        batch = documents[i:i+batch_size]
        vectorstore.add_documents(batch)
        
    print(f"Vector store created successfully in '{CHROMA_DIR}' directory.")

if __name__ == "__main__":
    create_vector_store()
