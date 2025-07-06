from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime
import asyncio
import os
from crawl4ai import *
from bs4 import BeautifulSoup
import queue
import threading
import time
import re
import logging
import atexit
import sys
import io
import json
import glob
import traceback
import shutil

app = Flask(__name__)

# 全局变量和默认值
DEFAULT_FILE_SIZE_GB = 6.0
task_queue = queue.Queue()
log_messages = []
MAX_FILE_SIZE_GB = DEFAULT_FILE_SIZE_GB
SEARCHED_CODES_FILE = 'searched_codes.json'
SETTINGS_FILE = 'settings.json'
crawler = None
crawler_lock = asyncio.Lock()  # 使用异步锁
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒
SEARCHED_COUNT_FILE = 'searched_count.json'
LINKS_FILE = 'links.json'
HISTORY_DIR = 'history'

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.__stdout__)]
)
logger = logging.getLogger()

# 禁用werkzeug的默认日志
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.WARNING)

def add_log(message):
    if not isinstance(message, str):
        message = str(message)
    # 过滤掉重复的HTTP请求日志
    if 'HTTP/1.1' in message or 'GET /get_logs' in message:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    log_messages.append(log_entry)
    if len(log_messages) > 1000:
        log_messages.pop(0)
    # 使用原始stdout输出到控制台
    print(log_entry, file=sys.__stdout__)

def cleanup():
    global crawler
    if crawler:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(crawler.__aexit__(None, None, None))
            loop.close()
            crawler = None
        except Exception as e:
            add_log(f"清理浏览器实例时出错: {e}")
            try:
                if loop and not loop.is_closed():
                    loop.close()
            except:
                pass
            crawler = None

atexit.register(cleanup)

# 自定义日志处理器
class CustomLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if not ('HTTP/1.1' in msg or 'GET /get_logs' in msg):
                add_log(msg)
        except Exception:
            self.handleError(record)

# 添加自定义日志处理器
custom_handler = CustomLogHandler()
custom_handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(custom_handler)

def parse_size(size_str):
    try:
        size_str = size_str.split(',')[0].strip()
        if "GB" in size_str:
            return float(size_str.replace("GB", "").strip())
        elif "MB" in size_str:
            return float(size_str.replace("MB", "").strip()) / 1024
        elif "KB" in size_str:
            return float(size_str.replace("KB", "").strip()) / (1024 * 1024)
        return 0
    except (ValueError, TypeError):
        return 0

def get_existing_links(filename):
    """获取已存在的链接集合，如果文件不存在则创建"""
    existing_links = set()
    try:
        # 确保使用完整路径
        if not os.path.isabs(filename):
            filename = os.path.join(HISTORY_DIR, os.path.basename(filename))
        
        # 确保目录存在
        ensure_directories()
        
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                existing_links = set(line.strip() for line in f if line.strip())
        else:
            # 如果文件不存在，创建一个空文件
            with open(filename, 'w', encoding='utf-8') as f:
                pass
    except Exception as e:
        add_log(f"读取现有链接时出错: {str(e)}")
    return existing_links

def create_crawler():
    """创建新的浏览器实例"""
    try:
        return AsyncWebCrawler()
    except Exception as e:
        add_log(f"创建浏览器实例失败: {str(e)}")
        return None

async def safe_request(url):
    """安全地发送请求，带有重试机制"""
    for attempt in range(MAX_RETRIES):
        crawler = None
        try:
            # 每次请求都创建新的实例
            crawler = create_crawler()
            if crawler is None:
                raise Exception("无法创建浏览器实例")
            
            result = await crawler.arun(url=url)
            return result
            
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                add_log(f"第 {attempt + 1} 次请求失败，{RETRY_DELAY}秒后重试: {str(e)}")
                await asyncio.sleep(RETRY_DELAY)
            else:
                add_log(f"请求失败，已达到最大重试次数: {str(e)}")
                raise
        finally:
            # 确保每次都清理浏览器实例
            if crawler:
                try:
                    await crawler.__aexit__(None, None, None)
                except:
                    pass

async def process_code(code):
    try:
        add_log(f"开始处理番号: {code}")
        
        try:
            # 搜索影片
            search_url = f"https://javdb.com/search?q={code}&f=all"
            result = await safe_request(search_url)
            if result is None:
                raise Exception("请求返回为空")
            
            soup = BeautifulSoup(result.html, "html.parser")
            movie_items = soup.select("div.item")
            
            if not movie_items:
                error_msg = "未找到相关影片"
                add_log(error_msg)
                return {"error": error_msg}
            
            movies = []
            for item in movie_items:
                # 提取番号
                code_element = item.select_one("strong")
                code = code_element.text.strip() if code_element else "N/A"
                
                # 提取标题
                title_element = item.select_one("a")
                title = title_element.get("title", "N/A") if title_element else "N/A"
                
                # 提取链接
                link = title_element.get("href", "N/A") if title_element else "N/A"
                
                # 提取时间
                date_element = item.select_one("div.meta")
                date = date_element.text.strip() if date_element else "N/A"
                
                # 提取评分
                rating_element = item.select_one("div.score span.value")
                rating = rating_element.text.strip() if rating_element else "N/A"
                
                movies.append({
                    "番号": code,
                    "标题": title,
                    "链接": link,
                    "时间": date,
                    "评分": rating
                })
            
            # 打印搜索结果
            for idx, movie in enumerate(movies, 1):
                add_log(f"{idx}. 番号: {movie['番号']}, 标题: {movie['标题']}, 时间: {movie['时间']}, 评分: {movie['评分']}")
            
            if movies:
                selected_movie = movies[0]
                add_log(f"自动选择: 番号: {selected_movie['番号']}, 标题: {selected_movie['标题']}")
                
                # 获取下载链接
                result = await safe_request(f"https://javdb.com{selected_movie['链接']}")
                soup = BeautifulSoup(result.html, "html.parser")
                download_containers = soup.select("#magnets-content > div > div.magnet-name.column.is-four-fifths")
                download_info = []
                
                add_log("检查所有可用的下载链接：")
                for container in download_containers:
                    a_tags = container.select("a")
                    meta_tag = container.select_one("span.meta")
                    size = meta_tag.text.strip() if meta_tag else "N/A"
                    
                    file_size_gb = parse_size(size)
                    add_log(f"发现链接，大小: {size} ({file_size_gb}GB)")
                    
                    if file_size_gb <= MAX_FILE_SIZE_GB:
                        for a_tag in a_tags:
                            href = a_tag.get("href")
                            if href:
                                download_info.append({"link": href, "size": size, "size_gb": file_size_gb})
                                add_log("已添加到下载列表")
                    else:
                        add_log(f"已跳过（超过大小限制 {MAX_FILE_SIZE_GB}GB）")
                
                if not download_info:
                    error_msg = f"没有找到符合大小限制（{MAX_FILE_SIZE_GB}GB）的链接"
                    add_log(error_msg)
                    return {"error": error_msg}
                
                min_size_info = min(download_info, key=lambda x: x["size_gb"])
                add_log(f"选择最小的符合条件的链接：{min_size_info['size']}")
                
                # 保存链接
                current_date = datetime.now().strftime("%Y%m%d")
                file_name = os.path.join(HISTORY_DIR, f"{current_date}.txt")
                magnet_link = min_size_info['link']
                
                # 检查链接是否已存在
                existing_links = get_existing_links(file_name)
                if magnet_link in existing_links:
                    add_log("链接已存在，跳过保存")
                else:
                    try:
                        # 确保 history 目录存在
                        ensure_directories()
                        
                        # 使用追加模式写入文件
                        with open(file_name, "a", encoding="utf-8") as f:
                            f.write(magnet_link + "\n")
                            f.flush()
                            os.fsync(f.fileno())
                        add_log(f"已保存到文件: {file_name}")
                        # 更新搜索计数
                        add_searched_code(code)
                        add_log(f"已更新搜索计数: {get_searched_count()}")
                    except Exception as e:
                        error_msg = f"保存文件时出错: {str(e)}"
                        add_log(error_msg)
                        return {"error": error_msg}
                
        except Exception as e:
            error_msg = f"处理过程出错: {str(e)}\n{traceback.format_exc()}"
            add_log(error_msg)
            return {"error": error_msg}
        
        return {"success": True, "message": "处理完成"}
        
    except Exception as e:
        error_msg = f"未知错误: {str(e)}\n{traceback.format_exc()}"
        add_log(error_msg)
        return {"error": error_msg}

def process_queue():
    while True:
        try:
            if not task_queue.empty():
                code = task_queue.get()
                # 创建新的事件循环来运行异步任务
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(process_code(code))
                finally:
                    loop.close()
            time.sleep(1)
        except Exception as e:
            error_msg = f"队列处理出错: {str(e)}\n{traceback.format_exc()}"
            add_log(error_msg)

def move_files_to_history():
    """将当前目录下的txt和json文件移动到history目录"""
    try:
        # 确保history目录存在
        ensure_directories()
        
        # 获取当前目录下的所有txt和json文件
        for pattern in ['*.txt', '*.json']:
            for file_path in glob.glob(pattern):
                # 跳过特殊文件
                if file_path in [SEARCHED_COUNT_FILE, LINKS_FILE, 'settings.json']:
                    continue
                    
                # 构建目标路径
                target_path = os.path.join(HISTORY_DIR, os.path.basename(file_path))
                
                try:
                    # 如果目标文件已存在，先删除
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    # 移动文件
                    shutil.move(file_path, target_path)
                    print(f"移动文件 {file_path} 到 {target_path}")
                except Exception as e:
                    print(f"移动文件 {file_path} 失败: {e}")
    except Exception as e:
        print(f"移动文件到history目录时出错: {e}")

def ensure_directories():
    """确保所有必要的目录都存在"""
    directories = [HISTORY_DIR]
    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
                print(f"创建目录: {directory}")
            except Exception as e:
                print(f"创建目录 {directory} 失败: {e}")

# 在应用启动时确保目录存在并移动文件
ensure_directories()
move_files_to_history()

def save_links(links):
    """保存链接到当前日期的文件"""
    try:
        current_date = datetime.now().strftime("%Y%m%d")
        file_path = os.path.join(HISTORY_DIR, f"{current_date}.txt")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            for link in links:
                f.write(f"{link}\n")
        print(f"保存链接到文件: {file_path}")
    except Exception as e:
        print(f"保存链接出错: {e}")

def get_links_data():
    try:
        # 获取当前日期的文件名
        current_date = datetime.now().strftime("%Y%m%d")
        current_file = f"{current_date}.txt"
        current_file_path = os.path.join(HISTORY_DIR, current_file)
        
        # 如果文件存在于history目录中，读取它
        if os.path.exists(current_file_path):
            with open(current_file_path, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        # 如果文件在当前目录中，移动它并读取
        elif os.path.exists(current_file):
            shutil.move(current_file, current_file_path)
            with open(current_file_path, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        return []
    except Exception as e:
        print(f"读取链接数据出错: {e}")
        return []

def get_history_files():
    try:
        ensure_directories()
        files = []
        # 搜索所有txt和json文件
        for pattern in ['*.txt', '*.json']:
            for file_path in glob.glob(os.path.join(HISTORY_DIR, pattern)):
                try:
                    filename = os.path.basename(file_path)
                    stat = os.stat(file_path)
                    link_count = 0
                    
                    # 根据文件类型读取内容
                    if file_path.endswith('.json'):
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            link_count = len(data.get('links', []))
                    else:  # .txt文件
                        with open(file_path, 'r', encoding='utf-8') as f:
                            link_count = sum(1 for line in f if line.strip())
                    
                    files.append({
                        'name': filename,
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                        'size': stat.st_size,
                        'link_count': link_count
                    })
                except Exception as e:
                    print(f"读取历史文件 {filename} 出错: {e}")
                    continue
        
        # 按修改时间降序排序
        return sorted(files, key=lambda x: x['modified'], reverse=True)
    except Exception as e:
        print(f"获取历史文件列表出错: {e}")
        return []

def get_searched_codes():
    """获取已搜索的番号列表"""
    try:
        if os.path.exists(SEARCHED_COUNT_FILE):
            with open(SEARCHED_COUNT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get('codes', []))
        else:
            # 如果文件不存在，创建它并初始化为空列表
            save_searched_codes(set())
            return set()
    except Exception as e:
        add_log(f"读取已搜索番号出错: {str(e)}")
        return set()

def save_searched_codes(codes):
    """保存已搜索的番号列表"""
    try:
        with open(SEARCHED_COUNT_FILE, 'w', encoding='utf-8') as f:
            json.dump({'codes': list(codes), 'count': len(codes)}, f, ensure_ascii=False, indent=4)
    except Exception as e:
        add_log(f"保存已搜索番号出错: {str(e)}")

def add_searched_code(code):
    """添加一个成功搜索的番号"""
    codes = get_searched_codes()
    if code not in codes:
        codes.add(code)
        save_searched_codes(codes)
        add_log(f"已添加番号到记录: {code}")
    return len(codes)

def get_searched_count():
    """获取已搜索的番号数量"""
    try:
        if os.path.exists(SEARCHED_COUNT_FILE):
            with open(SEARCHED_COUNT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return len(data.get('codes', []))
        return 0
    except Exception as e:
        add_log(f"读取搜索计数出错: {str(e)}")
        return 0

@app.route('/')
def index():
    # 确保计数文件存在
    searched_count = get_searched_count()
    # 获取历史文件列表
    history_files = get_history_files()
    # 获取当前链接
    current_links = get_links_data()
    
    return render_template('template.html', 
                         searched_count=searched_count,
                         history_files=history_files,
                         links=current_links,
                         max_file_size_gb=MAX_FILE_SIZE_GB)

@app.route('/get_logs')
def get_logs():
    return jsonify({
        'logs': log_messages,
        'links': get_links_data(),
        'history_files': get_history_files(),
        'searched_count': get_searched_count(),
        'max_file_size_gb': MAX_FILE_SIZE_GB
    })

@app.route('/download/<filename>')
def download_file(filename):
    try:
        return send_file(filename, as_attachment=True)
    except Exception as e:
        return str(e), 404

@app.route('/view/<filename>')
def view_file(filename):
    try:
        file_path = os.path.join(HISTORY_DIR, filename)
        if not os.path.exists(file_path):
            return jsonify({'error': '文件不存在'})
            
        links = []
        if filename.endswith('.json'):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                links = data.get('links', [])
        else:  # .txt文件
            with open(file_path, 'r', encoding='utf-8') as f:
                links = [line.strip() for line in f if line.strip()]
                
        return jsonify({'content': links})
    except Exception as e:
        return jsonify({'error': f'读取文件出错: {str(e)}'})

@app.route('/get_searched_codes')
def get_searched_codes_route():
    """获取已搜索的番号列表"""
    return jsonify({
        'codes': list(get_searched_codes())
    })

@app.route('/add_task', methods=['POST'])
def add_task():
    try:
        data = request.get_json()
        codes = data.get('codes', '').strip()
        
        if not codes:
            return jsonify({"error": "请输入番号"})
        
        # 分割并过滤空字符串
        code_list = [code.strip() for code in codes.split() if code.strip()]
        
        if not code_list:
            return jsonify({"error": "请输入有效的番号"})

        # 添加番号到队列
        for code in code_list:
            task_queue.put(code)
            add_log(f"已添加任务: {code}")
        
        return jsonify({
            "message": f"已添加 {len(code_list)} 个任务到队列",
            "status": "success"
        })
        
    except Exception as e:
        add_log(f"添加任务时出错: {str(e)}")
        return jsonify({"error": str(e)})

def load_settings():
    """加载设置"""
    global MAX_FILE_SIZE_GB
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                MAX_FILE_SIZE_GB = float(settings.get('max_file_size_gb', DEFAULT_FILE_SIZE_GB))
                add_log(f"已加载文件大小限制设置: {MAX_FILE_SIZE_GB}GB")
        else:
            MAX_FILE_SIZE_GB = DEFAULT_FILE_SIZE_GB
            # 创建默认设置文件
            save_settings({'max_file_size_gb': MAX_FILE_SIZE_GB})
            add_log(f"已创建默认设置文件，文件大小限制: {MAX_FILE_SIZE_GB}GB")
    except Exception as e:
        MAX_FILE_SIZE_GB = DEFAULT_FILE_SIZE_GB
        add_log(f"加载设置时出错: {str(e)}，使用默认值 {MAX_FILE_SIZE_GB}GB")
        # 出错时也创建默认设置文件
        save_settings({'max_file_size_gb': MAX_FILE_SIZE_GB})

def save_settings(settings):
    """保存设置"""
    try:
        # 确保目录存在
        settings_dir = os.path.dirname(SETTINGS_FILE)
        if settings_dir and not os.path.exists(settings_dir):
            os.makedirs(settings_dir)
        
        # 保存设置
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())  # 确保写入磁盘
        add_log(f"已保存设置: 文件大小限制 {settings.get('max_file_size_gb', DEFAULT_FILE_SIZE_GB)}GB")
    except Exception as e:
        add_log(f"保存设置出错: {str(e)}")

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    global MAX_FILE_SIZE_GB
    if request.method == 'POST':
        try:
            data = request.get_json()
            if 'reset' in data and data['reset']:
                MAX_FILE_SIZE_GB = DEFAULT_FILE_SIZE_GB
                save_settings({'max_file_size_gb': MAX_FILE_SIZE_GB})
                return jsonify({
                    'status': 'success',
                    'message': '已恢复默认设置',
                    'max_file_size_gb': MAX_FILE_SIZE_GB
                })
            else:
                new_size = float(data.get('max_file_size_gb', DEFAULT_FILE_SIZE_GB))
                if new_size <= 0:
                    return jsonify({
                        'status': 'error',
                        'message': '文件大小限制必须大于0'
                    })
                MAX_FILE_SIZE_GB = new_size
                save_settings({'max_file_size_gb': MAX_FILE_SIZE_GB})
                return jsonify({
                    'status': 'success',
                    'message': '设置已保存',
                    'max_file_size_gb': MAX_FILE_SIZE_GB
                })
        except ValueError:
            return jsonify({
                'status': 'error',
                'message': '无效的文件大小值'
            })
        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': str(e)
            })
    else:
        return jsonify({
            'max_file_size_gb': MAX_FILE_SIZE_GB,
            'default_file_size_gb': DEFAULT_FILE_SIZE_GB
        })

# 初始化设置
load_settings()

# 处理队列的线程
queue_thread = None

if __name__ == '__main__':
    host = '0.0.0.0'
    port = 5000
    add_log(f"服务器正在启动，访问地址: http://{host}:{port}")
    add_log(f"本地访问地址: http://localhost:{port}")
    
    # 只在主程序中启动处理队列的线程
    if not queue_thread or not queue_thread.is_alive():
        queue_thread = threading.Thread(target=process_queue, daemon=True)
        queue_thread.start()
        add_log("任务处理线程已启动")
    
    app.run(debug=True, host=host, port=port) 