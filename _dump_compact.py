import json, sys
sys.path.append('src')
from gp_assistant.recommend.runner import run as r
from gp_assistant.recommend.compact_payload import compact_recommend_payload as c
out=r(mode='service')
print('-- raw --')
print(json.dumps(out, ensure_ascii=False, indent=2))
print('-- compact --')
print(json.dumps(c(out), ensure_ascii=False, indent=2))
