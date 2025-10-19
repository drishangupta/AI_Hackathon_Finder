import os
import boto3
import json
import argparse
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from dotenv import load_dotenv

# --- CONFIGURATION ---
# Load environment variables from a .env file
load_dotenv()
REGION = os.environ.get("AWS_REGION", "ap-south-1")
OPENSEARCH_ENDPOINT = os.environ.get("OPENSEARCH_ENDPOINT")

# --- SETUP ---
# Ensure endpoint is configured
if not OPENSEARCH_ENDPOINT:
    print("❌ ERROR: OPENSEARCH_ENDPOINT is not set in your .env file.")
    print("   Please create a .env file and add the endpoint for your collection.")
    exit(1)

# Function to initialize the OpenSearch client
def get_opensearch_client():
    """Initializes and returns an OpenSearch client with AWS IAM authentication."""
    credentials = boto3.Session().get_credentials()
    aws_auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        REGION,
        'aoss', # Service name for OpenSearch Serverless
        session_token=credentials.token
    )

    client = OpenSearch(
        hosts=[{'host': OPENSEARCH_ENDPOINT, 'port': 443}],
        http_auth=aws_auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        pool_maxsize=20
    )
    return client

# --- TOOL FUNCTIONS ---
def list_indices(client):
    """Lists all indices in the collection."""
    print("🔍 Fetching indices in the collection...")
    try:
        indices = client.cat.indices(format="json")
        if not indices:
            print("  -> No indices found.")
            return
        print("✅ Found Indices:")
        for index in indices:
            print(f"  - Name: {index['index']}, Status: {index['status']}, Docs: {index['docs.count']}")
    except Exception as e:
        print(f"❌ ERROR fetching indices: {e}")

def get_mapping(client, index_name):
    """Gets the mapping (schema) for a specific index."""
    print(f"🔍 Fetching mapping for index '{index_name}'...")
    try:
        mapping = client.indices.get_mapping(index=index_name)
        print("✅ Index Mapping:")
        print(json.dumps(mapping, indent=2))
    except Exception as e:
        print(f"❌ ERROR fetching mapping for '{index_name}': {e}")

def scan_documents(client, index_name):
    """Scans and prints documents from a specific index."""
    print(f"🔍 Scanning documents in index '{index_name}'...")
    try:
        response = client.search(
            index=index_name,
            body={
                "size": 100, # Get up to 100 documents
                "query": {
                    "match_all": {}
                }
            }
        )
        hits = response['hits']['hits']
        if not hits:
            print("  -> No documents found.")
            return
        
        print(f"✅ Found {len(hits)} documents:")
        for i, hit in enumerate(hits):
            print("-" * 20)
            print(f"Document #{i+1} (ID: {hit['_id']})")
            print(json.dumps(hit['_source'], indent=2))
            print("-" * 20)

    except Exception as e:
        print(f"❌ ERROR scanning documents in '{index_name}': {e}")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect an Amazon OpenSearch Serverless collection.")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Sub-command to list indices
    parser_list = subparsers.add_parser('list', help='List all indices in the collection.')

    # Sub-command to get mapping
    parser_map = subparsers.add_parser('mapping', help='Get the mapping for a specific index.')
    parser_map.add_argument('index', type=str, help='The name of the index to inspect.')

    # Sub-command to scan documents
    parser_scan = subparsers.add_parser('scan', help='Scan documents within a specific index.')
    parser_scan.add_argument('index', type=str, help='The name of the index to scan.')

    args = parser.parse_args()
    
    os_client = get_opensearch_client()

    if args.command == 'list':
        list_indices(os_client)
    elif args.command == 'mapping':
        get_mapping(os_client, args.index)
    elif args.command == 'scan':
        scan_documents(os_client, args.index)
