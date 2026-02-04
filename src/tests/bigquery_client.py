from google.cloud import bigquery
import pandas as pd
from datetime import datetime


def get_bq_client(project_id: str) -> bigquery.Client:
    return bigquery.Client(project=project_id)


def load_companies(
    df: pd.DataFrame,
    project_id: str,
    dataset: str,
    table: str,
) -> None:
    """
    Load companies DataFrame into BigQuery (append).
    """
    client = get_bq_client(project_id)

    table_id = f"{project_id}.{dataset}.{table}"

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
        schema=[
            bigquery.SchemaField("symbol", "STRING"),
            bigquery.SchemaField("source", "STRING"),
            bigquery.SchemaField("ingest_ts", "TIMESTAMP"),
        ],
    )

    job = client.load_table_from_dataframe(
        df,
        table_id,
        job_config=job_config,
    )

    job.result()
