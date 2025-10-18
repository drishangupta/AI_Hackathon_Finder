"""
Interactive chat interface for testing Scout Agent
"""

import boto3
import json
from scout_agent import ScoutAgent


class ChatInterface:
    def __init__(self):
        self.scout = ScoutAgent()
        self.bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        
    def chat_with_bedrock(self, message: str) -> str:
        """Direct chat with Claude for general conversation"""
        response = self.bedrock.invoke_model(
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": message}],
                "max_tokens": 1000
            })
        )
        
        result = json.loads(response['body'].read())
        return result['content'][0]['text']
    
    def process_command(self, user_input: str):
        """Process user commands and route to appropriate function"""
        if user_input.startswith('/discover'):
            preferences = user_input.replace('/discover', '').strip()
            if not preferences:
                preferences = "general hackathons"
            
            print(f"🔍 Discovering hackathons for: {preferences}")
            try:
                result = self.scout.discover_hackathons(preferences)
                print(f"📊 Found {result['count']} hackathons")
                for hackathon in result['hackathons'][:3]:  # Show first 3
                    print(f"  • {hackathon.get('title', 'Unknown')}")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        elif user_input.startswith('/preferences'):
            user_id = "New User"
            preferences = user_input.replace('/preferences', '').strip()
            
            print(f"💾 Storing preferences: {preferences}")
            try:
                result = self.scout.store_user_preferences(user_id, preferences)
                print(f"✅ Preferences stored for user: {result['user_id']}")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        
        # elif user_input.startswith('/embeddings'):
        #     response = self.scout._generate_embedding("my preferences are of AWS Cloud and AI with all the related fields")
        #     print(response)
        
        elif user_input.startswith('/setup'):
            print("🔧 Setting up OpenSearch index...")
            try:
                result = self.scout.setup_opensearch_index()
                print(f"✅ Index setup: {result}")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        elif user_input.startswith('/chat'):
            message = user_input.replace('/chat', '').strip()
            print("🤖 Claude says:")
            try:
                response = self.chat_with_bedrock(message)
                print(response)
            except Exception as e:
                print(f"❌ Error: {e}")
        
        else:
            print("Available commands:")
            print("  /setup - Setup OpenSearch index")
            print("  /discover [preferences] - Discover hackathons")
            print("  /preferences [text] - Store user preferences")
            print("  /chat [message] - Chat with Claude")
            print("  /quit - Exit")
    
    def run(self):
        """Main chat loop"""
        print("🚀 Hackathon Hunter Scout Agent Chat Interface")
        print("Type /help for commands or /quit to exit\n")
        
        while True:
            try:
                user_input = input("You: ").strip()
                
                if user_input.lower() in ['/quit', 'quit', 'exit']:
                    print("👋 Goodbye!")
                    break
                
                if user_input.lower() in ['/help', 'help']:
                    self.process_command("")
                    continue
                
                if user_input:
                    self.process_command(user_input)
                
                print()  # Empty line for readability
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    chat = ChatInterface()
    chat.run()
