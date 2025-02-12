import sqlite3
from pinecone import Pinecone
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Pinecone Configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = "healthassistant"

pc = Pinecone(api_key=PINECONE_API_KEY, environment="us-east-1-aws")
pinecone_index = pc.Index(INDEX_NAME)

def query_sqlite(db_file):
    """
    Query and print all data from the SQLite database.
    """
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    if not tables:
        print("No tables found in the database.")
    else:
        for table in tables:
            table_name = table[0]
            print(f"Querying table: {table_name}")
            try:
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns_info = cursor.fetchall()
                columns = [col[1] for col in columns_info]
                print("Columns:", columns)
                for row in rows:
                    print(row)
            except Exception as e:
                print(f"Failed to query table {table_name}. Error: {e}")
            print("-" * 40)
    cursor.close()
    conn.close()

def query_pinecone():
    """
    Query and print all namespaces in Pinecone.
    """
    try:
        stats = pinecone_index.describe_index_stats()
        if "namespaces" in stats and stats["namespaces"]:
            print("Pinecone Namespaces:")
            for namespace in stats["namespaces"].keys():
                print(f"- {namespace}")
        else:
            print("No namespaces found in Pinecone.")
    except Exception as e:
        print(f"Failed to query Pinecone. Error: {e}")

def remove_user(username, db_file):
    """
    Remove user data from both SQLite and Pinecone.
    """
    try:
        # Delete from SQLite
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        cursor.close()
        conn.close()
        print(f"Removed {username} from SQLite.")
    except Exception as e:
        print(f"Failed to remove {username} from SQLite. Error: {e}")
    
    try:
        # Delete namespace from Pinecone
        pinecone_index.delete(delete_all=True, namespace=username)
        print(f"Removed namespace {username} from Pinecone.")
    except Exception as e:
        print(f"Failed to remove {username} from Pinecone. Error: {e}")

def main():
    db_file = "users.db"
    while True:
        print("\nLLM Health Assistant Database Management System")
        print("1. query - Query SQLite and Pinecone")
        print("2. remove - Remove user from SQLite and Pinecone")
        print("3. exit - Exit the program")
        choice = input("Enter your choice: ").strip().lower()
        
        if choice == "query":
            print("\nQuerying SQLite Database...")
            query_sqlite(db_file)
            print("\nQuerying Pinecone...")
            query_pinecone()
        elif choice == "remove":
            username = input("Enter username to remove (or '1' to return): ").strip()
            if username == "1":
                continue
            remove_user(username, db_file)
        elif choice == "exit":
            print("Exiting program...")
            break
        else:
            print("Invalid choice. Please enter 'query', 'remove', or 'exit'.")

if __name__ == "__main__":
    main()
