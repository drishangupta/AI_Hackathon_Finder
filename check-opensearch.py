import boto3
import requests
from requests_aws4auth import AWS4Auth
import json

region = "ap-south-1"  # change as needed
service = "aoss"

credentials = boto3.Session().get_credentials()
auth = AWS4Auth(
    credentials.access_key,
    credentials.secret_key,
    region,
    service,
    session_token=credentials.token
)

# Your collection endpoint
endpoint = "https://abc3bpsm0ywxlu29o1yh.ap-south-1.aoss.amazonaws.com"
index_name = "user_preferences"

# Fetch some documents
query = {
    "size": 10,
    "query": {
        "match_all": {}
    }
}

response = requests.post(
    f"{endpoint}/{index_name}/_search",
    auth=auth,
    headers={"Content-Type": "application/json"},
    data=json.dumps(query)
)

print(json.dumps(response.json(), indent=2))