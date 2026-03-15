# 导入所有必要依赖
import matplotlib
matplotlib.use('Agg')  
import matplotlib.pyplot as plt
import seaborn as sns
from flask import Flask, render_template, request, jsonify, send_file
from flask.json.provider import DefaultJSONProvider  # 新增：适配新版Flask JSON序列化
from flask_cors import CORS
# app.py 中新增导入
from plot_utils import generate_price_chart  # 导入独立绘图模块
import os
import sys
import time
import glob
import re
import numpy as np  # 新增：处理numpy类型和价格清洗
import pandas as pd
import urllib.parse  # 处理中文文件名下载
from io import BytesIO
import base64

# ========== 导入自定义模块 ==========
import goofishclaw  # 爬虫模块
import priceadvisor  # AI分析模块（省Token版）

# ========== 初始化Flask应用 ==========
app = Flask(__name__)
CORS(app)
app.config['JSON_AS_ASCII'] = False  # 强制显示中文，避免乱码
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制请求大小（16MB）

# ========== 路径配置 ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_FOLDER = os.path.join(BASE_DIR, 'data', 'raw_data')
CLEAN_DATA_FOLDER = os.path.join(BASE_DIR, 'data', 'clean_data')
os.makedirs(RAW_DATA_FOLDER, exist_ok=True)
os.makedirs(CLEAN_DATA_FOLDER, exist_ok=True)

# ========== 全局变量 ==========
latest_result = {
    "raw_file": "",    # 原始数据文件路径
    "clean_file": "",  # 清洗后数据文件路径
    "stats": {},       # 真实价格统计
    "keyword": ""      # 搜索关键词
}

# ========== 新增：价格清洗工具函数（适配闲鱼非标准价格格式） ==========

# ========== 替换app.py中原有的extract_valid_price函数 ==========
def extract_valid_price(price_str):
    """
    带调试打印的价格清洗函数，专门排查单条数据无效原因
    """
    # 打印原始输入，方便排查
    print(f"[调试] 收到价格输入：{repr(price_str)}")
    
    # 1. 空值/无效值过滤
    if pd.isna(price_str):
        print(f"[调试] 被过滤：空值")
        return None
    price_str = str(price_str).strip()
    
    invalid_keywords = ["无价格", "", "0", "免费", "面议", "私聊", "订金", "定金"]
    if price_str in invalid_keywords:
        print(f"[调试] 被过滤：属于无效关键词列表")
        return None

    # 2. 彻底清理干扰符号，只保留「数字、小数点、万」
    price_clean = re.sub(r'[^\d\.万]', '', price_str)
    print(f"[调试] 清理干扰符号后：{repr(price_clean)}")
    
    # 3. 处理万单位
    multiplier = 1
    if "万" in price_clean:
        multiplier = 10000
        price_clean = price_clean.replace("万", "").strip()
        print(f"[调试] 识别到万单位，乘以10000，清理后：{repr(price_clean)}")
    
    # 4. 校验纯数字格式
    number_match = re.match(r'^\d+\.?\d*$', price_clean)
    if not number_match:
        print(f"[调试] 被过滤：不是有效的纯数字格式")
        return None
    
    # 5. 计算最终价格
    try:
        price_num = float(number_match.group()) * multiplier
        print(f"[调试] 最终价格计算：{price_num} 元")
        # 过滤低于1元的无效脏数据
        if price_num < 1:
            print(f"[调试] 被过滤：价格低于1元")
            return None
        return price_num
    except Exception as e:
        print(f"[调试] 被过滤：计算异常 - {str(e)}")
        return None

# ========== 新增：自定义JSON提供器（解决numpy类型序列化问题） ==========
class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        # 处理numpy整数类型
        if isinstance(obj, np.integer):
            return int(obj)
        # 处理numpy浮点类型
        if isinstance(obj, np.floating):
            return float(obj)
        # 处理numpy数组
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        # 其他类型交给父类处理
        return super().default(obj)

# 注册自定义JSON提供器（适配所有Flask版本）
app.json_provider_class = CustomJSONProvider

# ========== 首页路由 ==========
@app.route('/')
def index():
    """渲染前端主页面（templates/index.html）"""
    return render_template('index.html')

# ========== API：爬取闲鱼数据 + 自动清洗 + 计算真实统计 ==========
@app.route('/api/crawl', methods=['POST'])
def api_crawl():
    try:
        # 1. 接收前端参数
        request_data = request.get_json()
        keyword = request_data.get('keyword', '').strip()
        max_pages = int(request_data.get('max_pages', 3))

        # 2. 参数校验
        if not keyword:
            return jsonify({"code": 400, "msg": "请输入搜索关键词！"})
        if max_pages < 1 or max_pages > 10:
            return jsonify({"code": 400, "msg": "爬取页数需在1-10之间！"})

        # 3. 生成唯一文件名（避免重复）
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        raw_filename = f'闲鱼_{keyword}_{timestamp}.csv'
        save_filename = os.path.join(RAW_DATA_FOLDER, raw_filename)

        # 4. 调用爬虫函数
        all_data = goofishclaw.crawl_xianyu(
            keyword=keyword,
            max_pages=max_pages,
            save_filename=save_filename
        )

        # 5. 校验爬虫结果
        if not os.path.exists(save_filename) or len(all_data) == 0:
            return jsonify({"code": 400, "msg": "爬虫未爬取到有效数据！"})

        
        # 6. 数据清洗
        df_raw = pd.read_csv(save_filename, encoding='utf-8-sig')

        # 【调试】打印去重前的数据量
        print(f"\n===== 去重前：原始数据共 {len(df_raw)} 条 =====")

        # 核心去重逻辑：默认 keep='first'，保留第一条出现的，删除后面重复的
        # 注意：这行代码绝对不会把所有重复的都删掉，一定会保留第一条！
        df_clean = df_raw.drop_duplicates(subset=['标题'], keep='first').copy()

        # 【调试】打印去重后的数据量，以及被删除的重复数据
        print(f"===== 去重后：保留 {len(df_clean)} 条（删除了 {len(df_raw)-len(df_clean)} 条重复数据） =====")

        # 【调试】如果有重复数据，打印出来让你看
        if len(df_raw) != len(df_clean):
            # 找出所有重复的标题（不包含第一次出现的）
            duplicated_titles = df_raw[df_raw.duplicated(subset=['标题'], keep='first')]['标题'].tolist()
            print(f"===== 被删除的重复标题（共 {len(duplicated_titles)} 条）： =====")
            for title in duplicated_titles:
                print(f"  - {title}")
            print("===== 注意：以上重复标题的第一条已被保留！ =====")
        print("============================\n")
        # 替换原有价格转数字逻辑，使用自定义清洗函数
        # ========== 替换api_crawl接口里的价格清洗代码块 ==========
        # 替换原有这一行：df_clean['价格（数字）'] = df_clean['价格'].apply(extract_valid_price)

        # 价格清洗核心逻辑
        # 替换原有价格清洗代码
        df_clean['价格（数字）'] = df_clean['价格'].apply(extract_valid_price)
        print("\n===== 清洗后价格详情 =====")
        print(df_clean[['标题', '价格', '价格（数字）']])
        print("============================\n")

        # 【关键调试】控制台打印清洗前后对比，确认万→元转换正确
        print("\n" + "="*80)
        print("📊 价格清洗结果（万→元 转换详情）")
        print("-"*80)
        for idx, row in df_clean.iterrows():
            print(f"原始价格：{row['价格']:<8} → 转换后：{row['价格（数字）']:.0f} 元 | 标题：{row['标题'][:30]}")
        print("="*80 + "\n")

        # 原有过滤逻辑不变（仅保留有效价格）
        df_clean = df_clean[df_clean['价格（数字）'].notna() & (df_clean['价格（数字）'] > 0)].reset_index(drop=True)
        # 过滤无效价格（仅保留>0的有效数据）
        df_clean = df_clean[df_clean['价格（数字）'].notna() & (df_clean['价格（数字）'] > 0)].reset_index(drop=True)

        # 7. 保存清洗后文件（修复replace多次匹配的问题）
        clean_filename = f"清洗_{raw_filename}"
        clean_file_path = os.path.join(CLEAN_DATA_FOLDER, clean_filename)
        df_clean.to_csv(clean_file_path, index=False, encoding='utf-8-sig')

        # 8. 计算真实统计值（确保返回Python原生类型，非numpy类型）
        real_stats = {}
        if len(df_clean) > 0:
            prices = df_clean['价格（数字）'].tolist()  # 转为Python列表
            real_stats = {
                "有效数据量": len(prices),  # Python int
                "平均价": round(sum(prices)/len(prices), 1),  # Python float
                "中位数": round(np.median(prices), 1),  # 即使是numpy值，JSON提供器会转换
                "最低有效价": round(min(prices), 1),  # Python float
                "最高有效价": round(max(prices), 1)   # Python float
            }
        else:
            real_stats = {
                "有效数据量": 0,
                "平均价": 0.0,
                "中位数": 0.0,
                "最低有效价": 0.0,
                "最高有效价": 0.0
            }

        # 9. 更新全局变量
        latest_result["raw_file"] = save_filename
        latest_result["clean_file"] = clean_file_path
        latest_result["stats"] = real_stats
        latest_result["keyword"] = keyword

        # 10. 返回结果（此时所有数值都是Python原生类型，可正常序列化）
        return jsonify({
            "code": 200,
            "msg": f"爬取&清洗完成！共{len(all_data)}条原始数据，{len(df_clean)}条有效数据",
            "stats": real_stats,
            "raw_file": save_filename,
            "clean_file": clean_file_path
        })

    except Exception as e:
        error_msg = f"爬取失败：{str(e)[:50]}（请检查爬虫模块/网络）"
        print(f"爬取接口异常详情：{str(e)}")  # 控制台打印完整错误，方便排查
        return jsonify({"code": 500, "msg": error_msg})

# ========== API：AI价格分析 ==========
@app.route('/api/ai_analyze', methods=['POST'])
def api_ai_analyze():
    try:
        # 1. 校验是否已爬取数据
        if not latest_result["keyword"] or not os.path.exists(CLEAN_DATA_FOLDER):
            return jsonify({"code": 400, "msg": "请先完成商品爬取，再生成AI分析报告！"})

        # 2. 检查清洗后数据
        csv_files = glob.glob(os.path.join(CLEAN_DATA_FOLDER, "*.csv"))
        if len(csv_files) == 0 or not latest_result["clean_file"]:
            return jsonify({"code": 400, "msg": "清洗后数据为空，请更换关键词重新爬取！"})

        # 3. 调用priceadvisor的分析函数
        report = priceadvisor.analyze_for_web(
            keyword=latest_result["keyword"],
            clean_folder=CLEAN_DATA_FOLDER
        )

        # 4. 返回AI分析结果
        return jsonify({
            "code": 200,
            "msg": "AI分析完成（省Token版）",
            "report": report
        })

    except Exception as e:
        error_msg = f"AI分析失败：{str(e)[:50]}（请检查priceadvisor模块/API密钥）"
        print(f"AI分析异常详情：{str(e)}")
        return jsonify({"code": 500, "msg": error_msg})

# ========== API：下载数据文件 ==========
@app.route('/api/download/<file_type>')
def api_download(file_type):
    try:
        # 1. 确定下载文件路径
        if file_type == "raw":
            file_path = latest_result["raw_file"]
        elif file_type == "clean":
            file_path = latest_result["clean_file"]
        else:
            return jsonify({"code": 400, "msg": "文件类型错误！仅支持raw/clean"})

        # 2. 校验文件是否存在
        if not file_path or not os.path.exists(file_path):
            return jsonify({"code": 404, "msg": "文件不存在！请先爬取数据"})

        # 3. 处理中文文件名（兼容所有浏览器）
        filename = os.path.basename(file_path)
        # 修复：直接使用原始文件名，Flask 2.0+支持中文下载名
        filename = urllib.parse.unquote(filename)

        # 4. 返回文件下载响应（指定utf-8-sig编码，避免Excel打开乱码）
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='text/csv; charset=utf-8-sig'
        )

    except Exception as e:
        error_msg = f"下载失败：{str(e)[:50]}"
        print(f"下载接口异常详情：{str(e)}")
        return jsonify({"code": 500, "msg": error_msg})
    


# ================================================
# 【简化版】价格可视化 API（调用独立模块）
# ================================================
@app.route('/api/visualize', methods=['GET'])
def api_visualize():
    try:
        print("=== /api/visualize 被调用（模块化版本） ===")   
        
        # 从全局变量获取清洗后文件路径和关键词
        clean_file = latest_result.get("clean_file", "")
        keyword = latest_result.get("keyword", "商品")
        
        # 调用独立绘图模块
        plot_result = generate_price_chart(clean_file, keyword)
        
        # 直接返回绘图模块的结果
        return jsonify({
            "code": plot_result["code"],
            "msg": plot_result["msg"],
            "image": plot_result["image"]
        })

    except Exception as e:
        import traceback
        print("可视化API报错：", traceback.format_exc())
        return jsonify({"code": 500, "msg": f"API调用失败：{str(e)[:200]}", "image": ""})

# ========== 启动服务 ==========
if __name__ == '__main__':
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        threaded=True
    )