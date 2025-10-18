from scout_agent import scout_agent

# Test the Scout Agent
print("Testing Scout Agent with hackathon discovery...")

test_queries = [
    "Find me AI and machine learning hackathons",
    "What hackathons are happening on DevPost?",
    "I'm interested in blockchain hackathons, can you help?"
]

for query in test_queries:
    print(f"\n🔍 Query: {query}")
    try:
        response = scout_agent(query)
        print(f"📝 Response: {response}")
    except Exception as e:
        print(f"❌ Error: {e}")
    print("-" * 50)