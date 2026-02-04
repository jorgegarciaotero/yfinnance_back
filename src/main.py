from google.cloud import bigquery


def test_connection() -> None:
    """
    Minimal connectivity check.
    """
    client = bigquery.Client()
    rows = client.query("SELECT 1 AS ok").result()
    for r in rows:
        print(r.ok)


def main():
   test_connection()


if __name__ == "__main__":
    main()
