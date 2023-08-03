from urllib.parse import urljoin, urlsplit

from flask import request

from utils.util import *

from .shares import Shares, conf, logger
from .threadlocal import ZmirrorThreadLocal


class RequestRewriter:
    def __init__(self, parse: ZmirrorThreadLocal, shares: Shares) -> None:
        self.parse = parse
        self.G = shares

    def decode_mirror_url(self, mirror_url: str = None) -> dict:
        """
        解析镜像url(可能含有extdomains), 并提取出原始url信息
        可以不是完整的url, 只需要有 path 部分即可(query_string也可以有)
        若参数留空, 则使用当前用户正在请求的url
        支持json (处理 \/ 和 \. 的转义)

        :rtype: dict[str, Union[str, bool]]
        :return: {'domain':str, 'is_https':bool, 'path':str, 'path_query':str}
        """
        _is_escaped_dot = False
        _is_escaped_slash = False
        result = {}

        if mirror_url is None:
            mirror_path_query = self.G.extract_path_and_query()  # type: str
        else:
            if r"\/" in mirror_url:  # 如果 \/ 在url中, 先反转义, 处理完后再转义回来
                _is_escaped_slash = True
                mirror_url = mirror_url.replace(r"\/", "/")

            if r"\." in mirror_url:  # 如果 \. 在url中, 先反转义, 处理完后再转义回来
                _is_escaped_dot = True
                mirror_url = mirror_url.replace(r"\.", ".")

            mirror_path_query = self.extract_path_and_query(mirror_url)  # type: str

        if mirror_path_query[:12] == "/extdomains/":
            # 12 == len('/extdomains/')
            split = urlsplit("//" + mirror_path_query[12:].lstrip("/"))

            real_domain = split.netloc
            real_path_query = (split.path or "/") + (("?" + split.query) if split.query else "")

            if real_domain[:6] == "https-":
                # 如果显式指定了 /extdomains/https-域名 形式(为了兼容老版本)的, 那么使用https
                real_domain = real_domain[6:]
                _is_https = True
            else:
                # 如果是 /extdomains/域名 形式, 没有 "https-" 那么根据域名判断是否使用HTTPS
                _is_https = self.G.is_target_domain_use_https(real_domain)

            # real_path_query = self.client_requests_text_rewrite(real_path_query)

            if _is_escaped_dot:
                real_path_query = real_path_query.replace(".", r"\.")
            if _is_escaped_slash:
                real_path_query = esc_str(real_path_query)
            result["domain"] = real_domain
            result["is_https"] = _is_https
            result["path_query"] = real_path_query
            result["path"] = urlsplit(real_path_query).path
            return result

        # input_path_query = self.client_requests_text_rewrite(input_path_query)

        if _is_escaped_dot:
            mirror_path_query = mirror_path_query.replace(".", r"\.")
        if _is_escaped_slash:
            mirror_path_query = esc_str(mirror_path_query)
        result["domain"] = conf.target_domain
        result["is_https"] = conf.target_scheme == "https://"
        result["path_query"] = mirror_path_query
        result["path"] = urlsplit(mirror_path_query).path
        return result

    def assemble_remote_url(self):
        """
        组装目标服务器URL, 即生成 parse.remote_url 的值
        :rtype: str
        """
        if self.parse.is_external_domain:
            # 请求的是外部域名 (external domains)
            scheme = "https://" if self.parse.is_https else "http://"
            return urljoin(scheme + self.parse.remote_domain, self.parse.remote_path_query)
        else:
            # 请求的是主域名及可以被当做(alias)主域名的域名
            return urljoin(conf.target_scheme + conf.target_domain, self.parse.remote_path_query)

    def assemle_parse(self):
        """将用户请求的URL解析为对应的目标服务器URL"""
        remote_url_info = self.decode_mirror_url()
        self.parse.remote_domain = remote_url_info["domain"]  # type: str
        self.parse.is_https = remote_url_info["is_https"]  # type: bool
        self.parse.remote_path = remote_url_info["path"]  # type: str
        self.parse.remote_path_query = remote_url_info["path_query"]  # type: str
        self.parse.is_external_domain = self.G.is_external_domain(self.parse.remote_domain)
        self.parse.remote_url = self.assemble_remote_url()  # type: str
        self.parse.url_no_scheme = self.parse.remote_url[self.parse.remote_url.find("//") + 2 :]  # type: str

        # extract client header
        self.parse.client_header = self.extract_client_header()

        # 写入最近使用的域名
        self.G.recent_domains[self.parse.remote_domain] = True

        logger.debug(
            "after assemble_parse, url:",
            self.parse.remote_url,
            "   path_query:",
            self.parse.remote_path_query,
        )

    def extract_client_header(self):
        """
        Extract necessary client header, filter out some.

        对于浏览器请求头的策略是黑名单制, 在黑名单中的头会被剔除, 其余所有请求头都会被保留

        对于浏览器请求头, zmirror会移除掉其中的 host和content-length
        并重写其中的cookie头, 把里面可能存在的本站域名修改为远程服务器的域名

        :return: 重写后的请求头
        :rtype: dict
        """
        rewrited_headers = {}
        logger.debug("BrowserRequestHeaders:", request.headers)
        for head_name, head_value in request.headers:
            head_name_l = head_name.lower()  # requests的请求头是区分大小写的, 统一变为小写

            # ------------------ 特殊请求头的处理 -------------------
            if head_name_l in ("host", "content-length"):
                # 丢弃浏览器的这两个头, 会在zmirror请求时重新生成
                continue

            elif head_name_l == "content-type" and head_value == "":
                # 跳过请求头中的空白的 content-type
                #   在flask的request中, 无论浏览器实际有没有传入, content-type头会始终存在,
                #   如果它是空值, 则表示实际上没这个头, 则剔除掉
                continue

            elif head_name_l == "accept-encoding" and ("br" in head_value or "sdch" in head_value):
                # 一些现代浏览器支持sdch和br编码, 而requests不支持, 所以会剔除掉请求头中sdch和br编码的标记
                # For Firefox, they may send 'Accept-Encoding: gzip, deflate, br'
                # For Chrome, they may send 'Accept-Encoding: gzip, deflate, sdch, br'
                #   however, requests cannot decode the br encode, so we have to remove it from the request header.
                _str_buff = ""
                if "gzip" in head_value:
                    _str_buff += "gzip, "
                if "deflate" in head_value:
                    _str_buff += "deflate"
                if _str_buff:
                    rewrited_headers[head_name_l] = _str_buff
            else:
                # ------------------ 其他请求头的处理 -------------------
                # 对于其他的头, 进行一次内容重写后保留
                rewrited_headers[head_name_l] = self.G.client_requests_text_rewrite(head_value)

                # 移除掉 cookie 中的 zmirror_verify
                if head_name_l == "cookie":
                    rewrited_headers[head_name_l] = self.G.re_patterns["verify_header"].sub(
                        "",
                        rewrited_headers[head_name_l],
                    )

        logger.debug("FilteredBrowserRequestHeaders:", rewrited_headers)

        return rewrited_headers
