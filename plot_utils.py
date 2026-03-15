# plot_utils.py - 完整修复版
import os
import base64
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
from io import BytesIO
from matplotlib.ticker import MaxNLocator

def generate_price_chart(clean_file_path: str, keyword: str = "商品") -> dict:
    try:
        # 1. 中文字体配置
        plt.style.use('seaborn-v0_8-whitegrid')
        font_paths = [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc"
        ]
        available_fonts = [path for path in font_paths if os.path.exists(path)]
        if not available_fonts:
            return {"code": 500, "msg": "系统未找到可用中文字体", "image": ""}
        
        chinese_font = fm.FontProperties(fname=available_fonts[0])
        plt.rcParams.update({
            'font.family': chinese_font.get_name(),
            'axes.unicode_minus': False,
            'figure.facecolor': 'white',
            'axes.facecolor': 'white'
        })

        # 2. 读取数据（核心修复：强制使用清洗好的数字列）
        if not os.path.exists(clean_file_path):
            return {"code": 400, "msg": "清洗后数据文件不存在！", "image": ""}
        
        df_clean = pd.read_csv(clean_file_path, encoding='utf-8-sig')
        
        # 强制使用app.py已经清洗好的“价格（数字）”列，不再二次解析
        if '价格（数字）' not in df_clean.columns:
            return {"code": 400, "msg": "数据文件缺少清洗后的价格列，请重新爬取！", "image": ""}
        
        # 过滤有效价格
        prices = df_clean['价格（数字）'].dropna()
        prices = prices[prices >= 1]  # 过滤低于1元的无效值
        prices_array = prices.values
        
        if len(prices_array) < 3:
            return {"code": 400, "msg": f"有效价格数据仅{len(prices_array)}条，无法生成图表！", "image": ""}

        # 3. 绘制图表
        fig, ax = plt.subplots(figsize=(10, 6))
        df_plot = pd.DataFrame({'价格(元)': prices_array})
        sns.histplot(data=df_plot, x='价格(元)', bins=20, kde=True, color='#4e79a7', ax=ax)
        
        # Y轴强制整数刻度
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=1))
        ax.set_ylim(bottom=0)
        
        # 图表标注
        ax.set_title(f"{keyword} 价格分布图", fontproperties=chinese_font, fontsize=16, pad=15)
        ax.set_xlabel("价格（元）", fontproperties=chinese_font, fontsize=12, labelpad=10)
        ax.set_ylabel("商品数量", fontproperties=chinese_font, fontsize=12, labelpad=10)
        
        # 标注均价和中位数
        avg_price = prices.mean()
        median_price = prices.median()
        ax.axvline(avg_price, color='red', linestyle='--', linewidth=2, label=f'均价: {avg_price:.0f}元')
        ax.axvline(median_price, color='orange', linestyle=':', linewidth=2, label=f'中位数: {median_price:.0f}元')
        ax.legend(prop=chinese_font, fontsize=11)

        # 4. 转换为base64
        buf = BytesIO()
        plt.savefig(
            buf, 
            format='png', 
            bbox_inches='tight', 
            dpi=150,
            facecolor='white',
            edgecolor='none'
        )
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        return {
            "code": 200,
            "msg": "图表生成成功",
            "image": f"data:image/png;base64,{img_base64}"
        }
    except Exception as e:
        import traceback
        error_msg = f"图表生成失败：{str(e)[:200]}"
        print(f"绘图模块报错：{traceback.format_exc()}")
        return {"code": 500, "msg": error_msg, "image": ""}

# 测试代码
if __name__ == "__main__":
    test_file = r"替换为你的清洗后CSV路径"
    result = generate_price_chart(test_file, "测试商品")
    print(f"测试结果：{result['code']} - {result['msg']}")