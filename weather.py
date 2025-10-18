from strands import Agent
from strands_tools import http_request,file_read,file_write
from strands.agent.conversation_manager import SlidingWindowConversationManager

# Create a conversation manager with custom window size
conversation_manager = SlidingWindowConversationManager(
    window_size=20,  # Maximum number of messages to keep
    should_truncate_results=True, # Enable truncating the tool result when a message is too large for the model's context window 
)
tools = [http_request,file_read,file_write]
agent = Agent(tools=tools,conversation_manager=conversation_manager)


result = agent("""What are some upcoming hackathons on devpost website? I asked this prompt before, and 
               you found an api endpoint on their website, share that with me too and how you found it""")
while True:
    user_query = input(">> ")
    if user_query == "exit":
        break
    result = agent(user_query)
# print(result)
