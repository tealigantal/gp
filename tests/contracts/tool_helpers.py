import json

def respond(text):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "final", "type": "function", "function": {"name": "respond", "arguments": json.dumps({"kind": "information", "text": text, "references": []}, ensure_ascii=False)}}]}
