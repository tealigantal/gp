import json
import types

import gp_assistant.chat.deepseek_agent as dsa
from gp_assistant.chat import session_store as store

class MockLLM:
    def __init__(self):
        self.calls = []
        self.phase = 0
    def available(self):
        return True, 'ok'
    def run_chat_with_tools(self, messages, tools=None, temperature=0.2, model=None, tool_choice=None):
        self.calls.append((len(messages), tool_choice, [t['function']['name'] for t in tools] if tools else []))
        # Step1: return only get_session_context
        if tool_choice == 'required' and tools and tools[0]['function']['name'] in ('chat','get_session_context'):
            return {
                'role':'assistant',
                'content': None,
                'tool_calls':[{'id':'tc1','type':'function','function':{'name':'get_session_context','arguments': json.dumps({'session_id':'default_session'}) }}]
            }
        # Step2: first round -> ensure_recommendation with null args
        if tool_choice == 'required' and tools and tools[0]['function']['name'] == 'chat':
            # we are not in step1 tools, so this must be step2 (full tools). Use a counter to simulate two attempts
            if self.phase == 0:
                self.phase = 1
                return {
                    'role':'assistant',
                    'content': None,
                    'tool_calls':[{'id':'tc2','type':'function','function':{'name':'ensure_recommendation','arguments': None }}]
                }
            else:
                # Second attempt with proper args
                return {
                    'role':'assistant',
                    'content': None,
                    'tool_calls':[{'id':'tc3','type':'function','function':{'name':'ensure_recommendation','arguments': json.dumps({'session_id':'default_session','topk':3,'refresh': True}) }}]
                }
        # Final no-tools call
        return {'role':'assistant','content':'OK','tool_calls':[]}

# Patch
orig = dsa.LLMClient
try:
    dsa.LLMClient = MockLLM  # type: ignore
    out = dsa.run_agent_turn(None, '强制刷新候选，用最新的数据 topk=3')
    print(json.dumps({'reply': out.get('reply'), 'right_panel': out.get('right_panel')}, ensure_ascii=False))
finally:
    dsa.LLMClient = orig  # restore
