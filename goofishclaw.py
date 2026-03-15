import time
import random
import csv
import os
import json
from urllib.parse import quote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --------------------- 全局配置 ---------------------
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_BASE_DIR = os.path.join(BASE_DIR, "data", "raw_data")
COOKIE_FILE = os.path.join(BASE_DIR, "xianyu_cookies.json")

# --------------------- Cookie免登核心函数 ---------------------
def save_cookies(driver, cookie_path):
    """保存登录Cookie到本地，后续免登"""
    try:
        cookies = driver.get_cookies()
        with open(cookie_path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        print(f"✅ 登录状态已保存，后续自动免登")
        return True
    except Exception as e:
        print(f"❌ 保存登录状态失败：{str(e)}")
        return False

def load_cookies(driver, cookie_path):
    """加载本地Cookie，恢复登录态"""
    if not os.path.exists(cookie_path):
        print("ℹ️  首次使用，需要手动登录")
        return False
    try:
        with open(cookie_path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        driver.get("https://www.goofish.com")
        time.sleep(1)
        for cookie in cookies:
            if 'expiry' in cookie:
                cookie['expires'] = cookie.pop('expiry')
            try:
                driver.add_cookie(cookie)
            except:
                continue
        print(f"✅ 已自动恢复登录态，免登成功")
        return True
    except Exception as e:
        print(f"❌ 恢复登录态失败：{str(e)}")
        return False

# --------------------- 【核心重写】精准价格提取函数 ---------------------
def extract_clean_price(item_element):
    """
    基于闲鱼实际DOM结构，精准提取完整价格
    匹配：整数部分number + 小数部分decimal + 单位magnitude（万）
    完整还原：2.19万、3.15万、9300 等格式
    """
    try:
        # 1. 先定位价格父容器（所有价格相关元素都在这个容器里）
        price_parent = item_element.select_one('div[class*="row3-wrap-price"]')
        if not price_parent:
            return "无价格"
        
        # 2. 分别提取价格三要素
        # 整数部分（必填）
        number_tag = price_parent.select_one('span[class*="number-"]')
        if not number_tag:
            return "无价格"
        number_str = number_tag.get_text(strip=True)
        
        # 小数部分（可选，没有就为空）
        decimal_tag = price_parent.select_one('span[class*="decimal-"]')
        decimal_str = decimal_tag.get_text(strip=True) if decimal_tag else ""
        
        # 单位部分（可选，万/千等，没有就为空）
        magnitude_tag = price_parent.select_one('span[class*="magnitude-"]')
        magnitude_str = magnitude_tag.get_text(strip=True) if magnitude_tag else ""
        
        # 3. 拼接成完整价格字符串
        full_price = f"{number_str}{decimal_str}{magnitude_str}"
        
        # 4. 兜底校验，确保价格有效
        if not full_price or len(full_price) == 0:
            return "无价格"
        
        return full_price

    except Exception as e:
        print(f"价格提取失败：{str(e)}")
        return "无价格"

# --------------------- 主爬虫函数 ---------------------
def crawl_xianyu(keyword: str, max_pages: int = 3, save_filename: str = None):
    # 初始化保存路径
    os.makedirs(SAVE_BASE_DIR, exist_ok=True)
    if save_filename is None:
        save_filename = f'闲鱼_{keyword}_{time.strftime("%Y%m%d_%H%M%S")}.csv'
    save_path = os.path.join(SAVE_BASE_DIR, save_filename)
    
    all_data = []
    encoded_kw = quote(keyword, encoding='utf-8')
    
    # Selenium浏览器配置（隐藏反爬特征）
    # Selenium浏览器配置（本地调试+服务器部署兼容版）
    options = Options()

    # ===================== 环境切换开关 =====================
    # 本地调试：注释下面这行（能看到浏览器）；服务器部署：取消注释（必须开启）
    options.add_argument("--headless=new")  

    # ===================== 通用核心配置（全部保留） =====================
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # 建议更新UA为真实版本，比如Chrome 124
    options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # ===================== 服务器/稳定性补充（新增，本地兼容） =====================
    options.add_argument("--disable-gpu")  # 服务器必需，本地无影响
    options.add_argument("--window-size=1920,1080")  # 固定窗口，避免元素定位失败
    options.add_argument("--ignore-certificate-errors")  # 忽略证书错误

    # ===================== 初始化驱动+清除webdriver标识（新增，反爬关键） =====================
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    # 核心反爬：清除selenium的webdriver标识，闲鱼几乎必检测这个
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")


    driver = None
    try:
        # 启动浏览器
        print("🚀 正在启动浏览器...")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # 免登逻辑
        cookie_loaded = load_cookies(driver, COOKIE_FILE)
        if not cookie_loaded:
            driver.get("https://www.goofish.com")
            print("\n" + "="*60)
            print("⚠️  请在浏览器中手动登录闲鱼，登录成功后回到此窗口按回车继续")
            print("="*60 + "\n")
            input()
            save_cookies(driver, COOKIE_FILE)
        
        # 刷新页面，确认登录态生效
        driver.refresh()
        time.sleep(3)
        
        # 逐页爬取
        for page in range(1, max_pages + 1):
            url = f"https://www.goofish.com/search?q={encoded_kw}&page={page}"
            print(f"\n📄 正在爬取第 {page}/{max_pages} 页 → {url}")
            
            # 访问页面，等待加载
            driver.get(url)
            wait_time = random.uniform(6, 10)
            print(f"   等待页面加载 {wait_time:.1f} 秒...")
            time.sleep(wait_time)
            
            # 解析页面商品
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            items = soup.select('div[class*="search-container"] div[class*="feeds-list-container"] a[class*="feeds-item-wrap"]')
            print(f"   本页找到 {len(items)} 个商品")
            
            if len(items) == 0:
                print("❌ 未找到商品，页面源码已保存到debug.html，可查看结构")
                with open("debug.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                continue
            
            # 解析每个商品
            print("\n===== 【精准价格提取调试】 =====")
            for idx, item in enumerate(items):
                try:
                    # 1. 商品标题
                    title_tag = item.select_one('div[class^="row1-wrap-title"] span')
                    title = title_tag.get_text(strip=True) if title_tag else "无标题"
                    
                    # 2. 【核心】精准提取完整价格（含万单位）
                    price = extract_clean_price(item)
                    
                    # 调试打印，100%确认价格是否正确
                    print(f"商品{idx+1} | 提取价格：{price} | 标题：{title[:25]}")
                    
                    # 3. 商品地区
                    seller_tag = item.select_one('div[class*="row4-wrap-seller"] div[class*="seller-text-wrap"] div[class*="seller-left"] p[class*="seller-text"]')
                    area = seller_tag.get_text(strip=True) if seller_tag else "无地区"
                    
                    # 4. 商品链接（修复重复问题）
                    href = item.get('href', '')
                    if href.startswith('//'):
                        link = f"https:{href}"
                    elif href.startswith('/'):
                        link = f"https://www.goofish.com{href}"
                    else:
                        link = href
                    
                    all_data.append([title, price, area, link])
                    
                except Exception as e:
                    print(f"商品{idx+1} 解析失败：{str(e)[:40]}")
                    continue
            print("=======================================\n")
            
            # 翻页间隔，模拟真人操作，避免被封
            if page < max_pages:
                interval = random.uniform(4, 7)
                print(f"   翻页间隔 {interval:.1f} 秒...")
                time.sleep(interval)
            
    except Exception as e:
        print("\n" + "!"*60)
        print(f"❌ 爬虫运行错误：{str(e)}")
        import traceback
        print("详细错误信息：")
        print(traceback.format_exc())
        print("!"*60 + "\n")
        
    finally:
        # 无论成功失败，都关闭浏览器
        if driver:
            try:
                driver.quit()
                print("🔒 浏览器已关闭")
            except:
                pass
    
    # 保存数据到CSV
    if all_data:
        try:
            with open(save_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['标题', '价格', '地区', '链接'])
                writer.writerows(all_data)
            print(f"🎉 爬取完成！共获取 {len(all_data)} 条数据")
            print(f"💾 数据已保存至：{save_path}")
        except Exception as e:
            print(f"❌ 保存数据失败：{str(e)}")
    else:
        print("⚠️ 未爬取到有效数据")
    
    return all_data

# --------------------- 本地运行入口 ---------------------
if __name__ == "__main__":
    print("="*60)
    print("           🐟 闲鱼商品数据爬取工具 (DOM精准匹配版)")
    print("="*60)
    
    keyword = input("\n请输入搜索关键词：").strip() 
    if not keyword:
        print("❌ 关键词不能为空！")
    else:
        pages_input = input("请输入爬取页数 (默认3)：").strip()
        pages = int(pages_input) if pages_input.isdigit() else 3
        crawl_xianyu(keyword, max_pages=pages)
    
    input("\n按回车键退出程序...")