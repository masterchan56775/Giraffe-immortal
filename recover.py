import subprocess
import os
import re

repo = r'd:\program\py\Giraffe-immortal'
res = subprocess.run(['git', 'show', 'eb4211e:README.md'], cwd=repo, capture_output=True, text=True, encoding='utf-8')
content = res.stdout

new_auth = """### 2. 配置认证（双引擎架构）

编辑 `~/.giraffe/config.json` 进行配置。系统支持双引擎认证机制，可自动根据配置决定底层调用方式：

**方式 A — Google Cloud ADC 认证（推荐用于 Vertex AI）：**

```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "project": "YOUR_PROJECT_ID",
      "location": "global"
    }
  }
}
```

在使用前，请确保您已通过 gcloud CLI 完成本地 ADC 认证：`gcloud auth application-default login`。系统会自动获取 ADC 凭据，无需在配置文件或 `.env` 中写入任何 API Key。

**方式 B — 兼容 OpenAI 协议的 API Key 认证：**

```json
{
  "router": {
    "primary_model": {
      "provider": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-your-key"
    }
  }
}
```
当系统检测到配置中包含有效的 `api_key` 时，会自动回退为基于 urllib 的标准 HTTP REST 调用。"""

# find the section to replace
pattern = r'### 2\. 配置 API Key.*?系统会自动获取 ADC 凭据，无需在配置文件或 `\.env` 中写入任何 API Key。'
content = re.sub(pattern, new_auth, content, flags=re.DOTALL)

with open(r'd:\program\py\2\README_zh.md', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated README_zh.md")
