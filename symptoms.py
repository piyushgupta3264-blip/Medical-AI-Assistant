import requests
import sqlite3
import time
import csv
import re
from collections import deque

# ============================================================
# WHO ICD-11 SYMPTOM COLLECTOR - FIXED & ENHANCED VERSION
# ============================================================
#
# WHAT WAS WRONG IN THE OLD VERSION:
#   - Crawled FOUNDATION ROOT (entire ICD-11 tree, ~100k+ entities)
#     instead of targeting the symptoms chapter specifically.
#   - is_symptom_entity() checked for metadata fields (classKind,
#     kind, entityType) that the API does NOT reliably return.
#   - Fallback keyword match caught disease entities whose
#     DEFINITIONS mention symptoms (e.g., "Beta thalassaemia").
#   - Result: 77 "symptoms" that are all actual diseases.
#
# WHAT THIS VERSION DOES:
#   Strategy 1: Extract from existing diseases DB (ICD-11 Chapter 21
#               codes MA-MH + symptom keyword name matching)
#   Strategy 2: Mine all 4,535 disease definitions for symptom
#               phrases using a comprehensive vocabulary
#   Strategy 3: Insert a curated master list of ~300 core symptoms
#   Strategy 4: API crawl ICD-11 MMS Chapter 21 for additional entries
#
# EXPECTED RESULT: 1000+ genuine, deduplicated symptoms
# ============================================================


# ============================================================
# CONFIG
# ============================================================

CLIENT_ID = "5ea0256b-98c5-48d6-a3de-09fc6fdafaaa_9c5f7d90-674a-43fc-918a-e82444d2341e"
CLIENT_SECRET = "yHFKFA7wkiXLrqGKDB9B57UU0xkUxTHPFzF2CtIVA38="

RELEASE = "2025-01"
LINEARIZATION = "mms"

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
BASE_URL = f"https://id.who.int/icd/release/11/{RELEASE}/{LINEARIZATION}"

DB_FILE = "icd11_complete.db"
CSV_FILE = "icd11_symptoms.csv"

REQUEST_DELAY = 0.12
MAX_RETRIES = 3

ACCESS_TOKEN = None


# ============================================================
# HELPERS (defined first so they can be used below)
# ============================================================

def normalize_name(name):
    """Lowercase + strip + collapse whitespace for deduplication."""
    if not name:
        return ""
    return re.sub(r'\s+', ' ', name.strip().lower())


def clean_text(value):
    """Extract string from ICD-11 JSON-LD value or plain string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if "@value" in value:
            return str(value["@value"]).strip()
        if "value" in value:
            return str(value["value"]).strip()
        if "@id" in value:
            return str(value["@id"]).strip()
    return str(value).strip()


def normalize_uri(uri):
    if not uri:
        return ""
    return uri.replace("http://id.who.int", "https://id.who.int")


def get_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# ============================================================
# CURATED MASTER SYMPTOM LIST (~300 core symptoms)
# Covers all major body systems — used as reliable baseline
# ============================================================

MASTER_SYMPTOMS = [

    # --- GENERAL / CONSTITUTIONAL ---
    "Fever", "High temperature", "Low-grade fever", "Chills", "Rigors",
    "Night sweats", "Fatigue", "Tiredness", "Weakness", "Malaise",
    "Lethargy", "Loss of energy", "Weight loss", "Unintentional weight loss",
    "Weight gain", "Poor appetite", "Loss of appetite", "Anorexia",
    "Cachexia", "Dehydration", "Excessive thirst", "Polydipsia",
    "Excessive hunger", "Polyphagia", "Pallor", "Jaundice", "Cyanosis",
    "Flushing", "Sweating", "Excessive sweating", "Hyperhidrosis",
    "Hot flushes", "Cold intolerance", "Heat intolerance",
    "Generalised swelling", "Oedema", "Lymphadenopathy",
    "Unexplained bruising", "Easy bruising",

    # --- PAIN ---
    "Pain", "Acute pain", "Chronic pain", "Burning pain", "Stabbing pain",
    "Throbbing pain", "Aching pain", "Sharp pain", "Dull pain",
    "Headache", "Migraine", "Cluster headache", "Tension headache",
    "Facial pain", "Jaw pain", "Neck pain", "Back pain",
    "Lower back pain", "Upper back pain", "Chest pain", "Chest tightness",
    "Chest pressure", "Abdominal pain", "Stomach pain", "Epigastric pain",
    "Pelvic pain", "Flank pain", "Shoulder pain", "Arm pain",
    "Elbow pain", "Wrist pain", "Hand pain", "Hip pain", "Knee pain",
    "Leg pain", "Ankle pain", "Foot pain", "Heel pain",
    "Joint pain", "Arthralgia", "Muscle pain", "Myalgia", "Bone pain",
    "Nerve pain", "Neuropathic pain", "Eye pain", "Ear pain", "Otalgia",
    "Throat pain", "Sore throat", "Groin pain", "Testicular pain",
    "Dysmenorrhoea", "Pelvic cramps", "Sciatica", "Radiating leg pain",

    # --- CARDIOVASCULAR ---
    "Palpitations", "Heart palpitations", "Irregular heartbeat",
    "Rapid heartbeat", "Tachycardia", "Slow heartbeat", "Bradycardia",
    "Shortness of breath", "Breathlessness", "Dyspnoea", "Orthopnoea",
    "Paroxysmal nocturnal dyspnoea", "Chest discomfort",
    "Ankle swelling", "Leg swelling", "Pedal oedema", "Pitting oedema",
    "Facial swelling", "Syncope", "Fainting", "Blackout",
    "Presyncope", "Near fainting", "Dizziness", "Lightheadedness",
    "Bounding pulse", "Weak pulse", "Cold extremities", "Clammy skin",
    "Peripheral cyanosis", "Central cyanosis", "Finger clubbing",
    "Raised jugular venous pressure",

    # --- RESPIRATORY ---
    "Cough", "Dry cough", "Productive cough", "Wet cough",
    "Coughing up blood", "Haemoptysis", "Wheezing", "Stridor",
    "Hoarseness", "Voice change", "Difficulty breathing",
    "Rapid breathing", "Tachypnoea", "Slow breathing", "Bradypnoea",
    "Apnoea", "Snoring", "Sleep apnoea", "Nasal congestion",
    "Runny nose", "Rhinorrhoea", "Nasal discharge", "Postnasal drip",
    "Sneezing", "Epistaxis", "Nosebleed", "Haemothorax",
    "Pleuritic chest pain",

    # --- GASTROINTESTINAL ---
    "Nausea", "Vomiting", "Retching", "Regurgitation", "Heartburn",
    "Acid reflux", "Indigestion", "Dyspepsia", "Bloating", "Flatulence",
    "Belching", "Hiccups", "Difficulty swallowing", "Dysphagia",
    "Odynophagia", "Painful swallowing", "Constipation", "Diarrhoea",
    "Loose stools", "Bloody stools", "Rectal bleeding", "Blood in stool",
    "Melaena", "Haematochezia", "Mucus in stool", "Steatorrhoea",
    "Fatty stools", "Bowel incontinence", "Faecal incontinence",
    "Abdominal distension", "Abdominal bloating", "Abdominal cramps",
    "Tenesmus", "Rectal pain", "Anal pain",
    "Change in bowel habit", "Loss of bowel control",
    "Vomiting blood", "Haematemesis", "Dark urine", "Pale stools",
    "Abdominal tenderness", "Abdominal rigidity", "Rebound tenderness",
    "Splenomegaly", "Hepatomegaly", "Hepatosplenomegaly", "Ascites",

    # --- NEUROLOGICAL ---
    "Confusion", "Disorientation", "Altered consciousness",
    "Loss of consciousness", "Unconsciousness", "Seizure", "Convulsion",
    "Epileptic fit", "Tremor", "Shaking", "Involuntary movements",
    "Muscle spasms", "Muscle cramps", "Muscle twitching", "Fasciculations",
    "Limb weakness", "Paralysis", "Hemiplegia", "Paraplegia",
    "Numbness", "Tingling", "Pins and needles", "Paraesthesia",
    "Loss of sensation", "Hypoaesthesia", "Hyperaesthesia",
    "Memory loss", "Amnesia", "Forgetfulness", "Cognitive decline",
    "Dementia", "Difficulty concentrating", "Poor concentration",
    "Speech difficulty", "Dysarthria", "Aphasia", "Slurred speech",
    "Word-finding difficulty", "Gait disturbance", "Difficulty walking",
    "Ataxia", "Balance problems", "Unsteadiness", "Falls",
    "Vertigo", "Spinning sensation", "Tinnitus", "Ringing in ears",
    "Photophobia", "Phonophobia", "Neck stiffness", "Meningism",
    "Bradykinesia", "Rigidity", "Shuffling gait", "Festinating gait",
    "Intention tremor", "Resting tremor", "Chorea", "Dystonia",
    "Spasticity", "Hyperreflexia", "Hyporeflexia", "Areflexia",
    "Restless legs", "Peripheral neuropathy symptoms",

    # --- PSYCHIATRIC / BEHAVIOURAL ---
    "Anxiety", "Panic attacks", "Depression", "Low mood", "Sadness",
    "Hopelessness", "Suicidal thoughts", "Self-harm", "Aggression",
    "Irritability", "Mood swings", "Emotional lability",
    "Hallucinations", "Visual hallucinations", "Auditory hallucinations",
    "Delusions", "Paranoia", "Psychosis",
    "Mania", "Euphoria", "Agitation", "Restlessness",
    "Insomnia", "Difficulty sleeping", "Sleep disturbance", "Hypersomnia",
    "Excessive sleepiness", "Somnolence", "Nightmares",
    "Obsessive thoughts", "Compulsive behaviour",
    "Social withdrawal", "Personality change", "Behavioural change",
    "Disorganised thinking", "Thought disorder", "Cognitive impairment",

    # --- MUSCULOSKELETAL ---
    "Joint swelling", "Joint stiffness", "Morning stiffness",
    "Reduced range of motion", "Joint locking", "Joint clicking",
    "Muscle weakness", "Muscle wasting", "Muscle atrophy",
    "Muscle stiffness", "Tendon pain", "Bone swelling", "Bone tenderness",
    "Back stiffness", "Limited mobility", "Inability to walk", "Limping",
    "Crepitus", "Synovitis",

    # --- SKIN / DERMATOLOGICAL ---
    "Rash", "Skin rash", "Hives", "Urticaria", "Itching", "Pruritus",
    "Skin redness", "Erythema", "Skin blistering", "Blisters",
    "Vesicles", "Pustules", "Skin peeling", "Desquamation",
    "Dry skin", "Oily skin", "Acne", "Skin thickening",
    "Pigmentation changes", "Hyperpigmentation", "Hypopigmentation",
    "Vitiligo", "Skin ulcer", "Leg ulcer", "Pressure sore",
    "Bruising", "Ecchymosis", "Petechiae", "Purpura",
    "Spider angioma", "Telangiectasia", "Skin nodule", "Lump under skin",
    "Hair loss", "Alopecia", "Nail changes", "Nail discolouration",
    "Leukoplakia", "Hirsutism", "Livedo reticularis",

    # --- EYE (OPHTHALMOLOGICAL) ---
    "Blurred vision", "Double vision", "Diplopia", "Vision loss",
    "Visual disturbance", "Eye redness", "Conjunctivitis",
    "Watery eyes", "Excessive tearing", "Lacrimation", "Dry eyes",
    "Light sensitivity", "Eye discharge", "Eye swelling", "Ptosis",
    "Drooping eyelid", "Eye twitching", "Floaters", "Flashes of light",
    "Field of vision loss", "Tunnel vision", "Night blindness",
    "Exophthalmos", "Proptosis", "Protruding eyes",

    # --- EAR, NOSE & THROAT (ENT) ---
    "Hearing loss", "Deafness", "Ear discharge", "Ear pain",
    "Blocked ears", "Muffled hearing", "Sore throat", "Throat tightness",
    "Difficulty speaking", "Voice hoarseness", "Loss of voice",
    "Swollen lymph nodes", "Neck lump", "Nasal polyps",
    "Loss of smell", "Anosmia", "Loss of taste", "Ageusia",
    "Altered taste", "Dysgeusia", "Mouth sores", "Oral ulcers",
    "Gum pain", "Toothache", "Jaw pain", "Trismus",
    "Pharyngitis", "Tonsillitis",

    # --- UROLOGICAL / RENAL ---
    "Frequent urination", "Polyuria", "Increased urination",
    "Reduced urination", "Oliguria", "No urine output", "Anuria",
    "Painful urination", "Dysuria", "Burning on urination",
    "Blood in urine", "Haematuria", "Cloudy urine", "Frothy urine",
    "Urinary incontinence", "Urinary urgency", "Urinary retention",
    "Difficulty urinating", "Weak urine stream",
    "Nocturia", "Bedwetting", "Enuresis", "Renal colic",
    "Penile discharge", "Urethral discharge", "Proteinuria",

    # --- GYNAECOLOGICAL / REPRODUCTIVE ---
    "Irregular periods", "Irregular menstruation", "Missed period",
    "Amenorrhoea", "Heavy periods", "Menorrhagia", "Painful periods",
    "Intermenstrual bleeding", "Postmenopausal bleeding",
    "Vaginal discharge", "Vaginal itching", "Vaginal dryness",
    "Dyspareunia", "Painful intercourse",
    "Breast pain", "Breast tenderness", "Mastalgia", "Nipple discharge",
    "Breast lump", "Reduced libido", "Galactorrhoea",

    # --- ENDOCRINE / METABOLIC ---
    "Goitre", "Neck swelling", "Tremor", "Sweating",
    "Dry hair", "Hair thinning", "Growth retardation", "Short stature",
    "Delayed puberty", "Moon face", "Buffalo hump", "Stretch marks",
    "Striae", "Gynaecomastia", "Virilisation",
    "Hypoglycaemia", "Hyperglycaemia",

    # --- HAEMATOLOGICAL / ONCOLOGICAL ---
    "Anaemia symptoms", "Dyspnoea on exertion", "Prolonged bleeding",
    "Recurrent infections", "Unexplained fever", "Bone marrow pain",
    "Leukaemia symptoms",
]


# ============================================================
# ICD-11 SYMPTOM CHAPTER CODE PREFIXES
# Chapter 21: Symptoms, signs or clinical findings (MA-MH)
# ============================================================

SYMPTOM_ICD_PREFIXES = [
    'MA', 'MB', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH',
]

# Disease name keywords that strongly indicate the entity is a symptom/sign
SYMPTOM_NAME_KEYWORDS = [
    "symptom", "sign of", "clinical finding", "clinical sign",
    "pain", "ache", " aching", "fever", "cough",
    "nausea", "vomiting", "diarrhoea", "diarrhea",
    "fatigue", "weakness", "malaise",
    "dizziness", "vertigo", "syncope",
    "breathlessness", "dyspnoea", "palpitation",
    "haemorrhage", "haemoptysis", "epistaxis", "haematuria", "haematemesis",
    "oedema", "swelling", "lymphadenopathy", "splenomegaly", "hepatomegaly",
    "rash", "pruritus", "itching",
    "numbness", "tingling", "paraesthesia", "paralysis",
    "tremor", "seizure", "convulsion", "ataxia",
    "confusion", "amnesia", "aphasia", "dysarthria",
    "insomnia", "anorexia", "jaundice", "cyanosis", "pallor",
    "tachycardia", "bradycardia", "polyuria", "dysuria",
    "dysphagia", "constipation", "headache",
    "chills", "rigors", "night sweats",
    "tinnitus", "hearing loss", "vision loss", "diplopia", "photophobia",
    "discharge", "incontinence", "distension", "bloating",
    "hypotension", "tachypnoea", "bradypnoea",
    "myalgia", "arthralgia",
]


# ============================================================
# COMPREHENSIVE VOCABULARY FOR DEFINITION MINING
# ============================================================

CLINICAL_TERMS = [
    "fever", "pain", "ache", "aching", "nausea", "vomiting", "diarrhoea",
    "diarrhea", "fatigue", "weakness", "malaise", "cough", "breathlessness",
    "dyspnoea", "tachycardia", "bradycardia", "palpitations", "oedema",
    "swelling", "rash", "pruritus", "itching", "jaundice", "pallor",
    "cyanosis", "anaemia", "haemorrhage", "bleeding", "bruising",
    "lymphadenopathy", "splenomegaly", "hepatomegaly", "hepatosplenomegaly",
    "seizure", "convulsion", "tremor", "ataxia", "paralysis",
    "numbness", "tingling", "paraesthesia", "confusion", "disorientation",
    "amnesia", "aphasia", "dysarthria", "vertigo", "dizziness", "syncope",
    "headache", "migraine", "photophobia", "phonophobia", "neck stiffness",
    "haematemesis", "melaena", "haematuria", "proteinuria",
    "polyuria", "oliguria", "dysuria", "frequency", "urgency",
    "incontinence", "constipation", "bloating", "flatulence",
    "dysphagia", "odynophagia", "anorexia", "cachexia",
    "polydipsia", "polyphagia", "weight loss", "weight gain",
    "chills", "night sweats", "rigors", "hyperthermia",
    "hypothermia", "hypotension", "hypertension", "tachypnoea",
    "bradypnoea", "stridor", "wheezing", "haemoptysis", "epistaxis",
    "rhinorrhoea", "nasal congestion", "sneezing", "anosmia",
    "ageusia", "dysgeusia", "tinnitus", "hearing loss", "otalgia",
    "vision loss", "blurred vision", "diplopia",
    "eye pain", "eye redness", "lacrimation", "ptosis",
    "alopecia", "hair loss", "nail changes", "skin ulcer",
    "erythema", "urticaria", "angioedema", "petechiae", "purpura",
    "ecchymosis", "xerosis", "hyperpigmentation", "hypopigmentation",
    "anxiety", "depression", "insomnia", "agitation", "psychosis",
    "hallucinations", "delusions", "cognitive decline",
    "steatorrhoea", "haemoglobinuria", "myalgia", "arthralgia",
    "myopathy", "neuropathy", "wasting", "growth retardation",
    "amenorrhoea", "menorrhagia", "dysmenorrhoea", "galactorrhoea",
    "gynaecomastia", "goitre", "hirsutism",
    "bradykinesia", "rigidity", "chorea", "dystonia",
    "spasticity", "hyperreflexia", "fasciculations", "restless legs",
    "ascites", "pleural effusion", "pericardial effusion",
    "exophthalmos", "proptosis", "clubbing",
    "leukoplakia", "oral candidiasis", "glossitis", "stomatitis",
    "pharyngitis", "tonsillitis", "lymphadenitis", "cellulitis",
    "abscess", "fistula", "discharge", "exudate",
    "shock", "collapse", "syncope", "pre-syncope",
    "dyspnoea on exertion", "orthopnoea",
    "paroxysmal nocturnal dyspnoea",
    "peripheral oedema", "pulmonary oedema",
    "increased intracranial pressure", "papilloedema",
    "nystagmus", "ophthalmoplegia", "strabismus",
    "acne", "seborrhoea", "psoriasis symptoms", "eczema symptoms",
    "rectal bleeding", "blood in stool", "haematochezia",
    "rectal pain", "tenesmus", "anal fissure symptoms",
    "urethral discharge", "penile discharge", "vaginal discharge",
    "vaginal itching", "dyspareunia", "pelvic inflammatory symptoms",
    "breast lump", "breast pain", "nipple discharge",
    "bone pain", "bone tenderness", "pathological fracture",
    "muscle weakness", "muscle wasting", "muscle cramps",
    "joint swelling", "joint stiffness", "morning stiffness", "crepitus",
    "skin discolouration", "livedo reticularis", "spider naevi",
    "palmar erythema", "xanthoma", "xanthelasma",
    "lump", "mass", "swollen lymph nodes", "enlarged lymph nodes",
    "abdominal mass", "breast mass", "testicular mass",
    "neck mass", "thyroid nodule", "enlarged thyroid",
    "reduced libido", "erectile dysfunction", "infertility",
    "early satiety", "postprandial fullness",
    "recurrent infections", "opportunistic infections",
    "delayed healing", "easy bruising", "prolonged bleeding",
]


# ============================================================
# AUTH
# ============================================================

def get_access_token():
    global ACCESS_TOKEN
    print("\nGetting WHO access token...")
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "icdapi_access"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(TOKEN_URL, data=data, headers=headers, timeout=30)
    print("Authentication status:", response.status_code)
    if response.status_code != 200:
        print("WHO authentication error:", response.text)
        raise RuntimeError("WHO authentication failed.")
    result = response.json()
    ACCESS_TOKEN = result["access_token"]
    print(
        "Authentication successful. Token expires in:",
        result.get("expires_in"),
        "seconds"
    )
    return ACCESS_TOKEN


def get_headers():
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json",
        "Accept-Language": "en",
        "API-Version": "v2"
    }


def get_request(url):
    global ACCESS_TOKEN
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=get_headers(), timeout=60)
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    print("Invalid JSON:", url)
                    return None
            if response.status_code == 401:
                print("Token expired. Refreshing...")
                get_access_token()
                continue
            if response.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"Rate limit. Waiting {wait}s...")
                time.sleep(wait)
                continue
            if response.status_code == 404:
                return None
            print("HTTP error:", response.status_code, "|", url)
            return None
        except requests.exceptions.Timeout:
            print("Timeout. Retrying...")
            time.sleep(3)
        except requests.exceptions.RequestException as e:
            print("Network error:", e)
            time.sleep(3)
    return None


# ============================================================
# DATABASE
# ============================================================

def connect_database():
    return sqlite3.connect(DB_FILE)


def setup_symptoms_table(conn):
    """
    Create or migrate the symptoms table.
    Adds new columns if the table already exists with old schema.
    """
    cursor = conn.cursor()

    # Create table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS symptoms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symptom_name TEXT,
            normalized_name TEXT,
            definition TEXT,
            synonyms TEXT,
            uri TEXT,
            icd_code TEXT,
            source TEXT,
            parent TEXT,
            children TEXT,
            release TEXT,
            body_system TEXT
        )
    """)
    conn.commit()

    # Get existing columns
    cursor.execute("PRAGMA table_info(symptoms)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    # Add any missing columns from new schema
    new_columns = {
        "normalized_name": "TEXT",
        "icd_code": "TEXT",
        "body_system": "TEXT",
    }
    for col, dtype in new_columns.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE symptoms ADD COLUMN {col} {dtype}")
            print(f"  Added column: {col}")

    # Create indexes
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sym_norm "
        "ON symptoms(normalized_name)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sym_name_unique "
        "ON symptoms(normalized_name)"
    )
    conn.commit()
    print("Symptoms table ready.")


def clear_wrong_symptoms(conn):
    """
    The old crawler stored disease entities as symptoms.
    Remove them by cross-checking against the diseases table.
    We keep anything that was correctly identified.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM symptoms")
    before = cursor.fetchone()[0]

    if before == 0:
        print("Symptoms table is empty — nothing to clean.")
        return

    # Remove entries whose names exactly match disease names
    cursor.execute("""
        DELETE FROM symptoms
        WHERE id IN (
            SELECT s.id FROM symptoms s
            INNER JOIN diseases d
                ON LOWER(TRIM(s.symptom_name)) = LOWER(TRIM(d.disease_name))
        )
    """)
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM symptoms")
    after = cursor.fetchone()[0]

    removed = before - after
    print(f"  Removed {removed} incorrect disease entries from symptoms table.")
    print(f"  Remaining genuine symptoms: {after}")


def symptom_exists(conn, normalized):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM symptoms WHERE normalized_name = ? LIMIT 1",
        (normalized,)
    )
    return cursor.fetchone() is not None


def insert_symptom(conn, name, definition="", uri="", icd_code="",
                   source="", synonyms="", parent="", children="",
                   body_system=""):
    """
    Insert a new symptom. Uses normalized_name for deduplication.
    Returns True if inserted, False if duplicate or invalid.
    """
    name = name.strip() if name else ""
    if not name or len(name) < 3:
        return False

    norm = normalize_name(name)
    if not norm:
        return False

    # Skip if it's a disease name (extra safety check)
    if _is_disease_name(norm):
        return False

    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO symptoms
            (
                symptom_name, normalized_name, definition, synonyms,
                uri, icd_code, source, parent, children, release, body_system
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            norm,
            definition or "",
            synonyms or "",
            uri or "",
            icd_code or "",
            source or "",
            parent or "",
            children or "",
            RELEASE,
            body_system or "",
        ))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.IntegrityError:
        return False
    except sqlite3.Error as e:
        print("DB error:", e)
        return False


# Cache of disease names (normalized) for fast lookup
_DISEASE_NAME_CACHE = None


def _load_disease_cache(conn=None):
    global _DISEASE_NAME_CACHE
    if _DISEASE_NAME_CACHE is None:
        _DISEASE_NAME_CACHE = set()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT disease_name FROM diseases")
            for row in cursor.fetchall():
                if row[0]:
                    _DISEASE_NAME_CACHE.add(normalize_name(row[0]))
    return _DISEASE_NAME_CACHE


def _is_disease_name(normalized_name):
    """Return True if this normalized name is a disease, not a symptom."""
    cache = _DISEASE_NAME_CACHE or set()
    return normalized_name in cache


def get_symptom_count(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM symptoms")
    return cursor.fetchone()[0]


# ============================================================
# STRATEGY 1: EXTRACT FROM EXISTING DISEASES DB
# ============================================================

def strategy1_from_diseases_db(conn):
    """
    Pull genuine symptom entities already collected in the diseases table.

    Part A: Entries with ICD-11 Chapter 21 codes (MA-MH).
            These ARE the official symptom/sign entities.

    Part B: Entries whose disease_name contains strong symptom keywords.
            e.g., "Fever of unknown origin", "Chronic fatigue syndrome",
            "Vertigo", etc. Many symptom-like entities sit in other chapters.
    """
    print()
    print("=" * 60)
    print("STRATEGY 1: Extracting from existing diseases DB")
    print("=" * 60)

    cursor = conn.cursor()
    added = 0
    skipped = 0

    # ----------------------------------------------------------
    # Part A: ICD Chapter 21 codes (MA, MB, MC, MD, ME, MF, MG, MH)
    # ----------------------------------------------------------
    conditions = " OR ".join(
        ["icd_code LIKE ?"] * len(SYMPTOM_ICD_PREFIXES)
    )
    params = [f"{prefix}%" for prefix in SYMPTOM_ICD_PREFIXES]

    cursor.execute(f"""
        SELECT disease_name, definition, uri, icd_code,
               synonyms, parent, children
        FROM diseases
        WHERE {conditions}
    """, params)

    rows = cursor.fetchall()
    print(f"Part A: {len(rows)} entities with symptom chapter codes (MA-MH)")

    for row in rows:
        name, definition, uri, icd_code, synonyms, parent, children = row
        if not name:
            continue
        ok = insert_symptom(
            conn, name,
            definition=definition or "",
            uri=uri or "",
            icd_code=icd_code or "",
            source="ICD-11 MMS Chapter 21",
            synonyms=synonyms or "",
            parent=parent or "",
            children=children or ""
        )
        if ok:
            added += 1
        else:
            skipped += 1

    print(f"  Added: {added} | Skipped (duplicates/diseases): {skipped}")

    # ----------------------------------------------------------
    # Part B: Symptom-keyword name matching
    # ----------------------------------------------------------
    print(f"\nPart B: Searching disease names for symptom keywords...")
    b_added = 0
    b_skipped = 0

    for keyword in SYMPTOM_NAME_KEYWORDS:
        cursor.execute("""
            SELECT disease_name, definition, uri, icd_code,
                   synonyms, parent, children
            FROM diseases
            WHERE LOWER(disease_name) LIKE ?
        """, (f"%{keyword}%",))
        rows = cursor.fetchall()
        for row in rows:
            name, definition, uri, icd_code, synonyms, parent, children = row
            if not name:
                continue
            ok = insert_symptom(
                conn, name,
                definition=definition or "",
                uri=uri or "",
                icd_code=icd_code or "",
                source="ICD-11 MMS (symptom name keyword match)",
                synonyms=synonyms or "",
                parent=parent or "",
                children=children or ""
            )
            if ok:
                b_added += 1
            else:
                b_skipped += 1

    print(f"  Added: {b_added} | Skipped: {b_skipped}")
    print(f"\nStrategy 1 total added: {added + b_added}")
    print(f"Total symptoms now: {get_symptom_count(conn)}")
    return added + b_added


# ============================================================
# STRATEGY 2: MINE DISEASE DEFINITIONS
# ============================================================

# Build normalized vocabulary set for fast lookup
_VOCAB_NORMALIZED = {normalize_name(t) for t in CLINICAL_TERMS}
# Also include multi-word terms from MASTER_SYMPTOMS
_VOCAB_NORMALIZED.update(
    normalize_name(s) for s in MASTER_SYMPTOMS
)

# Regex extraction patterns for symptom phrases in definitions
EXTRACTION_PATTERNS = [
    r'presents?\s+with\s+([\w\s,;/\-\']+?)(?:\.|,\s+and\s+\w+\s+(?:confirm|reveal|show)|;|$)',
    r'presenting\s+with\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'characteri[sz]ed\s+by\s+([\w\s,;/\-\']+?)(?:\.|;|which|including|such as|$)',
    r'symptoms?\s+(?:include|are|such as|of|:)\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'signs?\s+(?:include|are|such as|of|:)\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'may\s+(?:present|manifest|appear)\s+with\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'clinical\s+(?:features?|manifestations?|findings?)\s+(?:include|are|:)\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'disease\s+is\s+characterised?\s+by\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'manifests?\s+(?:as|with)\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'associated\s+with\s+([\w\s,;/\-\']+?)(?:\.|;|$)',
    r'including\s+((?:[\w\s\-\']+)(?:,\s*[\w\s\-\']+)*)\s+(?:and|or)\s+([\w\s\-\']+)',
]

SKIP_WORDS = {
    'the', 'and', 'or', 'in', 'of', 'a', 'an', 'is', 'are',
    'with', 'by', 'from', 'to', 'for', 'this', 'that', 'these',
    'which', 'may', 'can', 'be', 'been', 'has', 'have', 'had',
    'its', 'it', 'their', 'our', 'such', 'as', 'also', 'if',
    'but', 'so', 'then', 'due', 'well', 'other', 'both', 'all',
    'more', 'most', 'some', 'any', 'each', 'no', 'not', 'only',
    'include', 'includes', 'including', 'cause', 'caused', 'causes',
}


def _is_valid_extracted_term(token):
    """Validate that an extracted token is a plausible symptom term."""
    token = token.strip().lower()
    if len(token) < 4 or len(token) > 60:
        return False
    if token.isdigit():
        return False
    if token in SKIP_WORDS:
        return False
    if not re.search(r'[a-z]', token):
        return False
    # Must not start with a number
    if re.match(r'^\d', token):
        return False
    return True


def extract_symptoms_from_definition(definition_text):
    """
    Extract symptom terms from a disease definition using two methods:
    1. Vocabulary keyword match (exact term match)
    2. Pattern-based phrase extraction + vocabulary validation
    """
    found = set()
    text_lower = definition_text.lower()

    # --- Method A: Vocabulary matching ---
    for term in _VOCAB_NORMALIZED:
        if len(term) < 4:
            continue
        # Match as whole word or phrase
        escaped = re.escape(term)
        if re.search(r'\b' + escaped + r'\b', text_lower):
            found.add(term)

    # --- Method B: Pattern-based extraction ---
    for pattern in EXTRACTION_PATTERNS:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        for match in matches:
            # Handle tuple matches (from groups)
            if isinstance(match, tuple):
                match = ' '.join(match)
            # Split on commas/semicolons/and/or
            parts = re.split(r'[,;]|\band\b|\bor\b', match)
            for part in parts:
                part = re.sub(r'\s+', ' ', part).strip().strip('.')
                if not _is_valid_extracted_term(part):
                    continue
                part_norm = normalize_name(part)
                # Only include if it overlaps with known vocab
                for vocab_term in _VOCAB_NORMALIZED:
                    if (vocab_term in part_norm or
                            part_norm in vocab_term):
                        found.add(part_norm)
                        break

    return found


def strategy2_mine_definitions(conn):
    """
    Scan all 4,535 disease definitions and extract symptom mentions.
    Uses vocabulary matching + regex phrase extraction.
    """
    print()
    print("=" * 60)
    print("STRATEGY 2: Mining disease definitions for symptoms")
    print("=" * 60)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT disease_name, definition, uri
        FROM diseases
        WHERE definition IS NOT NULL AND TRIM(definition) != ''
    """)
    diseases = cursor.fetchall()
    print(f"Processing {len(diseases)} diseases with definitions...")

    # Collect all found symptom terms across all definitions
    all_extracted = {}   # normalized_term -> count (how many diseases mention it)
    processed = 0

    for disease_name, definition, uri in diseases:
        if not definition:
            continue

        symptoms_in_this = extract_symptoms_from_definition(definition)
        for s in symptoms_in_this:
            all_extracted[s] = all_extracted.get(s, 0) + 1

        processed += 1
        if processed % 500 == 0:
            print(f"  Processed {processed}/{len(diseases)} diseases...")

    print(f"\nExtracted {len(all_extracted)} unique symptom terms across all definitions")

    # Insert them — use proper casing
    added = 0
    skipped = 0

    # Sort by frequency (most mentioned first) for better canonical naming
    sorted_terms = sorted(
        all_extracted.items(),
        key=lambda x: x[1],
        reverse=True
    )

    for term_norm, count in sorted_terms:
        # Find the best canonical form from MASTER_SYMPTOMS if available
        canonical = None
        for master in MASTER_SYMPTOMS:
            if normalize_name(master) == term_norm:
                canonical = master
                break
        if canonical is None:
            canonical = term_norm.title()  # fallback: title case

        ok = insert_symptom(
            conn,
            canonical,
            definition="",
            uri="",
            icd_code="",
            source=f"Extracted from disease definitions (mentioned in {count} diseases)",
        )
        if ok:
            added += 1
        else:
            skipped += 1

    print(f"Strategy 2 complete. Added: {added} | Skipped (duplicates): {skipped}")
    print(f"Total symptoms now: {get_symptom_count(conn)}")
    return added


# ============================================================
# STRATEGY 3: CURATED MASTER SYMPTOM LIST
# ============================================================

def strategy3_curated_list(conn):
    """
    Insert the comprehensive curated symptom list as a reliable baseline.
    These ~300 symptoms cover all major body systems and are guaranteed
    to be genuine symptoms (not diseases).
    """
    print()
    print("=" * 60)
    print("STRATEGY 3: Adding curated master symptom list")
    print("=" * 60)

    added = 0
    skipped = 0

    for symptom in MASTER_SYMPTOMS:
        symptom = symptom.strip()
        if not symptom:
            continue
        ok = insert_symptom(
            conn,
            symptom,
            definition="",
            uri="",
            icd_code="",
            source="Curated symptom vocabulary",
        )
        if ok:
            added += 1
        else:
            skipped += 1

    print(f"Strategy 3 complete. Added: {added} | Skipped (duplicates): {skipped}")
    print(f"Total symptoms now: {get_symptom_count(conn)}")
    return added


# ============================================================
# STRATEGY 4: ICD-11 MMS API CRAWL (Chapter 21 only)
# ============================================================

def _find_chapter21_url():
    """
    Walk the MMS root children to find Chapter 21
    (Symptoms, signs or clinical findings).
    """
    print("\nFinding ICD-11 MMS Chapter 21 URL...")

    root = get_request(BASE_URL)
    if not root:
        print("Could not get MMS root.")
        return None

    children = get_list(root.get("child", []))
    print(f"MMS root has {len(children)} top-level chapters")

    for child in children:
        # child may be a string URI or a dict with @id
        if isinstance(child, str):
            child_url = normalize_uri(child)
        elif isinstance(child, dict):
            child_url = normalize_uri(child.get("@id", ""))
        else:
            continue

        if not child_url:
            continue

        time.sleep(REQUEST_DELAY)
        data = get_request(child_url)
        if not data:
            continue

        title = clean_text(data.get("title", "")).lower()
        code = clean_text(data.get("code", ""))
        print(f"  [{code}] {title[:60]}")

        # Chapter 21 title contains "symptom" or "sign" or "clinical finding"
        if any(kw in title for kw in
               ["symptom", "sign", "clinical finding"]):
            print(f"  [FOUND] Symptom chapter: {title}")
            return child_url

    return None


def strategy4_api_crawl(conn):
    """
    Crawl ICD-11 MMS Chapter 21 via the WHO API.
    This fetches every entity in the official symptoms chapter
    and inserts it into the symptoms table.

    This strategy requires internet access and WHO credentials.
    """
    print()
    print("=" * 60)
    print("STRATEGY 4: ICD-11 MMS API crawl (Chapter 21)")
    print("=" * 60)

    # Authenticate
    try:
        get_access_token()
    except Exception as e:
        print("Authentication failed:", e)
        print("Skipping Strategy 4 (no API access).")
        return 0

    # Find the Chapter 21 URL
    chapter_url = _find_chapter21_url()
    if not chapter_url:
        print("Could not locate Chapter 21. Skipping Strategy 4.")
        return 0

    print(f"\nCrawling from: {chapter_url}")

    queue = deque([chapter_url])
    visited = set()
    added = 0
    processed = 0
    failed = 0

    while queue:
        url = queue.popleft()
        url = normalize_uri(url)

        if url in visited:
            continue
        visited.add(url)

        data = get_request(url)
        if not data:
            failed += 1
            continue

        processed += 1

        # --- Extract entity data ---
        title = clean_text(data.get("title", ""))
        definition = clean_text(data.get("definition", ""))
        icd_code = clean_text(data.get("code", ""))
        uri = normalize_uri(clean_text(data.get("@id", "")))

        # Synonyms
        synonyms = []
        for syn in get_list(data.get("synonym", [])):
            if isinstance(syn, dict):
                label = syn.get("label", {})
                synonyms.append(clean_text(label))
            elif isinstance(syn, str):
                synonyms.append(syn)

        # Parents
        parents = []
        for p in get_list(data.get("parent", [])):
            if isinstance(p, str):
                parents.append(normalize_uri(p))
            elif isinstance(p, dict):
                parents.append(normalize_uri(p.get("@id", "")))

        # Children — add to queue
        children_uris = []
        for child in get_list(data.get("child", [])):
            if isinstance(child, str):
                c_url = normalize_uri(child)
            elif isinstance(child, dict):
                c_url = normalize_uri(child.get("@id", ""))
            else:
                continue
            children_uris.append(c_url)
            if c_url not in visited:
                queue.append(c_url)

        # Insert
        if title:
            ok = insert_symptom(
                conn,
                title,
                definition=definition,
                uri=uri,
                icd_code=icd_code,
                source="ICD-11 MMS Chapter 21 API",
                synonyms=" | ".join(s for s in synonyms if s),
                parent=" | ".join(p for p in parents if p),
                children=" | ".join(c for c in children_uris if c),
            )
            if ok:
                added += 1
                print(f"  [+] [{icd_code}] {title}")

        if processed % 100 == 0:
            print(
                f"\n  Processed: {processed} | "
                f"Added: {added} | "
                f"Failed: {failed} | "
                f"Queue: {len(queue)}"
            )
            print(f"  Total symptoms: {get_symptom_count(conn)}\n")

        time.sleep(REQUEST_DELAY)

    print(
        f"\nStrategy 4 complete. "
        f"Processed: {processed} | "
        f"Added: {added} | "
        f"Failed: {failed}"
    )
    print(f"Total symptoms now: {get_symptom_count(conn)}")
    return added


# ============================================================
# EXPORT CSV
# ============================================================

def export_csv(conn):
    print("\nExporting symptoms to CSV...")

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            id,
            symptom_name,
            normalized_name,
            definition,
            synonyms,
            uri,
            icd_code,
            source,
            body_system,
            release
        FROM symptoms
        ORDER BY symptom_name
    """)
    rows = cursor.fetchall()
    columns = [col[0] for col in cursor.description]

    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"CSV saved: {CSV_FILE}")
    print(f"Total rows exported: {len(rows)}")


# ============================================================
# FINAL SUMMARY
# ============================================================

def show_summary(conn):
    cursor = conn.cursor()

    print()
    print("=" * 60)
    print("FINAL SYMPTOM DATABASE SUMMARY")
    print("=" * 60)

    cursor.execute("SELECT COUNT(*) FROM symptoms")
    total = cursor.fetchone()[0]
    print(f"Total unique symptoms: {total}")

    print("\nBreakdown by source:")
    cursor.execute("""
        SELECT source, COUNT(*) as cnt
        FROM symptoms
        GROUP BY source
        ORDER BY cnt DESC
    """)
    for row in cursor.fetchall():
        print(f"  {row[1]:>5}  |  {row[0]}")

    print("\nRandom sample of 25 symptoms:")
    cursor.execute("SELECT symptom_name FROM symptoms ORDER BY RANDOM() LIMIT 25")
    for i, row in enumerate(cursor.fetchall(), 1):
        print(f"  {i:>2}. {row[0]}")

    cursor.execute("SELECT COUNT(*) FROM diseases")
    diseases = cursor.fetchone()[0]
    print(f"\nDiseases in DB: {diseases}")
    print(f"Symptoms in DB: {total}")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("=" * 60)
    print("WHO ICD-11 SYMPTOM COLLECTOR — FIXED VERSION")
    print("=" * 60)

    print("""
STRATEGIES:
  1. Extract from existing diseases DB (ICD Chapter 21 codes + keywords)
  2. Mine all disease definitions for symptom phrases
  3. Insert curated master symptom list (~300 symptoms)
  4. API crawl of ICD-11 MMS Chapter 21 (requires internet)

Press Ctrl+C at any time to stop safely.
All progress is saved to SQLite as it runs.
""")

    conn = connect_database()

    # -------------------------------------------------------
    # Load disease name cache (used to avoid re-inserting diseases)
    # -------------------------------------------------------
    print("Loading disease name cache...")
    _load_disease_cache(conn)
    print(f"  Cached {len(_DISEASE_NAME_CACHE)} disease names for filtering.")

    # -------------------------------------------------------
    # Setup / migrate table schema
    # -------------------------------------------------------
    print("\nSetting up symptoms table...")
    setup_symptoms_table(conn)

    # -------------------------------------------------------
    # Clean up wrong data from old crawler
    # -------------------------------------------------------
    print("\nCleaning up incorrect entries from old crawler...")
    clear_wrong_symptoms(conn)

    # -------------------------------------------------------
    # Run strategies
    # -------------------------------------------------------
    try:
        strategy1_from_diseases_db(conn)
    except KeyboardInterrupt:
        print("\nStopped after Strategy 1.")
        show_summary(conn)
        export_csv(conn)
        conn.close()
        return

    try:
        strategy2_mine_definitions(conn)
    except KeyboardInterrupt:
        print("\nStopped after Strategy 2.")
        show_summary(conn)
        export_csv(conn)
        conn.close()
        return

    try:
        strategy3_curated_list(conn)
    except KeyboardInterrupt:
        print("\nStopped after Strategy 3.")
        show_summary(conn)
        export_csv(conn)
        conn.close()
        return

    try:
        strategy4_api_crawl(conn)
    except KeyboardInterrupt:
        print("\nStopped during Strategy 4.")
    except Exception as e:
        print(f"\nStrategy 4 error: {e}")
        print("Continuing with data already collected.")

    # -------------------------------------------------------
    # Final output
    # -------------------------------------------------------
    show_summary(conn)
    export_csv(conn)

    conn.close()
    print("\nDatabase connection closed. All done!")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()