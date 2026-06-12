import os
import re
import subprocess
import sys
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
import pre_start
from app.core.config import settings

def import_sql_seeds():
    seed_dir = "/app/db_seed"
    if not os.path.exists(seed_dir):
        print(f"Directory {seed_dir} does not exist. Skipping SQL seed import.")
        return

    # Connect directly to the target database
    driver = "ODBC Driver 17 for SQL Server"
    odbc_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE={settings.DB_NAME};"
        f"TrustServerCertificate=yes;"
    )
    if settings.DB_TRUSTED_CONNECTION.lower() == "yes":
        odbc_str += "Trusted_Connection=yes;"
    else:
        odbc_str += f"UID={settings.DB_USER};PWD={settings.DB_PASSWORD};"
        
    db_url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc_str)
    
    sql_files = [f for f in os.listdir(seed_dir) if f.endswith(".sql")]
    if not sql_files:
        print("No SQL seed files found in db_seed directory.")
        return
        
    print(f"Found {len(sql_files)} SQL seed file(s) to import: {sql_files}")
    
    try:
        engine = create_engine(db_url)
        with engine.connect() as connection:
            for sql_file in sorted(sql_files):
                file_path = os.path.join(seed_dir, sql_file)
                print(f"Importing seed file: {sql_file}...")
                
                content = ""
                for encoding in ["utf-8", "utf-16", "latin-1"]:
                    try:
                        with open(file_path, "r", encoding=encoding) as f:
                            content = f.read()
                        break
                    except UnicodeDecodeError:
                        continue
                
                if not content:
                    print(f"Could not read file {sql_file} with supported encodings. Skipping.")
                    continue
                
                # Split content into individual lines
                lines = content.splitlines()
                statements = []
                for line in lines:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    if line_str.upper() == "GO":
                        continue
                    if line_str.startswith("--"):
                        continue
                    statements.append(line_str)
                
                print(f"Executing {len(statements)} statements from {sql_file} line-by-line...")
                
                success_count = 0
                ignored_pk_count = 0
                failed_count = 0
                
                for idx, stmt in enumerate(statements):
                    try:
                        with connection.begin():
                            connection.execute(text(stmt))
                        success_count += 1
                    except Exception as stmt_err:
                        err_msg = str(stmt_err)
                        # Check for primary key / duplicate key violations (error code 2627 or similar)
                        if "2627" in err_msg or "23000" in err_msg or "Cannot insert duplicate key" in err_msg:
                            ignored_pk_count += 1
                        else:
                            failed_count += 1
                            print(f"[Warning] Statement {idx+1} failed: {stmt[:120]}")
                            print(f"  Error: {err_msg[:200]}")
                
                print(f"Finished executing {sql_file}. Stats: Success: {success_count}, Ignored Duplicates: {ignored_pk_count}, Failures: {failed_count}")
                
                # Rename the file to .sql.imported so it doesn't run again on next boot
                imported_path = file_path + ".imported"
                try:
                    os.rename(file_path, imported_path)
                    print(f"Renamed {sql_file} to {sql_file}.imported")
                except Exception as rename_err:
                    print(f"Could not rename {sql_file}: {rename_err}")
                    
    except Exception as e:
        print(f"Error importing SQL seeds: {e}")

def main():
    # 1. Run database initialization check & creation
    pre_start.main()
    
    # 2. Run database migrations
    print("Running database migrations via Alembic...")
    result = subprocess.run(["alembic", "upgrade", "head"])
    if result.returncode != 0:
        print("Database migrations failed! Exiting startup.")
        sys.exit(result.returncode)
    print("Database migrations completed successfully.")
    
    # 3. Import any custom SQL seeds if provided
    import_sql_seeds()
    
    # 4. Start the FastAPI server using Uvicorn
    print("Starting FastAPI application...")
    subprocess.run(["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"])

if __name__ == "__main__":
    main()
