import json
import re

# 从 GPT 输出中提取 JSON
def extract_json(text):
    m = re.search(r"(\{[\s\S]*\})", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except:
        return None