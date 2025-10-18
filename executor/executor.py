import sys
import os
import json
import requests
from bs4 import BeautifulSoup

def main():
    try:
        # 1. Get the untrusted code and URL from environment variables
        scraper_code = os.environ.get("SCRAPER_CODE")
        target_url = os.environ.get("TARGET_URL")

        if not scraper_code or not target_url:
            print(json.dumps({"error": "Missing code or URL"}), file=sys.stderr)
            sys.exit(1)
            
        # 2. Make libraries available for the exec() call
        # The code inside exec() needs access to 'requests' and 'BeautifulSoup'
        local_scope = {
            "requests": requests,
            "BeautifulSoup": BeautifulSoup
        }
        
        # 3. Execute the LLM-generated code in a controlled scope
        # This defines the 'extract_hackathons' function within local_scope
        exec(scraper_code, {"__builtins__": {}}, local_scope)

        # 4. Check if the function was defined
        if 'extract_hackathons' not in local_scope:
            print(json.dumps({"error": "Function 'extract_hackathons' not defined"}), file=sys.stderr)
            sys.exit(1)
            
        # 5. Run the extracted function
        extractor_func = local_scope['extract_hackathons']
        results = extractor_func(target_url)
        
        # 6. Print the results as a JSON string to stdout
        # The agent will capture this output
        print(json.dumps(results))

    except Exception as e:
        # If anything fails, print the error to stderr
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()