import feedparser
import time
import os
import re
import pytz
import traceback
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from multiprocessing.managers import ListProxy
import yagmail
import requests
import markdown
import json
import shutil
import hashlib
from urllib.parse import urlparse
from multiprocessing import Pool, Manager, Value

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# 配置常量
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 8))  # 从环境变量读取，默认 8 个进程
RETRY_TIMES = int(os.getenv("RETRY_TIMES", 3))  # 请求重试次数，默认 3 次


def escape_markdown(text):
    """
    转义 Markdown 特殊字符
    Args:
        text: 需要转义的文本
    Returns:
        转义后的文本
    """
    return text.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")



def get_rss_info(
    feed_url: str,
    index: int,
    rss_info_list: ListProxy,
    progress_counter: Optional[Value] = None
) -> List[Dict[str, str]]:
    """
    获取 RSS 订阅源的文章信息
    Args:
        feed_url: RSS 订阅地址
        index: 在列表中的索引
        rss_info_list: 用于存储结果的共享列表
        progress_counter: 进度计数器（可选）
    Returns:
        RSS 文章列表
    """
    result = {"result": []}
    request_success = False

    # 如果请求出错,则重新请求,最多 RETRY_TIMES 次
    for i in range(RETRY_TIMES):
        if not request_success:
            try:
                headers = {
                    # 设置用户代理头(为狼披上羊皮)
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36",
                    "Content-Encoding": "gzip"
                }
                # 指数退避重试：8s, 16s, 32s
                timeout = 8 * (2 ** i)
                response = requests.get(feed_url, timeout=timeout, headers=headers, stream=True)
                feed_url_content = response.content
                feed = feedparser.parse(feed_url_content)
                feed_entries = feed["entries"]
                feed_entries_length = len(feed_entries)
                logger.info(f"Fetched {feed_url}: {feed_entries_length} entries")

                # 直接遍历，避免完整拷贝
                for entrie in feed_entries:
                    title = entrie["title"]
                    link = entrie["link"]

                    # 日期异常处理
                    try:
                        date = time.strftime("%Y-%m-%d", entrie["published_parsed"])
                    except (KeyError, TypeError):
                        date = datetime.now().strftime("%Y-%m-%d")  # 降级方案
                        logger.warning(f"Published date not found for {feed_url}, using current date")

                    # 清理标题中的换行符
                    title = title.replace("\n", "").replace("\r", "")

                    result["result"].append({
                        "title": title,
                        "link": link,
                        "date": date
                    })
                request_success = True
            except Exception as e:
                logger.warning(f"{feed_url} 第{i+1}次请求失败: {e}")
                if i == 2:  # 最后一次重试
                    logger.error(f"RSS {feed_url} 最终失败")
                    # traceback.print_exc()

    rss_info_list[index] = result["result"]
    logger.info(f"本次爬取==》》 {feed_url} <<<=== 索引: {index}, 文章数: {len(result['result'])}")

    # 更新进度计数器
    if progress_counter is not None:
        with progress_counter.get_lock():
            progress_counter.value += 1
            remaining_amount = len(rss_info_list) - progress_counter.value
            logger.info(f"当前进度: {progress_counter.value}/{len(rss_info_list)}, 剩余: {remaining_amount}")

    return result["result"]
    


def send_mail(email, title, contents):
    # 判断secret.json是否存在
    user = ""
    password = ""
    host = ""
    try:
        if(os.environ["USER"]):
            user = os.environ["USER"]
        if(os.environ["PASSWORD"]):
            password = os.environ["PASSWORD"]
        if(os.environ["HOST"]):
            host = os.environ["HOST"]
    except:
        print("无法获取github的secrets配置信息,开始使用本地变量")
        if(os.path.exists(os.path.join(os.getcwd(),"secret.json"))):
            with open(os.path.join(os.getcwd(),"secret.json"),'r') as load_f:
                load_dict = json.load(load_f)
                user = load_dict["user"]
                password = load_dict["password"]
                host = load_dict["host"]
                # print(load_dict)
        else:
            print("无法获取发件人信息")
    
    # 连接邮箱服务器
    yag = yagmail.SMTP(user = user, password = password, host=host)
    # 发送邮件
    yag.send(email, title, contents)

def replace_readme(edit_readme_md):
    new_edit_readme_md = ["", ""]
    current_date_news_index = [""]


    
    # 使用传入的 edit_readme_md
    print("replace_readme")
    new_num = 0
    new_edit_readme_md[0] = edit_readme_md
    before_info_list =  re.findall(r'\{\{latest_content\}\}.*\[订阅地址\]\(.*\)' ,edit_readme_md);
    # 填充统计RSS数量
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{rss_num}}", str(len(before_info_list)))
    # 填充统计时间
    rss_datetime = datetime.fromtimestamp(int(time.time()),pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{rss_datetime}}", str(rss_datetime))

    # 使用进程池进行数据获取，获得rss_info_list
    before_info_list_len = len(before_info_list)
    rss_info_list = Manager().list(range(before_info_list_len))

    # 创建进度计数器
    progress_counter = Manager().Value('i', 0)

    logger.info(f'初始化完毕，共 {before_info_list_len} 个订阅源')

    # 创建进程池，使用配置的 MAX_WORKERS
    po = Pool(MAX_WORKERS)

    for index, before_info in enumerate(before_info_list):
        # 获取link
        link = re.findall(r'\[订阅地址\]\((.*)\)', before_info)[0]
        po.apply_async(get_rss_info, (link, index, rss_info_list, progress_counter))


    # 关闭进程池,不再接收新的任务,开始执行任务
    po.close()

    # 主进程等待所有子进程结束
    po.join()
    print("----结束----", rss_info_list)


    for index, before_info in enumerate(before_info_list):
        # 获取link
        link = re.findall(r'\[订阅地址\]\((.*)\)', before_info)[0]
        # 生成超链接
        rss_info = rss_info_list[index]
        latest_content = ""
        parse_result = urlparse(link)
        scheme_netloc_url = f"{parse_result.scheme}://{parse_result.netloc}"
        latest_content = f"[暂无法通过爬虫获取信息, 点击进入源网站主页]({scheme_netloc_url})"

        # 获取今天的日期（用于日期比较）
        today = datetime.now().date()

        # 加入到索引 - 使用列表优化字符串拼接
        news_items = []
        try:
            for rss_info_atom in rss_info:
                # 日期比较优化：使用 datetime 对象
                article_date = datetime.strptime(rss_info_atom["date"], "%Y-%m-%d").date()
                if article_date == today:
                    new_num += 1
                    if (new_num % 2) == 0:
                        news_items.append(f"<div style='line-height:3;' ><a href='{rss_info_atom['link']}' style='line-height:2;text-decoration:none;display:block;color:#584D49;'>🌈 ‣ {rss_info_atom['title']} | 第{new_num}篇</a></div>")
                    else:
                        news_items.append(f"<div style='line-height:3;background-color:#FAF6EA;' ><a href='{rss_info_atom['link']}' style='line-height:2;text-decoration:none;display:block;color:#584D49;'>🌈 ‣ {rss_info_atom['title']} | 第{new_num}篇</a></div>")
        except Exception as e:
            print(f"Error processing RSS feed: {e}")
            print(f"Traceback: {traceback.format_exc()}")

        # 使用 join() 优化字符串拼接
        if news_items:
            current_date_news_index[0] += "\n".join(news_items) + "\n"

        # 生成最新内容
        if len(rss_info) > 0:
            # 使用转义函数
            rss_info[0]["title"] = escape_markdown(rss_info[0]["title"])

            # 日期比较优化：使用 datetime 对象
            article_date = datetime.strptime(rss_info[0]["date"], "%Y-%m-%d").date()
            date_str = f" 🌈 {rss_info[0]['date']}" if article_date == today else f" | {rss_info[0]['date']}"
            latest_content = f"[‣ {rss_info[0]['title']}{date_str}]({rss_info[0]['link']})"

        if len(rss_info) > 1:
            # 使用转义函数
            rss_info[1]["title"] = escape_markdown(rss_info[1]["title"])

            # 日期比较优化：使用 datetime 对象
            article_date = datetime.strptime(rss_info[0]["date"], "%Y-%m-%d").date()
            date_str = f" 🌈 {rss_info[0]['date']}" if article_date == today else f" | {rss_info[0]['date']}"
            latest_content += f"<br/>[‣ {rss_info[1]['title']}{date_str}]({rss_info[1]['link']})"

        # 生成after_info
        after_info = before_info.replace("{{latest_content}}", latest_content)
        print("====latest_content==>", latest_content)
        # 替换edit_readme_md中的内容
        new_edit_readme_md[0] = new_edit_readme_md[0].replace(before_info, after_info)
    # 替换EditREADME中的索引
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{news}}", current_date_news_index[0])
    # 替换EditREADME中的新文章数量索引
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{new_num}}", str(new_num))
    # 保持本地相对路径，如果需要 CDN 建议使用自己的仓库地址
    # new_edit_readme_md[0] = new_edit_readme_md[0].replace("./_media", "...")
        
    # 将新内容
    with open(os.path.join(os.getcwd(),"README.md"),'w') as load_f:
        load_f.write(new_edit_readme_md[0])
    

    mail_re = r'邮件内容区开始>([.\S\s]*)<邮件内容区结束'
    reResult = re.findall(mail_re, new_edit_readme_md[0])
    new_edit_readme_md[1] = reResult

    
    return new_edit_readme_md

# 将README.md复制到docs中

def cp_readme_md_to_docs():
    shutil.copyfile(os.path.join(os.getcwd(),"README.md"), os.path.join(os.getcwd(), "docs","README.md"))
    
def cp_media_to_docs():
    if os.path.exists(os.path.join(os.getcwd(), "docs","_media")):
        shutil.rmtree(os.path.join(os.getcwd(), "docs","_media"))	
    shutil.copytree(os.path.join(os.getcwd(),"_media"), os.path.join(os.getcwd(), "docs","_media"))

def save_email_result(reResult):
    if reResult:
        content = "\n".join(reResult)
        
        # 将 HTML 格式转换为 Markdown 格式
        # 1. 转换链接: 从 div 结构转换为 Markdown 列表项
        # 增加 \n 确保每个项目占一行
        content = re.sub(r"<div[^>]*>\s*<a href='([^']*)'[^>]*>(.*?)</a>\s*</div>", r"\n- [\2](\1)", content)
        
        # 2. 转换标题: <h2>TEXT</h2> -> ## TEXT
        content = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", content)
        
        # 3. 清理多余的 HTML 标签
        content = re.sub(r"<br\s*/?>", r"\n", content)
        
        # 4. 移除多余的空行，保持整洁
        content = re.sub(r"\n{3,}", r"\n\n", content)
        
        # 写入 docs/email_result.md
        file_path = os.path.join(os.getcwd(), "docs", "email_result.md")
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("# 📧 邮件内容备份\n\n")
            f.write(f"> 生成时间: {datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(content)
        print(f"邮件结果已写入 {file_path}")

def get_email_list():
    email_list = []
    with open(os.path.join(os.getcwd(),"tasks.json"),'r') as load_f:
        load_dic = json.load(load_f)
        for task in load_dic["tasks"]:
            email_list.append(task["email"])
    return email_list

def parse_readme_rss(edit_readme_md):
    """
    从 EditREADME.md 内容中解析 RSS 订阅信息
    返回 RSS 信息列表
    """
    opml_info_text_list = re.findall(r'.*\{\{latest_content\}\}.*\[订阅地址\]\(.*\).*', edit_readme_md)
    rss_list = []

    for opml_info_text in opml_info_text_list:
        opml_info_text_format_data = re.search(r'\|(.*)\|(.*)\|(.*)\|(.*)\|.*\[订阅地址\]\((.*)\).*\|', opml_info_text)

        if not opml_info_text_format_data:
            continue

        title = opml_info_text_format_data.group(2).strip()
        description = opml_info_text_format_data.group(3).strip()
        xml_url = opml_info_text_format_data.group(5).strip()

        # 提取网站主页 URL（从 RSS URL 中提取）
        parsed = urlparse(xml_url)
        html_url = f"{parsed.scheme}://{parsed.netloc}"

        rss_info = {
            "title": title,
            "description": description,
            "htmlUrl": html_url,
            "xmlUrl": xml_url
        }

        rss_list.append(rss_info)

    return rss_list

# 创建opml订阅文件

def create_opml(edit_readme_md):
    """
    从 EditREADME.md 内容中生成 OPML 订阅文件（v1 和 v2 版本）
    使用共享的 parse_readme_rss() 函数避免代码重复
    """
    # 使用共享的解析函数
    rss_list = parse_readme_rss(edit_readme_md)

    # 使用 list.append() + join() 优化字符串拼接
    result_v2_lines = []
    result_v1_lines = []

    for rss_info in rss_list:
        # v2 版本：完整信息
        opml_info_text = '<outline  text="{text}" description="{description}" htmlUrl="{htmlUrl}" language="unknown" title="{title}" type="rss" version="RSS2" xmlUrl="{xmlUrl}"/>'
        opml_info_text = opml_info_text.format(
            text=rss_info["title"],
            description=rss_info["description"],
            htmlUrl=rss_info["htmlUrl"],  # 优化：使用网站主页 URL
            title=rss_info["title"],
            xmlUrl=rss_info["xmlUrl"]
        )
        result_v2_lines.append(opml_info_text)

        # v1 版本：简化格式，也包含时间戳
        opml_info_text_v1 = '      <outline text="{title}" title="{title}" type="rss"  \n            xmlUrl="{xmlUrl}" htmlUrl="{htmlUrl}"/>'
        opml_info_text_v1 = opml_info_text_v1.format(
            htmlUrl=rss_info["htmlUrl"],  # 优化：使用网站主页 URL
            title=rss_info["title"],
            xmlUrl=rss_info["xmlUrl"]
        )
        result_v1_lines.append(opml_info_text_v1)

        # 打印调试信息
        print('##', rss_info["title"])
        print(rss_info["description"])
        print(rss_info["xmlUrl"])

    # 使用 join() 替代字符串拼接
    result_v2 = "\n".join(result_v2_lines) + "\n"
    result_v1 = "\n".join(result_v1_lines) + "\n"

    # 生成 v2 版本 OPML 文件
    with open(os.path.join(os.getcwd(), "rss-template-v2.txt"), 'r') as load_f:
        rss_subscription_list_template = load_f.read()
        GMT_FORMAT = '%a, %d %b %Y %H:%M:%S GMT'
        date_created = datetime.utcnow().strftime(GMT_FORMAT)
        date_modified = datetime.utcnow().strftime(GMT_FORMAT)
        rss_subscription_list = rss_subscription_list_template.format(
            result=result_v2,
            date_created=date_created,
            date_modified=date_modified
        )

    with open(os.path.join(os.getcwd(), "subscription_list_v2.opml"), 'w') as load_f:
        load_f.write(rss_subscription_list)

    # 生成 v1 版本 OPML 文件（添加时间戳）
    with open(os.path.join(os.getcwd(), "rss-template-v1.txt"), 'r') as load_f:
        rss_subscription_list_template = load_f.read()
        GMT_FORMAT = '%a, %d %b %Y %H:%M:%S GMT'
        date_created = datetime.utcnow().strftime(GMT_FORMAT)
        # 检查模板是否支持 date_created 参数，如果不支持则不添加
        if "{date_created}" in rss_subscription_list_template:
            rss_subscription_list_v1 = rss_subscription_list_template.format(
                result=result_v1,
                date_created=date_created
            )
        else:
            rss_subscription_list_v1 = rss_subscription_list_template.format(result=result_v1)

    with open(os.path.join(os.getcwd(), "subscription_list_v1.opml"), 'w') as load_f:
        load_f.write(rss_subscription_list_v1)




        
    # print(result)

def create_json(edit_readme_md):
    """
    从 EditREADME.md 内容中提取 RSS 信息并生成 JSON 文件
    使用共享的 parse_readme_rss() 函数避免代码重复
    """
    result = {"rss_info": []}

    # 使用共享的解析函数
    rss_list = parse_readme_rss(edit_readme_md)

    for rss_info in rss_list:
        result["rss_info"].append({
            "title": rss_info["title"],
            "description": rss_info["description"],
            "xmlUrl": rss_info["xmlUrl"]
        })

    with open("./rss_info.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

def main():
    edit_readme_path = os.path.join(os.getcwd(), "EditREADME.md")
    md5_path = os.path.join(os.getcwd(), "EditREADME.md.md5")
    
    with open(edit_readme_path, 'r', encoding='utf-8') as f:
        edit_readme_md = f.read()
    
    curr_md5 = hashlib.md5(edit_readme_md.encode('utf-8')).hexdigest()
    
    old_md5 = ""
    if os.path.exists(md5_path):
        with open(md5_path, 'r') as f:
            old_md5 = f.read().strip()
            
    if curr_md5 != old_md5:
        print("EditREADME.md 已更改，重新生成 json 和 opml 文件")
        create_json(edit_readme_md)
        create_opml(edit_readme_md)
        with open(md5_path, 'w') as f:
            f.write(curr_md5)
    else:
        print("EditREADME.md 未更改，跳过生成 json 和 opml 文件")

    readme_md = replace_readme(edit_readme_md)
    content = markdown.markdown(readme_md[0], extensions=['tables', 'fenced_code'])
    cp_readme_md_to_docs()
    cp_media_to_docs()
    email_list = get_email_list()

    mail_re = r'邮件内容区开始>([.\S\s]*)<邮件内容区结束'
    reResult = re.findall(mail_re, readme_md[0])

    # 将邮件内容写入 docs/email_result.md
    save_email_result(reResult)

    try:
        send_mail(email_list, "我的个人 RSS 订阅更新", reResult)
    except Exception as e:
        print("==邮件设信息置错误===》》", e)


if __name__ == "__main__":
    main()