from datetime import datetime
from functools import lru_cache
import inspect
import os
import traceback
import re
import pickle


def get_group(name, match_obj: re.Match, default=""):
    """return a blank string if the match group is None"""
    try:
        obj = match_obj.group(name)
    except:
        return default
    else:
        if obj is not None:
            return obj
        else:
            return default


def esc_str(s: str):
    """
    equivalent to s.replace("/",r"\/")
    :type s: str
    :rtype: str
    """
    return s.replace("/", r"\/")


def un_esc_str(s: str):
    """
    equivalent to s.replace(r"\\\\/","/")
    """
    return s.replace(r"\/", "/")


def html_escape(s: str, quote=True):
    """
    Replace special characters "&", "<" and ">" to HTML-safe sequences.
    If the optional flag quote is true (the default), the quotation mark
    characters, both double quote (") and single quote (') characters are also
    translated.
    """
    s = s.replace("&", "&amp;")  # Must be done first!
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    if quote:
        s = s.replace('"', "&quot;")
        s = s.replace("'", "&#x27;")
    return s


def current_line_number():
    """Returns the current line number in our program.
    :return: current line number
    :rtype: int
    """

    return inspect.currentframe().f_back.f_lineno


@lru_cache(maxsize=128)
def extract_mime_from_content_type(_content_type):
    """从content-type中提取出mime, 如 'text/html; encoding=utf-8' --> 'text/html'
    :rtype: str
    """
    c = _content_type.find(";")
    if c == -1:
        return _content_type.lower()
    else:
        return _content_type[:c].lower()


@lru_cache(maxsize=128)
def is_content_type_using_cdn(_content_type, mime_to_use_cdn):
    """根据content-type确定该资源是否使用CDN"""
    _mime = extract_mime_from_content_type(_content_type)
    if _mime in mime_to_use_cdn:
        # dbgprint(content_type, 'Should Use CDN')
        return _mime
    else:
        # dbgprint(content_type, 'Should NOT CDN')
        return False


@lru_cache(maxsize=64)
def guess_colon_from_slash(slash):
    """根据 slash(/) 的格式, 猜测最有可能与之搭配的 colon(:) 格式"""
    if "%" not in slash:
        return ":"  # slash没有转义, 直接原文
    elif "%25" in slash:
        # %252F %252f
        if "F" in slash:
            return "%253A"
        else:
            return "%253a"
    else:
        # %2F %2f
        if "F" in slash:
            return "%3A"
        else:
            return "%3a"


@lru_cache(maxsize=128)
def is_mime_streamable(mime):
    """
    根据content-type判断是否应该用stream模式传输(服务器下载的同时发送给用户)
     视频/音频/图片等二进制内容默认用stream模式传输
     :param mime: mime or content-type, eg: "plain/text; encoding=utf-8"
     :type mime: str
     :rtype: bool
    """
    steamed_mime_keywords = (
        "video",
        "audio",
        "binary",
        "octet-stream",
        "x-compress",
        "application/zip",
        "pdf",
        "msword",
        "powerpoint",
        "vnd.ms-excel",
        "image",  # v0.23.0+ image can use stream mode, too (experimental)
    )
    for streamed_keyword in steamed_mime_keywords:
        if streamed_keyword in mime:
            return True
    return False


@lru_cache(maxsize=128)
def is_mime_represents_text(input_mime, text_like_mime_keywords):
    """
    Determine whether an mime is text (eg: text/html: True, image/png: False)
    :param input_mime: str
    :return: bool
    """
    input_mime_l = input_mime.lower()
    for text_word in text_like_mime_keywords:
        if text_word in input_mime_l:
            return True
    return False


def inject_content(position, html, content):
    """
    将文本内容注入到html中
    详见 default_config.py 的 `Custom Content Injection` 部分
    :param position: 插入位置
    :type position: str
    :param html: 原始html
    :type html: str
    :param content: 等待插入的自定义文本内容
    :type content: str
    :return: 处理后的html
    :rtype: str
    """
    if position == "head_first":
        return inject_content_head_first(html, content)
    elif position == "head_last":
        return inject_content_head_last(html, content)
    else:  # coverage: exclude
        raise ValueError("Unknown Injection Position: {}".format(position))


def inject_content_head_first(html, content):
    """
    将文本内容插入到head中第一个现有<script>之前
    如果head中不存在<script>, 则加在</head>标签之前

    :type html: str
    :type content: str
    :rtype: str
    """
    head_end_pos = html.find("</head")  # 找到 </head> 标签结束的位置
    script_begin_pos = html.find("<script")  # 找到第一个 <script> 开始的地方

    if head_end_pos == -1:  # coverage: exclude
        # 如果没有 </head> 就不进行插入
        return html

    if script_begin_pos != -1 and script_begin_pos < head_end_pos:
        # 如果<head>中存在<script>标签, 则插入到第一个 <script> 标签之前
        return html[:script_begin_pos] + content + html[script_begin_pos:]

    else:
        # 如果<head>中 *不* 存在<script>标签, 则插入到 </head> 之前
        return html[:head_end_pos] + content + html[head_end_pos:]


def inject_content_head_last(html, content):
    """
    将文本内容插入到head的尾部

    :type html: str
    :type content: str
    :rtype: str
    """
    head_end_pos = html.find("</head")  # 找到 </head> 标签结束的位置

    if head_end_pos == -1:
        # 如果没有 </head> 就不进行插入
        return html

    return html[:head_end_pos] + content + html[head_end_pos:]


def dump_zmirror_snapshot(parse, request, root="error_dump", msg=None, our_response=None):
    """
    dump当前状态到文件
    :param root: 文件夹名
    :type root: str
    :param our_response: Flask返回对象, 可选
    :type our_response: Response
    :param msg: 额外的信息
    :type msg: str
    :return: dump下来的文件绝对路径
    :rtype: Union[str, None]
    """

    try:
        if not os.path.exists(root(root)):
            os.mkdir(root(root))
        _time_str = datetime.now().strftime("snapshot_%Y-%m-%d_%H-%M-%S")

        import config

        snapshot = {
            "time": datetime.now(),
            "parse": parse.dump(),
            "msg": msg,
            "traceback": traceback.format_exc(),
            "config": attributes(config, to_dict=True),
            "FlaskRequest": attributes(request, to_dict=True),
        }
        if our_response is not None:
            our_response.freeze()
        snapshot["OurResponse"] = our_response

        dump_file_path = os.path.abspath(os.path.join(root(root), _time_str + ".dump"))

        with open(dump_file_path, "wb") as fp:
            pickle.dump(snapshot, fp, pickle.HIGHEST_PROTOCOL)
        return dump_file_path
    except:
        return None


def attributes(var, to_dict=False, max_len=1024):
    output = {} if to_dict else ""
    for name in dir(var):
        if name[0] != "_" and name[-2:] != "__":
            continue

        value = str(getattr(var, name))
        if max_len:
            length = len(value)
            if length > max_len:
                value = value[:max_len] + "....(total:{})".format(length)

        if to_dict:
            output[name] = value
        else:
            output += strx(name, ":", value, "\n")
    return output


def strx(*args):
    """
    concat all args to a string with space
    :return: str
    """
    output = ""
    for arg in args:
        output += str(arg) + " "
    output.rstrip(" ")
    return output
