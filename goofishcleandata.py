import time
import random
import csv
import re
import statistics
from urllib.parse import quote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --------------------- 配置 ---------------------
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
}

# ========== 工具函数（完全不变） ==========
def extract_price_num(price_str):
    price_match = re.search(r'(\d+\.?\d*)', price_str)
    if price_match:
        return float(price_match.group(1))
    return None

# ========== 新增函数：标题模糊去重（解决微小差异导致的重复） ==========
def fuzzy_title_match(title1, title2, threshold=0.8):
    """
    模糊匹配两个标题，判断是否为同一商品
    threshold：相似度阈值（0.8表示80%相似即判定为同一商品）
    """
    from difflib import SequenceMatcher
    # 统一格式：小写+去除空格+去除特殊符号
    def clean_title(title):
        title = title.lower().strip()
        title = re.sub(r'[^\w\s]', '', title)  # 去除标点符号
        title = re.sub(r'\s+', '', title)      # 去除所有空格
        return title
    
    cleaned1 = clean_title(title1)
    cleaned2 = clean_title(title2)
    # 计算标题相似度
    similarity = SequenceMatcher(None, cleaned1, cleaned2).ratio()
    return similarity >= threshold

def calculate_dynamic_price_range(price_list, outlier_factor=1.5):
    valid_prices = [p for p in price_list if p is not None and p > 0]
    if len(valid_prices) < 5:
        return (10, 100000)
    q1 = statistics.quantiles(valid_prices, n=4)[0]
    q3 = statistics.quantiles(valid_prices, n=4)[2]
    iqr = q3 - q1
    min_valid = max(10, q1 - outlier_factor * iqr)
    max_valid = q3 + outlier_factor * iqr
    print(f"\n📊 自动计算合理价格区间：")
    print(f"   - 原始价格样本数：{len(valid_prices)}")
    print(f"   - 下四分位数(Q1)：{round(q1, 2)}元，上四分位数(Q3)：{round(q3, 2)}元")
    print(f"   - 合理价格区间：{round(min_valid, 2)} ~ {round(max_valid, 2)}元")
    return (min_valid, max_valid)

def clean_and_extract_data(title, price_str, price_range):
    if re.search(r'回收|求购|收|收二手|高价收', title, re.IGNORECASE):
        return None
    price_num = extract_price_num(price_str)
    if price_num is None:
        return None
    min_valid, max_valid = price_range
    if price_num < min_valid or price_num > max_valid:
        print(f"❌ 过滤异常价：{title[:25]}...（{price_num}元，超出区间{min_valid:.0f}-{max_valid:.0f}元）")
        return None
    condition = "未知"
    condition_patterns = [
        (r'全新|未拆封|未使用', '全新'),
        (r'99新|九九新', '99新'),
        (r'95新|九五新', '95新'),
        (r'9成新|九成新', '9成新'),
        (r'85新|八五新', '85新'),
        (r'8成新|八成新', '8成新'),
        (r'7成新|七成新', '7成新'),
        (r'战损|伊拉克|磕碰严重', '战损版')
    ]
    for pattern, desc in condition_patterns:
        if re.search(pattern, title, re.IGNORECASE):
            condition = desc
            break
    core_model = "未知型号"
    phone_pattern = r'(iPhone\s*\d+[A-Za-z]*|华为\s*Mate\s*\d+|华为\s*P\s*\d+|小米\s*1\d+|Redmi\s*\w+|荣耀\s*\d+)'
    phone_match = re.search(phone_pattern, title, re.IGNORECASE)
    if phone_match:
        core_model = phone_match.group(1).strip()
    elif re.search(r'([a-zA-Z]+[^，。！\s]*\d+|[\u4e00-\u9fa5]+[^，。！\s]*\d+)', title):
        model_match = re.search(r'([a-zA-Z]+[^，。！\s]*\d+|[\u4e00-\u9fa5]+[^，。！\s]*\d+)', title)
        core_model = model_match.group(1).strip() if model_match else "未知型号"
    return {
        "title": title.strip(),
        "price_str": price_str,
        "price_num": price_num,
        "condition": condition,
        "core_model": core_model
    }

def calculate_statistics(cleaned_prices):
    valid_prices = [p for p in cleaned_prices if p is not None and p > 0]
    if not valid_prices:
        return {"平均价": 0, "中位数": 0, "有效数据量": 0, "总爬取量": len(cleaned_prices), "最低有效价": 0, "最高有效价": 0}
    avg_price = round(statistics.mean(valid_prices), 2)
    median_price = round(statistics.median(valid_prices), 2)
    return {
        "平均价": avg_price,
        "中位数": median_price,
        "有效数据量": len(valid_prices),
        "总爬取量": len(cleaned_prices),
        "最低有效价": round(min(valid_prices), 2),
        "最高有效价": round(max(valid_prices), 2)
    }

# ========== 主爬虫函数（核心修改：翻页逻辑） ==========
def crawl_xianyu(keyword: str, max_pages: int = 3, save_filename: str = None):
    if save_filename is None:
        save_filename = f'闲鱼_{keyword}_{time.strftime("%Y%m%d_%H%M")}.csv'
    
    raw_data = []
    raw_price_list = []
    encoded_kw = quote(keyword, encoding='utf-8')
    
    # Selenium配置
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={headers['User-Agent']}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    wait = WebDriverWait(driver, 20)  # 显式等待对象
    
    try:
        # 登录
        driver.get("https://www.goofish.com")
        print("="*50)
        print("⚠️  先登录！登录完成后按回车继续")
        print("="*50)
        input()
        
        # ========== 核心修改：输入页码跳转翻页 ==========
                # ========== 核心修改：输入页码跳转翻页（含确认按钮） ==========
        for target_page in range(1, max_pages + 1):
            print(f"\n🔍 正在爬取第 {target_page}/{max_pages} 页")
            # 1. 直接构造目标页URL（兜底）
            target_url = f"https://www.goofish.com/search?q={encoded_kw}&page={target_page}"
            driver.get(target_url)
            
            # 2. 等待页面加载完成
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div[class*="search-container"] div[class*="feeds-list-container"]')
            ))
            time.sleep(random.uniform(2, 3))  # 短等待确保渲染完成
            
            # 3. 通过“输入页码框”+“确认按钮”跳转（最强保险）
            try:
                # 定位页码输入框 & 确认按钮（基于你提供的Selector）
                page_input = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'input[class*="search-pagination-to-page-input"]')
                ))
                confirm_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'button[class*="search-pagination-to-page-confirm-button"]')
                ))
                
                # 输入目标页码并确认
                page_input.clear()
                page_input.send_keys(str(target_page))
                time.sleep(0.5)  # 输入后短暂停顿，模拟人工操作
                confirm_btn.click()
                print(f"✅ 已通过输入框+确认按钮跳转到第 {target_page} 页")
                
                # 等待页面刷新完成
                wait.until(EC.staleness_of(
                    driver.find_element(By.CSS_SELECTOR, 'div[class*="feeds-list-container"]')
                ))
                time.sleep(random.uniform(1, 2))  # 确认后再等一下，确保页面稳定
            except Exception as e:
                print(f"⚠️  输入框+确认按钮跳转失败，使用URL兜底：{target_url}")
            
            # 4. 解析页面
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            items = soup.select('div[class*="search-container"] div[class*="feeds-list-container"] a[class*="feeds-item-wrap"]')
            print(f"本页找到 {len(items)} 个商品")
            
            if len(items) == 0:
                print(f"❌ 第{target_page}页无商品，停止翻页")
                break
            
            for item in items:
                try:
                    title_tag = item.select_one('div[class^="row1-wrap-tit"] span')
                    title = title_tag.get_text(strip=True) if title_tag else "无标题"
                    price_tag = item.select_one('div[class^="row3-wrap-price"]')
                    price_str = price_tag.get_text(strip=True) if price_tag else "无价格"
                    service_tag = item.select_one('div[class^="row2-wrap-service"]')
                    service = service_tag.get_text(strip=True) if service_tag else "无服务信息"
                    seller_tag = item.select_one('div[class^="row4-wrap-seller"]')
                    seller = seller_tag.get_text(strip=True) if seller_tag else "无卖家"
                    href = item.get('href', '')
                    link = f"https:{href}" if href.startswith('//') else f"https://www.goofish.com{href}" if href else "无链接"
                    
                    raw_data.append([title, service, price_str, seller, link])
                    raw_price_list.append(extract_price_num(price_str))
                except Exception as e:
                    continue
        
    finally:
        driver.quit()
    
    # 后续清理&统计（完全不变）
    price_range = calculate_dynamic_price_range(raw_price_list)
    print(f"\n🔍 阶段2：基于动态区间清理数据")
    cleaned_data = []
    cleaned_price_list = []
    for raw_item in raw_data:
        title, service, price_str, seller, link = raw_item
        extracted_info = clean_and_extract_data(title, price_str, price_range)
        if extracted_info is None:
            continue
        cleaned_item = [
            extracted_info["title"],
            extracted_info["core_model"],
            extracted_info["condition"],
            price_str,
            extracted_info["price_num"],
            service,
            seller,
            link
        ]
        cleaned_data.append(cleaned_item)
        cleaned_price_list.append(extracted_info["price_num"])
    
    if cleaned_data:
        with open(save_filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['标题', '核心型号', '成色', '原始价格', '价格（数字）', '服务信息', '卖家', '链接'])
            writer.writerows(cleaned_data)
        
        stats = calculate_statistics(cleaned_price_list)
        print(f"\n🎉 爬取&清理完成！")
        print(f"📊 最终数据统计（{keyword}）：")
        print(f"   - 原始爬取商品数：{len(raw_data)}")
        print(f"   - 有效商品数：{stats['有效数据量']}")
        print(f"   - 价格平均值：{stats['平均价']} 元")
        print(f"   - 价格中位数：{stats['中位数']} 元")
        print(f"   - 有效价格区间：{stats['最低有效价']} ~ {stats['最高有效价']} 元")
        print(f"💾 保存文件：{save_filename}")
    else:
        print("\n⚠️ 未爬取到有效数据")
    
    return cleaned_data, stats

# ==================== 运行 ====================
if __name__ == "__main__":
    keyword = input("输入搜索关键词：").strip() 
    pages = int(input("输入爬取页数：").strip() or 3)
    crawl_xianyu(keyword, max_pages=pages)