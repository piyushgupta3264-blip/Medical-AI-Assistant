import sqlite3
import re

DB_FILE = "icd11_complete.db"
CSV_FILE = "icd11_symptoms.csv"

conn = sqlite3.connect(DB_FILE)
c = conn.cursor()

# -------------------------------------------------------
# 1. Current counts
# -------------------------------------------------------
c.execute("SELECT COUNT(*) FROM symptoms")
before = c.fetchone()[0]
print(f"Symptoms before cleanup: {before}")

# -------------------------------------------------------
# 2. Remove entries whose normalized name exactly matches
#    a disease name (catches anything that slipped through)
# -------------------------------------------------------
c.execute("""
    DELETE FROM symptoms
    WHERE id IN (
        SELECT s.id FROM symptoms s
        INNER JOIN diseases d
            ON LOWER(TRIM(s.symptom_name)) = LOWER(TRIM(d.disease_name))
    )
""")
conn.commit()
c.execute("SELECT COUNT(*) FROM symptoms")
after1 = c.fetchone()[0]
print(f"After removing exact disease name matches: {after1} (removed {before - after1})")

# -------------------------------------------------------
# 3. Remove clearly non-symptom entries:
#    - Entries containing pathogen/organism names
#      (e.g., "Vancomycin resistant Enterococcus")
#    - Entries containing "syndrome" + over 50 chars
#      (these are almost always disease names)
#    - Pure lab/diagnostic result entries
# -------------------------------------------------------
bad_patterns = [
    # Pathogen resistance patterns (lab results, not symptoms)
    r"resistant\s+\w+",
    r"positive\s+antigen",
    r"specific antigen",
    r"serogroup",
    r"serotype",
    # These are procedures/diagnoses, not symptoms
    r"^autopsy",
    r"mention of autopsy",
    r"stenosis of neural canal",
    r"unspecified\s+\w+\s+death",
]

removed_patterns = 0


# Use LIKE-based cleanup instead (more reliable in SQLite)
noise_terms = [
    "%resistant %coccus%",
    "%resistant %pylori%",
    "% resistant %",
    "%mention of autopsy%",
    "%antigen positive%",
    "%antigen negative%",
    "% serogroup %",
    "% serotype %",
    "%gene positive%",
    "%pcr positive%",
    "%antibody positive%",
    "%antibody negative%",
    "% positive culture%",
]

for term in noise_terms:
    c.execute(
        "DELETE FROM symptoms WHERE LOWER(symptom_name) LIKE ?",
        (term,)
    )
    removed_patterns += c.rowcount

conn.commit()
c.execute("SELECT COUNT(*) FROM symptoms")
after2 = c.fetchone()[0]
print(f"After removing lab/pathogen noise: {after2} (removed {after1 - after2})")

# -------------------------------------------------------
# 4. Show breakdown by source
# -------------------------------------------------------
print("\nFinal breakdown by source:")
c.execute("""
    SELECT source, COUNT(*) as cnt
    FROM symptoms
    GROUP BY
        CASE
            WHEN source LIKE 'Extracted%' THEN 'Extracted from disease definitions'
            ELSE source
        END
    ORDER BY cnt DESC
    LIMIT 10
""")
for row in c.fetchall():
    print(f"  {row[1]:>5}  |  {row[0]}")

# -------------------------------------------------------
# 5. Show 30 random sample entries
# -------------------------------------------------------
print("\n30 random symptoms (verify quality):")
c.execute("SELECT symptom_name, source FROM symptoms ORDER BY RANDOM() LIMIT 30")
for i, row in enumerate(c.fetchall(), 1):
    src = row[1]
    if "Extracted" in src:
        src = "Definition mining"
    elif "Curated" in src:
        src = "Curated list"
    elif "Chapter 21" in src:
        src = "ICD-11 Ch.21"
    print(f"  {i:>2}. {row[0]}  [{src}]")

# -------------------------------------------------------
# 6. Final counts
# -------------------------------------------------------
c.execute("SELECT COUNT(*) FROM symptoms")
final = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM diseases")
diseases = c.fetchone()[0]

print(f"\n{'='*50}")
print(f"  Diseases  : {diseases}")
print(f"  Symptoms  : {final}")
print(f"  Improvement: {final}x more than original 77")
print(f"{'='*50}")

# -------------------------------------------------------
# 7. Re-export CSV
# -------------------------------------------------------
import csv
c.execute("""
    SELECT id, symptom_name, normalized_name, definition,
           synonyms, uri, icd_code, source, body_system, release
    FROM symptoms ORDER BY symptom_name
""")
rows = c.fetchall()
cols = [d[0] for d in c.description]
with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(cols)
    writer.writerows(rows)
print(f"\nCSV re-exported: {CSV_FILE}  ({len(rows)} rows)")

conn.close()
