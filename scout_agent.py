"""
Scout Agent - Discovery & Analysis Core
Handles tool generation, user interaction, and hackathon discovery
"""

import docker
import boto3
import json
from typing import Dict, List, Optional
from strands import Agent, tool
from docker.errors import ContainerError, ImageNotFound
from botocore.exceptions import ClientError # For other boto errors


class ScoutAgent(Agent):
    def __init__(self):
        super().__init__(
            name="HackathonScout",
            description="Discovers hackathons by generating custom tools and analyzing websites"
        )
            # In __init__
        self.bedrock_runtime = boto3.client('bedrock-runtime') # For invoke_model (Claude, Titan)
        self.bedrock_agent_runtime = boto3.client('bedrock-agent-runtime') # For retrieve (KB)
        self.dynamodb = boto3.resource('dynamodb')
        self.opensearch = boto3.client('opensearchserverless')
        try:
            self.docker_client = docker.from_env()
        except Exception as e:
            print(f"Warning: Docker client not found. Execution will fail. Error: {e}")
            self.docker_client = None
        
    @tool
    def discover_hackathons(self, user_preferences: str) -> Dict:
        """Main discovery workflow: query knowledge base → generate tools → extract data"""
        # Step 1: Query Bedrock Knowledge Base for trusted URLs
        trusted_urls = self._get_trusted_hackathon_sites()
        
        # Step 2: For each URL, generate appropriate extraction tool
        results = []
        for url in trusted_urls:
            tool_result = self._generate_extraction_tool(url)
            if tool_result:
                hackathon_data = self._execute_extraction_tool(url, tool_result)
                results.extend(hackathon_data)
        
        return {"hackathons": results, "count": len(results)}
    
    @tool
    def store_user_preferences(self, user_id: str, preferences: str) -> Dict:
        """Store user preferences as vectors in OpenSearch"""
        # Generate embedding using Titan
        embedding = self._generate_embedding(preferences)
        
        # Store in OpenSearch
        self.opensearch.index(
            index='user-preferences',
            body={
                'user_id': user_id,
                'preference_text': preferences,
                'preference_vector': embedding
            }
        )
        return {"status": "stored", "user_id": user_id}
    
    def _get_trusted_hackathon_sites(self) -> List[str]:
        """Query Bedrock Knowledge Base for trusted hackathon URLs"""
        try:
            response = self.bedrock_agent_runtime.retrieve(
            knowledgeBaseId="your-kb-id",
            retrievalQuery={
                'text': 'hackathon websites trusted sources'
            }
            # You can add retrievalConfiguration here if needed
            )
            
            urls = [
            doc['content']['text'] for doc in response.get('retrievalResults', [])
            # Or use 'location' if you are storing URLs in S3 metadata
            # urls = [doc['location']['s3Location']['uri'] for doc in response.get('retrievalResults', [])]
                    ]
            return urls if urls else ["https://devpost.com", "https://hackerearth.com"]
        
        except Exception as e:
            # Catch specific exceptions (e.g., botocore.exceptions.ClientError)
            print(f"Error querying Knowledge Base: {e}") 
            # Fallback for local testing or errors
            return ["https://devpost.com", "https://hackerearth.com"]
    
    def _generate_extraction_tool(self, url: str) -> Optional[Dict]:
        """Core WOW factor: Generate API discovery or scraper code"""
        # Check if we already have a tool for this URL
        scrapers_table = self.dynamodb.Table('ScraperFunctions')
        existing = scrapers_table.get_item(Key={'source_url': url})
        
        if 'Item' in existing:
            return existing['Item']
        
        # Generate new tool using Claude 4.5 Sonnet
        prompt = f"""
        Analyze this website: {url}
        
        First, try to find hidden JSON APIs by examining the source code.
        If APIs found, return extraction code using requests.
        If no APIs, generate a BeautifulSoup scraper.
        
        Return *only* the executable Python code as a function named 'extract_hackathons'.
        The function must take 'url' as an argument, e.g., 'def extract_hackathons(url):'.
        Your code *must* import its own dependencies (e.g., requests, BeautifulSoup).
        """
        
        response = self.bedrock_runtime.invoke_model(
            modelId='anthropic.claude-sonnet-4-5-20250929-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000
            })
        )
        
        result = json.loads(response['body'].read())
        scraper_code = result['content'][0]['text']
        
        # Store generated tool
        tool_data = {
            'source_url': url,
            'scraper_code': scraper_code,
            'function_type': 'api' if 'requests.get' in scraper_code and 'json' in scraper_code else 'scraper'
        }
        
        scrapers_table.put_item(Item=tool_data)
        return tool_data
    
    def _execute_extraction_tool(self, url: str, tool_data: Dict) -> List[Dict]:
        """Execute the generated extraction tool"""
        # Execute the generated code safely in a docker container
        try:
            # 1. Run the container
            container = self.docker_client.containers.run(
                image="scout-executor:latest",  # The image we built
                environment={
                    "SCRAPER_CODE": tool_data['scraper_code'],
                    "TARGET_URL": url
                },
                
                # --- SECURITY & RESOURCE LIMITS ---
                remove=True,        # Automatically remove container on exit
                detach=False,       # Run in foreground and wait for completion
                network_mode="bridge", # Isolates from host network
                mem_limit="256m",   # Max 256MB of RAM
                cpu_period=100000,  # CPU limiting (100ms)
                cpu_quota=50000,    # 50% CPU max
                read_only=True      # Read-only filesystem
            )
            
            # 2. 'container' holds the stdout logs (as bytes)
            #    because detach=False blocks until completion
            stdout = container.decode('utf-8')
            
            # 3. Parse the JSON output from the container's stdout
            return json.loads(stdout)

        except ImageNotFound:
            print("Error: 'scout-executor:latest' image not found. Please build it.")
            return [{"error": "Executor image not found"}]
        except ContainerError as e:
            # This catches errors *from inside* the container (e.g., non-zero exit code)
            print(f"Container failed for {url}:\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
            return [{"error": f"Container failed: {e.stderr.decode('utf-8')}"}]
        except json.JSONDecodeError as e:
            print(f"Failed to decode container output for {url}. Output: {stdout}")
            return [{"error": f"JSON decode error: {e}"}]
        except Exception as e:
            print(f"An unexpected error occurred during Docker execution: {e}")
            return [{"error": f"Docker execution failed: {str(e)}"}]
    
    def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding using Amazon Titan"""
        response = self.bedrock_runtime.invoke_model(
            modelId='amazon.titan-embed-text-v2:0',
            body=json.dumps({"inputText": text})
        )
        return json.loads(response['body'].read())['embedding']
