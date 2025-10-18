"""
Minimal Strands SDK mock for local testing
"""

def tool(func):
    """Decorator to mark functions as agent tools"""
    func._is_tool = True
    return func


class Agent:
    """Base agent class"""
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
