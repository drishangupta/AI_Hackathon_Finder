"""
Simple script to check OpenSearch data
"""

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

def check_opensearch_data():
    # Setup OpenSearch client
    session = boto3.Session()
    credentials = session.get_credentials()
    region = 'us-east-1'
    
    auth = AWS4Auth(credentials.access_key, credentials.secret_key, region, 'aoss', session_token=credentials.token)
    
    client = OpenSearch(
        hosts=[{'host': '5puu3iyv3d1lz41d7yp4.us-east-1.aoss.amazonaws.com', 'port': 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30
    )
    
    try:
        # Get all data from user-preferences index
        response = client.search(
            index='user-preferences',
            body={
                "query": {"match_all": {}},
                "size": 100
            }
        )
        
        print(f"📊 Total documents: {response['hits']['total']['value']}")
        print("\n📋 Stored data:")
        
        for hit in response['hits']['hits']:
            data = hit['_source']
            print(f"  User: {data.get('user_id')}")
            print(f"  Preferences: {data.get('preference_text')}")
            print(f"  Vector length: {len(data.get('preference_vector', []))}")
            print("  ---")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_opensearch_data()
