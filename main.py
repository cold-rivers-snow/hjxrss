import feedparser
import time
import os
import re
import pytz
from datetime import datetime
import yagmail
import requests
import markdown
import json
import shutil
import hashlib
from urllib.parse import urlparse
from multiprocessing import Pool,  Manager



def get_rss_info(feed_url, index, rss_info_list):
    result = {"result": []}
    request_success = False
    # 如果请求出错,则重新请求,最多五次
    for i in range(3):
        if(request_success == False):
            try:
                headers = {
                    # 设置用户代理头(为狼披上羊皮)
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36",
                    "Content-Encoding": "gzip"
                }
                # 三次分别设置8, 16, 24秒钟超时
                feed_url_content = requests.get(feed_url,  timeout= (i+1)*8 ,headers = headers).content
                feed = feedparser.parse(feed_url_content)
                feed_entries = feed["entries"]
                feed_entries_length = len(feed_entries)
                print("==feed_url=>>", feed_url, "==len=>>", feed_entries_length)
                for entrie in feed_entries[:]:
                    title = entrie["title"]
                    link = entrie["link"]
                    date = time.strftime("%Y-%m-%d", entrie["published_parsed"])

                    title = title.replace("\n", "")
                    title = title.replace("\r", "")

                    result["result"].append({
                        "title": title,
                        "link": link,
                        "date": date
                    })
                request_success = True
            except Exception as e:
                print(feed_url+"第+"+str(i)+"+次请求出错==>>",e)
                pass
        else:
            pass

    rss_info_list[index] = result["result"]
    print("本次爬取==》》", feed_url, "<<<===", index, result["result"])
    # 剩余数量
    remaining_amount = 0

    for tmp_rss_info_atom in rss_info_list:
        if(isinstance(tmp_rss_info_atom, int)):
            remaining_amount = remaining_amount + 1
            
    print("当前进度 | 剩余数量", remaining_amount, "已完成==>>", len(rss_info_list)-remaining_amount)
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
    print('初始化完毕==》', rss_info_list)

    

    # 创建一个最多开启8进程的进程池
    po = Pool(8)

    for index, before_info in enumerate(before_info_list):
        # 获取link
        link = re.findall(r'\[订阅地址\]\((.*)\)', before_info)[0]
        po.apply_async(get_rss_info,(link, index, rss_info_list))


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
        scheme_netloc_url = str(parse_result.scheme)+"://"+str(parse_result.netloc)
        latest_content = "[暂无法通过爬虫获取信息, 点击进入源网站主页]("+ scheme_netloc_url +")"

        # 加入到索引
        try:
            for rss_info_atom in rss_info:
                if (rss_info_atom["date"] == datetime.today().strftime("%Y-%m-%d")):
                    new_num = new_num + 1
                    if (new_num % 2) == 0:
                        current_date_news_index[0] = current_date_news_index[0] + "<div style='line-height:3;' ><a href='" + rss_info_atom["link"] + "' " + 'style="line-height:2;text-decoration:none;display:block;color:#584D49;">' + "🌈 ‣ " + rss_info_atom["title"] + " | 第" + str(new_num) +"篇" + "</a></div>"
                    else:
                        current_date_news_index[0] = current_date_news_index[0] + "<div style='line-height:3;background-color:#FAF6EA;' ><a href='" + rss_info_atom["link"] + "' " + 'style="line-height:2;text-decoration:none;display:block;color:#584D49;">' + "🌈 ‣ " + rss_info_atom["title"] + " | 第" + str(new_num) +"篇" + "</a></div>"

        except:
            print("An exception occurred")
        

            
        if(len(rss_info) > 0):
            rss_info[0]["title"] = rss_info[0]["title"].replace("|", "\\|")
            rss_info[0]["title"] = rss_info[0]["title"].replace("[", "\\[")
            rss_info[0]["title"] = rss_info[0]["title"].replace("]", "\\]")

            latest_content = "[" + "‣ " + rss_info[0]["title"] + ( " 🌈 " + rss_info[0]["date"] if (rss_info[0]["date"] == datetime.today().strftime("%Y-%m-%d")) else " | " + rss_info[0]["date"] ) +"](" + rss_info[0]["link"] +")"

        if(len(rss_info) > 1):
            rss_info[1]["title"] = rss_info[1]["title"].replace("|", "\\|")
            rss_info[1]["title"] = rss_info[1]["title"].replace("[", "\\[")
            rss_info[1]["title"] = rss_info[1]["title"].replace("]", "\\]")

            latest_content = latest_content + "<br/>[" + "‣ " +  rss_info[1]["title"] + ( " 🌈 " + rss_info[0]["date"] if (rss_info[0]["date"] == datetime.today().strftime("%Y-%m-%d")) else " | " + rss_info[0]["date"] ) +"](" + rss_info[1]["link"] +")"

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

def get_email_list():
    email_list = []
    with open(os.path.join(os.getcwd(),"tasks.json"),'r') as load_f:
        load_dic = json.load(load_f)
        for task in load_dic["tasks"]:
            email_list.append(task["email"])
    return email_list

# 创建opml订阅文件

def create_opml(edit_readme_md):

    result = "";
    result_v1 = "";

    # <outline text="CNET News.com" description="Tech news and business reports by CNET News.com. Focused on information technology, core topics include computers, hardware, software, networking, and Internet media." htmlUrl="http://news.com.com/" language="unknown" title="CNET News.com" type="rss" version="RSS2" xmlUrl="http://news.com.com/2547-1_3-0-5.xml"/>

    ## 将信息填充到opml_info_list
    opml_info_text_list =  re.findall(r'.*\{\{latest_content\}\}.*\[订阅地址\]\(.*\).*' ,edit_readme_md);

    for opml_info_text in opml_info_text_list:
        opml_info_text_format_data = re.search(r'\|(.*)\|(.*)\|(.*)\|(.*)\|.*\[订阅地址\]\((.*)\).*\|', opml_info_text)
        
        if not opml_info_text_format_data:
            continue

        print('##', opml_info_text_format_data.group(2).strip())
        print(opml_info_text_format_data.group(3).strip())
        print(opml_info_text_format_data.group(5).strip())
        
        opml_info = {}
        opml_info["text"] = opml_info_text_format_data.group(2).strip()
        opml_info["description"] = opml_info_text_format_data.group(3).strip()
        opml_info["htmlUrl"] = opml_info_text_format_data.group(5).strip()
        opml_info["title"] = opml_info_text_format_data.group(2).strip()
        opml_info["xmlUrl"] = opml_info_text_format_data.group(5).strip()

        # print('opml_info==>>', opml_info);
        


        opml_info_text = '<outline  text="{text}" description="{description}" htmlUrl="{htmlUrl}" language="unknown" title="{title}" type="rss" version="RSS2" xmlUrl="{xmlUrl}"/>'

        opml_info_text_v1 = '      <outline text="{title}" title="{title}" type="rss"  \n            xmlUrl="{xmlUrl}" htmlUrl="{htmlUrl}"/>'

        opml_info_text =  opml_info_text.format(
            text=opml_info["text"], 
            description=opml_info["description"], 
            htmlUrl = opml_info["htmlUrl"],
            title=opml_info["title"],
            xmlUrl=opml_info["xmlUrl"]
        )

        opml_info_text_v1 =  opml_info_text_v1.format(
            htmlUrl = opml_info["htmlUrl"],
            title=opml_info["title"],
            xmlUrl=opml_info["xmlUrl"]
        )

        result = result + opml_info_text + "\n"

        result_v1 = result_v1 + opml_info_text_v1 + "\n"
    rss_subscription_list = "";
    with open(os.path.join(os.getcwd(),"rss-template-v2.txt"),'r') as load_f:
        rss_subscription_list_template = load_f.read();
        GMT_FORMAT = '%a, %d %b %Y %H:%M:%S GMT'
        date_created = datetime.utcnow().strftime(GMT_FORMAT);
        date_modified = datetime.utcnow().strftime(GMT_FORMAT);
        rss_subscription_list = rss_subscription_list_template.format(result=result, date_created=date_created, date_modified=date_modified);
        # print(rss_subscription_list);

    # 将内容写入
    with open(os.path.join(os.getcwd(),"subscription_list_v2.opml"),'w') as load_f:
        load_f.write(rss_subscription_list)

    rss_subscription_list_v1 = ""
    with open(os.path.join(os.getcwd(),"rss-template-v1.txt"),'r') as load_f:
        rss_subscription_list_template = load_f.read();
        rss_subscription_list_v1 = rss_subscription_list_template.format(result=result_v1);
        # print(rss_subscription_list_v1);

    # 将内容写入
    with open(os.path.join(os.getcwd(),"subscription_list_v1.opml"),'w') as load_f:
        load_f.write(rss_subscription_list_v1)




        
    # print(result)

def create_json(edit_readme_md):
    result = {"rss_info": []}
    ## 将信息填充到opml_info_list
    opml_info_text_list =  re.findall(r'.*\{\{latest_content\}\}.*\[订阅地址\]\(.*\).*' ,edit_readme_md);
    for opml_info_text in opml_info_text_list:
        opml_info_text_format_data = re.search(r'\|(.*)\|(.*)\|(.*)\|(.*)\|.*\[订阅地址\]\((.*)\).*\|', opml_info_text)
        if opml_info_text_format_data:
            opml_info = {}
            opml_info["description"] = opml_info_text_format_data.group(3).strip()
            opml_info["title"] = opml_info_text_format_data.group(2).strip()
            opml_info["xmlUrl"] = opml_info_text_format_data.group(5).strip()
            result["rss_info"].append(opml_info)
    with open("./rss_info.json","w", encoding="utf-8") as f:
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

    try:
        send_mail(email_list, "我的个人 RSS 订阅更新", reResult)
    except Exception as e:
        print("==邮件设信息置错误===》》", e)


if __name__ == "__main__":
    main()