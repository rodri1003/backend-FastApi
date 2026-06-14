import os
import re
import subprocess
import sys
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
import pre_start
from app.core.config import settings

def split_sql_values(vals_str):
    tokens = []
    current = []
    in_quotes = False
    quote_char = None
    nest_level = 0
    
    i = 0
    while i < len(vals_str):
        char = vals_str[i]
        
        if in_quotes:
            current.append(char)
            if char == "'" and quote_char == "'":
                if i + 1 < len(vals_str) and vals_str[i+1] == "'":
                    current.append("'")
                    i += 1
                else:
                    in_quotes = False
                    quote_char = None
        else:
            if char in ("'", '"'):
                in_quotes = True
                quote_char = char
                current.append(char)
            elif char == "(":
                nest_level += 1
                current.append(char)
            elif char == ")":
                nest_level -= 1
                current.append(char)
            elif char == "," and nest_level == 0:
                tokens.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        i += 1
        
    if current:
        tokens.append("".join(current).strip())
        
    return tokens

def clean_val(val):
    val = val.strip()
    if val.upper() == "NULL":
        return None
    if val.startswith("N'") and val.endswith("'"):
        return val[2:-1].replace("''", "'")
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1].replace("''", "'")
    if val.upper().startswith("CAST(") and val.endswith(")"):
        inner_match = re.search(r"CAST\s*\((.*?)\s+AS\s+", val, re.IGNORECASE)
        if inner_match:
            return clean_val(inner_match.group(1))
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val

def parse_insert(stmt):
    match = re.match(
        r"INSERT\s+(?:INTO\s+)?\[dbo\]\.\[(\w+)\]\s*\((.*?)\)\s*VALUES\s*\((.*)\)",
        stmt,
        re.IGNORECASE
    )
    if not match:
        return None
    table = match.group(1)
    cols_raw = match.group(2)
    vals_raw = match.group(3)
    
    cols = [c.replace("[", "").replace("]", "").strip() for c in cols_raw.split(",")]
    vals = split_sql_values(vals_raw)
    return table, cols, vals

def row_exists(connection, table, cols, vals):
    if table == "alembic_version":
        ver = clean_val(vals[0])
        res = connection.execute(
            text("SELECT 1 FROM [alembic_version] WHERE version_num = :ver"),
            {"ver": ver}
        ).first()
        return res is not None
        
    elif table == "room_amenities":
        room_idx = cols.index("room_id")
        amenity_idx = cols.index("amenity_id")
        r_id = clean_val(vals[room_idx])
        a_id = clean_val(vals[amenity_idx])
        res = connection.execute(
            text("SELECT 1 FROM [room_amenities] WHERE room_id = :r_id AND amenity_id = :a_id"),
            {"r_id": r_id, "a_id": a_id}
        ).first()
        return res is not None
        
    elif table == "user_roles":
        user_idx = cols.index("user_id")
        role_idx = cols.index("role_id")
        u_id = clean_val(vals[user_idx])
        r_id = clean_val(vals[role_idx])
        res = connection.execute(
            text("SELECT 1 FROM [user_roles] WHERE user_id = :u_id AND role_id = :r_id"),
            {"u_id": u_id, "r_id": r_id}
        ).first()
        return res is not None
        
    elif table == "casbin_rule":
        ptype_idx = cols.index("ptype") if "ptype" in cols else -1
        v0_idx = cols.index("v0") if "v0" in cols else -1
        v1_idx = cols.index("v1") if "v1" in cols else -1
        v2_idx = cols.index("v2") if "v2" in cols else -1
        v3_idx = cols.index("v3") if "v3" in cols else -1
        v4_idx = cols.index("v4") if "v4" in cols else -1
        v5_idx = cols.index("v5") if "v5" in cols else -1

        ptype = clean_val(vals[ptype_idx]) if ptype_idx != -1 else None
        v0 = clean_val(vals[v0_idx]) if v0_idx != -1 else None
        v1 = clean_val(vals[v1_idx]) if v1_idx != -1 else None
        v2 = clean_val(vals[v2_idx]) if v2_idx != -1 else None
        v3 = clean_val(vals[v3_idx]) if v3_idx != -1 else None
        v4 = clean_val(vals[v4_idx]) if v4_idx != -1 else None
        v5 = clean_val(vals[v5_idx]) if v5_idx != -1 else None

        query_parts = []
        params = {}
        for col, val in [("ptype", ptype), ("v0", v0), ("v1", v1), ("v2", v2), ("v3", v3), ("v4", v4), ("v5", v5)]:
            if col in cols:
                if val is None:
                    query_parts.append(f"[{col}] IS NULL")
                else:
                    query_parts.append(f"[{col}] = :{col}")
                    params[col] = val

        query_str = "SELECT 1 FROM [casbin_rule] WHERE " + " AND ".join(query_parts)
        res = connection.execute(text(query_str), params).first()
        return res is not None

    else:
        if "id" in cols:
            id_idx = cols.index("id")
            row_id = clean_val(vals[id_idx])
            res = connection.execute(
                text(f"SELECT 1 FROM [{table}] WHERE id = :row_id"),
                {"row_id": row_id}
            ).first()
            return res is not None
    return False

def import_sql_seeds():
    seed_dir = "/app/db_seed" if os.path.exists("/app/db_seed") else "./db_seed"
    if not os.path.exists(seed_dir):
        print(f"Directory {seed_dir} does not exist. Skipping SQL seed import.")
        return

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
        
    print(f"Found {len(sql_files)} SQL seed file(s) to check/import: {sql_files}")
    
    try:
        engine = create_engine(db_url)
        for sql_file in sorted(sql_files):
            file_path = os.path.join(seed_dir, sql_file)
            print(f"Analyzing and synchronizing seed file: {sql_file}...")
            
            content = ""
            for encoding in ["utf-8", "utf-16", "latin-1"]:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                print(f"Could not read file {sql_file}. Skipping.")
                continue
            
            lines = content.splitlines()
            statements = []
            for line in lines:
                line_str = line.strip()
                if not line_str or line_str.upper() == "GO" or line_str.startswith("--"):
                    continue
                if line_str.upper().startswith("INSERT"):
                    statements.append(line_str)
            
            print(f"Parsed {len(statements)} INSERT statements from {sql_file}.")
            
            success_count = 0
            existing_count = 0
            failed_count = 0
            
            for idx, stmt in enumerate(statements):
                parsed = parse_insert(stmt)
                if not parsed:
                    continue
                table, cols, vals = parsed
                
                try:
                    # Usar una conexion fresca por cada statement para evitar conflictos y corrupcion de transacciones
                    with engine.connect() as conn:
                        with conn.begin():
                            # Comprobar si el registro ya existe
                            if row_exists(conn, table, cols, vals):
                                existing_count += 1
                                continue
                                
                            # Si no existe, insertar
                            use_identity = False
                            if "id" in cols and table not in ("alembic_version", "room_amenities", "user_roles"):
                                use_identity = True
                                
                            if use_identity:
                                conn.execute(text(f"SET IDENTITY_INSERT [dbo].[{table}] ON"))
                            conn.execute(text(stmt))
                            if use_identity:
                                conn.execute(text(f"SET IDENTITY_INSERT [dbo].[{table}] OFF"))
                                
                            success_count += 1
                            
                except Exception as stmt_err:
                    failed_count += 1
                    print(f"[Warning] Statement {idx+1} failed: {stmt[:120]}")
                    print(f"  Error: {str(stmt_err)[:200]}")
            
            print(f"Finished sync for {sql_file}. Stats: Inserted: {success_count}, Already Exists: {existing_count}, Failures: {failed_count}")
            
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
