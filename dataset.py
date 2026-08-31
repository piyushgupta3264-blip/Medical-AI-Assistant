import requests
import sqlite3
import time
import csv

# ============================================================
# WHO CREDENTIALS
# ============================================================

CLIENT_ID = "5ea0256b-98c5-48d6-a3de-09fc6fdafaaa_9c5f7d90-674a-43fc-918a-e82444d2341e"
CLIENT_SECRET = "yHFKFA7wkiXLrqGKDB9B57UU0xkUxTHPFzF2CtIVA38="


# ============================================================
# CONFIG
# ============================================================

RELEASE = "2025-01"
LINEARIZATION = "mms"

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"

BASE_URL = (
    f"https://id.who.int/icd/release/11/"
    f"{RELEASE}/{LINEARIZATION}"
)

DB_FILE = "icd11_complete.db"
CSV_FILE = "icd11_complete.csv"

REQUEST_DELAY = 0.1


# ============================================================
# GLOBAL TOKEN
# ============================================================

ACCESS_TOKEN = None


# ============================================================
# GET ACCESS TOKEN
# ============================================================

def get_access_token():

    global ACCESS_TOKEN

    print("\nGetting new WHO access token...")

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "icdapi_access"
    }

    headers = {
        "Content-Type":
        "application/x-www-form-urlencoded"
    }

    response = requests.post(
        TOKEN_URL,
        data=data,
        headers=headers,
        timeout=30
    )

    print(
        "Authentication status:",
        response.status_code
    )

    if response.status_code != 200:

        print(
            "WHO authentication error:"
        )

        print(response.text)

        response.raise_for_status()

    ACCESS_TOKEN = response.json()["access_token"]

    print(
        "New access token received."
    )

    return ACCESS_TOKEN


# ============================================================
# API HEADERS
# ============================================================

def get_headers():

    global ACCESS_TOKEN

    return {
        "Authorization":
        f"Bearer {ACCESS_TOKEN}",

        "Accept":
        "application/json",

        "Accept-Language":
        "en",

        "API-Version":
        "v2"
    }


# ============================================================
# REQUEST WITH AUTOMATIC TOKEN REFRESH
# ============================================================

def get_request(url):

    global ACCESS_TOKEN

    for attempt in range(3):

        try:

            response = requests.get(
                url,
                headers=get_headers(),
                timeout=60
            )

            # -----------------------------------------
            # SUCCESS
            # -----------------------------------------

            if response.status_code == 200:

                return response.json()


            # -----------------------------------------
            # TOKEN EXPIRED
            # -----------------------------------------

            if response.status_code == 401:

                print(
                    "\nAccess token expired."
                )

                print(
                    "Getting new token..."
                )

                get_access_token()

                continue


            # -----------------------------------------
            # RATE LIMIT
            # -----------------------------------------

            if response.status_code == 429:

                print(
                    "Rate limit reached."
                )

                print(
                    "Waiting 10 seconds..."
                )

                time.sleep(10)

                continue


            # -----------------------------------------
            # OTHER ERROR
            # -----------------------------------------

            print(
                "HTTP error:",
                response.status_code
            )

            print(
                "URL:",
                url
            )

            return None


        except requests.exceptions.RequestException as e:

            print(
                "Network error:",
                e
            )

            time.sleep(3)


    return None


# ============================================================
# DATABASE
# ============================================================

def connect_database():

    conn = sqlite3.connect(
        DB_FILE
    )

    return conn


# ============================================================
# CHECK IF RECORD ALREADY EXISTS
# ============================================================

def already_downloaded(
    conn,
    uri
):

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM diseases
        WHERE uri = ?
        LIMIT 1
        """,
        (uri,)
    )

    return cursor.fetchone() is not None


# ============================================================
# JSON-LD HELPERS
# ============================================================

def clean_text(value):

    if value is None:
        return ""

    if isinstance(value, dict):

        if "@value" in value:
            value = value["@value"]

        elif "value" in value:
            value = value["value"]

    return str(value).strip()


def get_list(value):

    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def extract_uris(value):

    result = []

    for item in get_list(value):

        if isinstance(item, str):

            result.append(item)

        elif isinstance(item, dict):

            uri = item.get("@id")

            if uri:
                result.append(uri)

    return result


def extract_children(data):

    return extract_uris(
        data.get("child", [])
    )


# ============================================================
# EXTRACT ENTITY
# ============================================================

def extract_entity(data):

    uri = data.get(
        "@id",
        ""
    )

    title = clean_text(
        data.get(
            "title",
            ""
        )
    )

    code = clean_text(
        data.get(
            "code",
            ""
        )
    )

    definition = clean_text(
        data.get(
            "definition",
            ""
        )
    )

    parents = extract_uris(
        data.get(
            "parent",
            []
        )
    )

    children = extract_children(
        data
    )

    synonyms = extract_uris(
        data.get(
            "synonym",
            []
        )
    )

    return {

        "uri":
        uri,

        "icd_code":
        code,

        "disease_name":
        title,

        "definition":
        definition,

        "synonyms":
        " | ".join(synonyms),

        "parent":
        " | ".join(parents),

        "children":
        " | ".join(children),

        "release":
        RELEASE,

        "classification":
        "ICD-11 MMS",

        "source":
        "WHO ICD-11 API"
    }


# ============================================================
# SAVE ENTITY
# ============================================================

def save_record(
    conn,
    record
):

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO diseases
        (
            uri,
            icd_code,
            disease_name,
            definition,
            synonyms,
            parent,
            children,
            release,
            classification,
            source
        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,

        (

            record["uri"],

            record["icd_code"],

            record["disease_name"],

            record["definition"],

            record["synonyms"],

            record["parent"],

            record["children"],

            record["release"],

            record["classification"],

            record["source"]
        )
    )

    conn.commit()


# ============================================================
# GET ALREADY SAVED RECORD COUNT
# ============================================================

def get_database_count(conn):

    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM diseases"
    )

    return cursor.fetchone()[0]


# ============================================================
# RESUME CRAWLING
# ============================================================

def resume_crawl(conn):

    print(
        "\nChecking existing database..."
    )

    existing = get_database_count(
        conn
    )

    print(
        "Existing records:",
        existing
    )

    # -----------------------------------------
    # Get fresh token
    # -----------------------------------------

    get_access_token()

    # -----------------------------------------
    # Get root
    # -----------------------------------------

    print(
        "\nGetting ICD-11 MMS root..."
    )

    root = get_request(
        BASE_URL
    )

    if not root:

        print(
            "Could not retrieve root."
        )

        return


    # -----------------------------------------
    # Start from root
    # -----------------------------------------

    queue = []

    children = extract_children(
        root
    )

    queue.extend(
        children
    )

    visited = set()

    new_records = 0

    skipped = 0

    failed = 0


    print(
        "Starting/resuming crawler..."
    )


    # ========================================================
    # MAIN LOOP
    # ========================================================

    while queue:

        uri = queue.pop(0)

        uri = uri.replace(
            "http://id.who.int",
            "https://id.who.int"
        )


        # -----------------------------------------
        # Prevent duplicate URI in current run
        # -----------------------------------------

        if uri in visited:

            continue

        visited.add(
            uri
        )


        # -----------------------------------------
        # IMPORTANT:
        # We still request existing entities
        # because we need their children to continue
        # through the hierarchy.
        # -----------------------------------------

        data = get_request(
            uri
        )


        if not data:

            failed += 1

            continue


        # -----------------------------------------
        # Find children
        # -----------------------------------------

        children = extract_children(
            data
        )


        for child in children:

            child = child.replace(
                "http://id.who.int",
                "https://id.who.int"
            )

            if child not in visited:

                queue.append(
                    child
                )


        # -----------------------------------------
        # CHECK DATABASE
        # -----------------------------------------

        if already_downloaded(
            conn,
            uri
        ):

            skipped += 1

            if skipped % 100 == 0:

                print(
                    "Already saved:",
                    skipped,
                    "| Queue:",
                    len(queue)
                )

            continue


        # -----------------------------------------
        # SAVE NEW RECORD
        # -----------------------------------------

        record = extract_entity(
            data
        )


        if record:

            save_record(
                conn,
                record
            )

            new_records += 1


            if new_records % 50 == 0:

                total = get_database_count(
                    conn
                )

                print(
                    "New records:",
                    new_records,
                    "| Total database:",
                    total,
                    "| Queue:",
                    len(queue)
                )


        time.sleep(
            REQUEST_DELAY
        )


    # ========================================================
    # FINISHED
    # ========================================================

    print()
    print(
        "=" * 60
    )

    print(
        "RESUME PROCESS FINISHED"
    )

    print(
        "New records:",
        new_records
    )

    print(
        "Already existed:",
        skipped
    )

    print(
        "Failed:",
        failed
    )

    print(
        "Total database records:",
        get_database_count(conn)
    )

    print(
        "=" * 60
    )


# ============================================================
# EXPORT DATABASE TO CSV
# ============================================================

def export_csv(conn):

    print(
        "\nExporting database to CSV..."
    )

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM diseases"
    )

    rows = cursor.fetchall()

    columns = [
        column[0]
        for column in cursor.description
    ]

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(
            file
        )

        writer.writerow(
            columns
        )

        writer.writerows(
            rows
        )

    print(
        "CSV saved:",
        CSV_FILE
    )

    print(
        "Rows:",
        len(rows)
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "WHO ICD-11 RESUME DOWNLOADER"
    )

    print(
        "=" * 60
    )

    print(
        "\nExisting database will NOT be deleted."
    )

    print(
        "Existing records will be skipped."
    )

    print(
        "Expired tokens will automatically refresh."
    )


    # -----------------------------------------
    # Connect existing database
    # -----------------------------------------

    conn = connect_database()


    # -----------------------------------------
    # Resume
    # -----------------------------------------

    resume_crawl(
        conn
    )


    # -----------------------------------------
    # Export final CSV
    # -----------------------------------------

    export_csv(
        conn
    )


    conn.close()


    print(
        "\nDone."
    )


if __name__ == "__main__":

    main()