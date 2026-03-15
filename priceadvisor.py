import os
import glob
import pandas as pd
import dashscope
from dashscope import Generation

# ============== 配置区（核心优化：相对路径+低成本模型） ==============
# 大模型API密钥（优先环境变量，也可直接填写）
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY") or "你的API密钥"

# 核心修改：相对路径配置（适配上传/跨环境）
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CLEAN_DATA_FOLDER = os.path.join(CURRENT_DIR, "data", "clean_data")
CLEAN_DATA_FOLDER = os.getenv("CLEAN_DATA_FOLDER") or DEFAULT_CLEAN_DATA_FOLDER

# 查询缓存（避免重复调用AI，省Token）
QUERY_CACHE = {}

# ============== 核心函数1：读取文件夹下所有CSV并合并 ==============
def load_all_csv_from_folder(folder_path: str):
    """
    读取指定文件夹下所有CSV，合并为DataFrame（跳过损坏文件）
    """
    if not os.path.exists(folder_path):
        return f"❌ 文件夹不存在：{folder_path}"
    
    # 只读取.csv文件
    csv_files = glob.glob(os.path.join(folder_path, "*.csv"))
    if len(csv_files) == 0:
        return f"❌ 文件夹 {folder_path} 无CSV文件"
    
    all_df = []
    for csv_file in csv_files:
        try:
            # 兼容中文编码
            df = pd.read_csv(csv_file, encoding='utf-8-sig')
            all_df.append(df)
        except Exception as e:
            print(f"⚠️ 跳过损坏文件 {os.path.basename(csv_file)}：{str(e)[:20]}")
            continue
    
    if len(all_df) == 0:
        return "❌ 无可用CSV数据"
    
    # 合并所有数据，重置索引
    merged_df = pd.concat(all_df, ignore_index=True)
    return merged_df

# ============== 核心函数2：生成价格建议（省Token版） ==============
def get_price_suggestion(query: str, data_source: str = None):
    """
    生成价格建议（带缓存+精简Prompt+限制数据量）
    :param query: 搜索关键词
    :param data_source: 数据来源（文件夹/单个CSV）
    :return: 精简的AI分析报告
    """
    # 1. 优先查缓存（避免重复调用AI）
    if query in QUERY_CACHE:
        print(f"✅ 命中缓存，节省Token！")
        return QUERY_CACHE[query]
    
    # 2. 确定数据来源（默认用clean_data文件夹）
    data_source = data_source or CLEAN_DATA_FOLDER
    
    # 3. 读取数据（区分文件夹/文件）
    df = load_all_csv_from_folder(data_source) if os.path.isdir(data_source) else None
    if isinstance(df, str):  # 读取失败返回的是错误字符串
        return df
    if df is None or len(df) == 0:
        return "❌ 未加载到有效数据"
    
    # 4. 过滤数据（限制最多50条，减少Token消耗）
    filtered = df[df['标题'].str.contains(query, case=False, na=False)].head(50)
    if len(filtered) < 1:
        return f"⚠️ 无{query}相关数据"
    
    # 5. 计算核心统计（只保留关键指标，精简Prompt）
    prices = pd.to_numeric(filtered['价格'], errors='coerce').dropna()
    if len(prices) == 0:
        return "❌ 无有效价格数据"
    
    stats = {
        "count": len(prices),
        "avg": round(prices.mean(), 1),
        "median": round(prices.median(), 1),
        "min": round(prices.min(), 1),
        "max": round(prices.max(), 1),
    }
    
    # 6. 精简Prompt（核心优化：砍掉冗余内容，限制输出长度）
    prompt = f"""角色：闲鱼二手商品定价专家。
需求：基于以下数据，给{query}的定价建议（严格控制在200字内）。
核心数据：
- 有效样本：{stats['count']}条
- 均价：{stats['avg']}元，中位数：{stats['median']}元
- 价格区间：{stats['min']}-{stats['max']}元

要求：
1. 推荐合理出售价格区间（精确到百元）
2. 1句核心定价建议
语气简洁、专业、实用。"""
    
    # 7. 调用低成本模型（核心优化：qwen-plus+限制输出Token）
    try:
        response = Generation.call(
            model="qwen-plus",          # 替换为低成本模型（比max省60%+Token）
            messages=[{"role": "user", "content": prompt}],
            result_format='message',
            temperature=0.7,
            max_tokens=300              # 限制输出长度，避免冗余消耗
        )
        report = response.output.choices[0].message.content
        
        # 8. 存入缓存（下次查询直接用）
        QUERY_CACHE[query] = report
        return report
    
    except Exception as e:
        error_msg = f"❌ AI调用失败：{str(e)[:30]}（检查API密钥/网络）"
        QUERY_CACHE[query] = error_msg  # 缓存错误结果，避免重复报错
        return error_msg

# ============== 核心函数3：适配Web端调用 ==============
def analyze_for_web(keyword: str, clean_folder: str = None):
    """Web端专用调用函数"""
    data_source = clean_folder or CLEAN_DATA_FOLDER
    return get_price_suggestion(query=keyword, data_source=data_source)

# ============== 本地交互（单独运行时） ==============
if __name__ == "__main__":
    print(f"🎯 闲鱼定价助手（省Token版）")
    print(f"数据文件夹：{CLEAN_DATA_FOLDER}")  # 打印实际使用的路径，方便调试
    print("输入关键词（如iPhone15）或exit退出\n")
    
    while True:
        user_query = input("👤 你的查询：").strip()
        if user_query.lower() in ["exit", "quit", "退出"]:
            print("👋 再见！")
            break
        if not user_query:
            continue
        
        print("🤖 分析中...")
        result = get_price_suggestion(user_query)
        print("\n" + "="*50)
        print(result)
        print("="*50 + "\n")