import dashscope
from dashscope import Generation
import os

# 自动读取环境变量（最安全）
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

if not dashscope.api_key:
    print("❌ 未检测到API Key！请先完成步骤3")
else:
    print("✅ Key已读取，正在测试调用...")

response = Generation.call(
    model="qwen-max",  # 或 qwen-plus（更便宜）
    messages=[{"role": "user", "content": "你好，请用一句话介绍自己"}],
    result_format='message'
)

print("\n🎉 调用成功！Qwen回复：")
print(response.output.choices[0].message.content)