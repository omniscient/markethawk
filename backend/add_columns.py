import logging
import os
import time
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load env vars
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.error("DATABASE_URL not found!")
    exit(1)

def run_migration():
    logger.info("Starting schema migration...")
    engine = create_engine(DATABASE_URL)
    
    # Columns to add and their types
    new_columns = [
        ("description", "TEXT"),
        ("primary_exchange", "VARCHAR"),
        ("list_date", "VARCHAR"),
        ("total_employees", "FLOAT"),
        ("share_class_shares_outstanding", "FLOAT"),
        ("weighted_shares_outstanding", "FLOAT"),
        ("sic_code", "VARCHAR"),
        ("sic_description", "VARCHAR"),
        ("homepage_url", "VARCHAR"),
        ("last_details_update", "TIMESTAMP WITHOUT TIME ZONE")
    ]
    
    with engine.connect() as connection:
        for col_name, col_type in new_columns:
            try:
                # Check if column exists
                check_sql = text(f"SELECT column_name FROM information_schema.columns WHERE table_name='ticker_references' AND column_name='{col_name}'")
                result = connection.execute(check_sql).fetchone()
                
                if not result:
                    logger.info(f"Adding column {col_name}...")
                    alter_sql = text(f"ALTER TABLE ticker_references ADD COLUMN {col_name} {col_type}")
                    connection.execute(alter_sql)
                    connection.commit()
                else:
                    logger.info(f"Column {col_name} already exists. Skipping.")
                    
            except Exception as e:
                logger.error(f"Error adding column {col_name}: {e}")
                
    logger.info("Migration complete!")

if __name__ == "__main__":
    run_migration()
