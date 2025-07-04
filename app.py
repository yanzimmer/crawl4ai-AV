import asyncio
from crawl4ai import *
from bs4 import BeautifulSoup

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
    return download_info

async def main():
    try:
        async with AsyncWebCrawler() as crawler:
            movies = await get_movie_list(crawler)
            
            # 打印电影列表
            for idx, movie in enumerate(movies, 1):
                print(f"{idx}. 番号: {movie['番号']}, 标题: {movie['标题']}, 时间: {movie['时间']}, 评分: {movie['评分']}")
            
            # 获取用户选择
            try:
                choice = int(input("请输入要查询的电影序号（输入 0 退出）: "))
                if choice == 0:
                    return
                if 1 <= choice <= len(movies):
                    selected_movie = movies[choice - 1]
                    print(f"你选择了: 番号: {selected_movie['番号']}, 标题: {selected_movie['标题']}, 时间: {selected_movie['时间']}, 评分: {selected_movie['评分']}")
                    download_info = await get_download_links(crawler, selected_movie['链接'])
                    print(f"该番号的下载链接数量: {len(download_info)}")
                    if download_info:
                        for info in download_info:
                            print(f"下载链接：{info['link']} 链接大小：{info['size']}")
                else:
                    print("输入的序号超出范围，请输入有效的序号。")
            except ValueError:
                print("输入无效，请输入一个数字。")
    except Exception as e:
        print(f"程序运行出错: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())