import json
from reasoning_agent import AGENT_TOOLS

def convert_to_ollama_tools(tools_dict):
    ollama_tools = []
    for name, info in tools_dict.items():
        tool = {
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": info["params"]
                }
            }
        }
        for param in info["params"]:
            tool["function"]["parameters"]["properties"][param] = {
                "type": "string",
                "description": f"Parameter {param}"
            }
        ollama_tools.append(tool)
    return ollama_tools

if __name__ == "__main__":
    tools = convert_to_ollama_tools(AGENT_TOOLS)
    print(json.dumps(tools[:2], indent=2))
