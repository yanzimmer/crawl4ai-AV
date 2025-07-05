import asyncio
from crawl4ai import *
from bs4 import BeautifulSoup
from datetime import datetime

async def get_movie_list(crawler):
    result = await crawler.arun(
        url="https://javdb.com/",
    )
    soup = BeautifulSoup(result.html, "html.parser")
    alt_movie_items = soup.select("div.item")
    movies = []
    for item in alt_movie_items:
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
    return movies

async def get_download_links(crawler, movie_url):
    result = await crawler.arun(
        url=f"https://javdb.com{movie_url}",
    )
    soup = BeautifulSoup(result.html, "html.parser")
    # 使用用户提供的选择器查找下载链接容器
    download_containers = soup.select("#magnets-content > div > div.magnet-name.column.is-four-fifths")
    download_info = []
    for container in download_containers:
        a_tags = container.select("a")
        meta_tag = container.select_one("span.meta")
        size = meta_tag.text.strip() if meta_tag else "N/A"
        for a_tag in a_tags:
            href = a_tag.get("href")
            if href:
                download_info.append({"link": href, "size": size})
    
    if not download_info:
        return []
    
    def parse_size(size_str):
        try:
            if "GB" in size_str:
                return float(size_str.replace("GB", "").strip()) * 1024
            elif "MB" in size_str:
                return float(size_str.replace("MB", "").strip())
            elif "KB" in size_str:
                return float(size_str.replace("KB", "").strip()) / 1024
            return 0
        except (ValueError, TypeError):
            return 0
    
    min_size_info = min(download_info, key=lambda x: parse_size(x["size"]))
    return [min_size_info]

async def main():
    try:
        async with AsyncWebCrawler() as crawler:
            movies = await get_movie_list(crawler)
            
            # 打印电影列表
            for idx, movie in enumerate(movies, 1):
                print(f"{idx}. 番号: {movie['番号']}, 标题: {movie['标题']}, 时间: {movie['时间']}, 评分: {movie['评分']}")
            
            # 获取用户选择
            try:
                choice_input = input("请输入要查询的电影序号（多个序号用空格分隔，输入 0 退出）: ")
                if choice_input == "0":
                    return
                choices = []
                for choice_str in choice_input.strip().split(): 
                    try:
                        choice = int(choice_str)
                        if 1 <= choice <= len(movies):
                            choices.append(choice)
                        else:
                            print(f"输入的序号 {choice} 超出范围，已跳过，请输入有效的序号。")
                    except ValueError:
                        print(f"输入的 {choice_str} 无效，已跳过，请输入数字。")
                
                for choice in choices:
                    selected_movie = movies[choice - 1]
                    print(f"你选择了: 番号: {selected_movie['番号']}, 标题: {selected_movie['标题']}, 时间: {selected_movie['时间']}, 评分: {selected_movie['评分']}")
                    download_info = await get_download_links(crawler, selected_movie['链接'])
                    print(f"该番号的下载链接数量: {len(download_info)}（已筛选出最小的链接）")
                    if download_info:
                        for info in download_info:
                            info_str = f"下载链接：{info['link']} 链接大小：{info['size']}"
                            print(info_str)
                            current_time = datetime.now().strftime("%Y%m%d%H%M")
                            file_name = f"{current_time}.txt"
                            # 提取 magnet 磁力链接
                            magnet_link = info['link']
                            with open(file_name, "a", encoding="utf-8") as f:
                                f.write(magnet_link + "\n")
            except Exception as e:
                print(f"输入处理出错: {str(e)}")
    except Exception as e:
        print(f"程序运行出错: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())