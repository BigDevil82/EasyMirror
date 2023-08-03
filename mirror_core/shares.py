import re
import traceback
from collections import Counter
from urllib.parse import urlsplit

from flask import request

from configuration import Config
from utils.ColorfulPyPrint import ColorfulPrinter
from utils.util import current_line_number, get_group

from .threadlocal import ZmirrorThreadLocal

conf = Config(conf_path="config.py")
logger = ColorfulPrinter(conf.verbose_level)


class Shares:
    """
    this class is used to share some global variables between different modules
    and contains some commonly used functions
    """

    def __init__(self) -> None:
        self.logger = logger
        self.recent_domains = {}  # type: dict[str, bool]
        self.conf = conf

        # do some preparation
        self.prepare()

    def prepare(self):
        self.__precompile_regex()

        if conf.custom_text_rewriter_enable:
            try:
                from custom_func import custom_response_text_rewriter

                self.custom_response_text_rewriter = custom_response_text_rewriter
            except:
                logger.error(
                    "Cannot import custom_response_text_rewriter custom_func.py, `custom_text_rewriter` is now disabled(if it was enabled)"
                )
                conf.custom_text_rewriter_enable = False

        if conf.local_cache_enable:
            try:
                from .cache_system import FileCache, get_expire_from_mime

                self.cache = FileCache()
                self.get_expire_from_mime = get_expire_from_mime
            except:  # coverage: exclude
                traceback.print_exc()
                logger.error("Can Not Create Local File Cache, local file cache is disabled automatically.")
                conf.local_cache_enable = False

    def is_external_domain(self, domain):
        """
        check if a domain is external domain,
        all domains not in target_domain_alias are considered as external domain
        """
        return domain not in conf.target_domain_alias

    def __precompile_regex(self) -> dict[str, re.Pattern]:
        """
        precomile some commonly used regex patterns
        """
        # 1. 冒号(colon :)可能的值为:
        #    : %3A %253A  完整列表见 tests.TestRegex.REGEX_POSSIBLE_COLON
        REGEX_COLON = r"""(?::|%(?:25)?3[Aa])"""
        # 2. 斜线(slash /)可能的值为(包括大小写):
        # 完整列表见 tests.TestRegex.REGEX_POSSIBLE_COLON
        #    / \/ \\/ \\\(N个反斜线)/ %2F %5C%2F %5C%5C(N个5C)%2F %255C%252F %255C%255C%252F \x2F
        REGEX_SLASH = r"""(?:\\*(?:/|x2[Ff])|%(?:(?:25)?5[Cc]%)*(?:25)?2[Ff])"""
        # 3. 引号 可能值的完整列表见 tests.TestRegex.REGEX_POSSIBLE_QUOTE
        # " ' \\(可能有N个反斜线)' \\(可能有N个反斜线)"
        # %22 %27 %5C(可能N个5C)%22 %5C(可能N个5C)%27
        # %2522 %2527 %255C%2522 %255C%2527
        # &quot;
        REGEX_QUOTE = r"""(?:\\*["']|%(?:(?:25)?5[Cc]%)*2(?:52)?[27]|&quot;)"""

        # 代表本镜像域名的正则
        if conf.my_port is not None:
            REGEX_MY_HOST_NAME = (
                r"(?:"
                + re.escape(conf.my_host_name_with_port)
                + REGEX_COLON
                + re.escape(str(conf.my_port))
                + r"|"
                + re.escape(conf.my_host_name_with_port)
                + r")"
            )
        else:
            REGEX_MY_HOST_NAME = re.escape(conf.my_host_name)

        # Advanced url rewriter, see function response_text_rewrite()
        # #### 这个正则表达式是整个程序的最核心的部分, 它的作用是从 html/css/js 中提取出长得类似于url的东西 ####
        # 如果需要阅读这个表达式, 请一定要在IDE(如PyCharm)的正则高亮下阅读
        # 这个正则并不保证匹配到的东西一定是url, 在 regex_url_reassemble() 中会进行进一步验证是否是url
        regex_adv_url_pattern = re.compile(
            # 前缀, 必须有  'action='(表单) 'href='(链接) 'src=' 'url('(css) '@import'(css) '":'(js/json, "key":"value")
            # \s 表示空白字符,如空格tab
            r"""(?P<prefix>\b(?:(?:src|href|action)\s*=|url\s*\(|@import\s*|"\s*:)\s*)"""
            +  # prefix, eg: src=
            # 左边引号, 可选 (因为url()允许没有引号). 如果是url以外的, 必须有引号且左右相等(在重写函数中判断, 写在正则里可读性太差)
            r"""(?P<quote_left>["'])?""" +  # quote  "'
            # 域名和协议头, 可选. http:// https:// // http:\/\/ (json) https:\/\/ (json) \/\/ (json)
            r"""(?P<domain_and_scheme>(?P<scheme>(?:https?:)?\\?/\\?/)(?P<domain>(?:[-a-z0-9]+\.)+[a-z]+(?P<port>:\d{1,5})?))?"""
            +
            # url路径, 含参数 可选
            r"""(?P<path>[^\s;+$?#'"\{}]*?""" +  # full path(with query string)  /foo/bar.js?love=luciaZ
            # 查询字符串, 可选
            r"""(?P<query_string>\?[^\s?#'"]*?)?""" + ")" +  # query string  ?love=luciaZ
            # 右引号(可以是右括弧), 必须
            r"""(?P<quote_right>["')])(?P<right_suffix>\W)""",  # right quote  "'
            flags=re.IGNORECASE,
        )

        # 用于匹配响应文本中的url(不含路径和query param)的正则表达式
        # 包含以下捕获组：
        #     scheme: http(s):
        #     scheme_slash: // or /
        #     quote: " or '
        #     domain: target.domain
        #     suffix_slash: // or / or None

        # 统计各个顶级域名(tld)出现的频率, 并且按照出现频率降序排列, 有助于提升正则效率
        tld_freq = Counter(re.escape(x.split(".")[-1]) for x in conf.allowed_domains)
        all_remote_tld = sorted(list(tld_freq.keys()), key=lambda tld: tld_freq[tld], reverse=True)
        re_all_remote_tld = "(?:" + "|".join(all_remote_tld) + ")"

        re_scheme = r"""(?:https?(?P<colon>{REGEX_COLON}))?""".format(
            REGEX_COLON=REGEX_COLON
        )  # http(s): or nothing(note the ? at the end)
        re_scheme_slash = r"""(?P<scheme_slash>{SLASH})(?P=scheme_slash)""".format(SLASH=REGEX_SLASH)  # //
        re_quote = r"""(?P<quote>{REGEX_QUOTE})""".format(REGEX_QUOTE=REGEX_QUOTE)
        re_domain = r"""(?P<domain>([a-zA-Z0-9-]+\.){1,5}%s)\b""" % re_all_remote_tld
        # explain: (?(name)yes-pattern|no-pattern)
        #  if the group with given name matched, then use yes-pattern, else use no-pattern, and if no-pattern is omitted, then use empty string
        re_suffix_slash = r"""(?P<suffix_slash>(?(scheme_slash)(?P=scheme_slash)|{SLASH}))?""".format(
            SLASH=REGEX_SLASH
        )  # suffix slash is optional(not the ? at the end)
        # right quote (if we have left quote)
        re_right_quote = r"""(?(quote)(?P=quote))"""

        regex_basic_url_pattern: re.Pattern = re.compile(
            f"(?:{re_scheme}{re_scheme_slash}|{re_quote}){re_domain}{re_suffix_slash}{re_right_quote}"
        )

        # Response Cookies Rewriter, see response_cookie_rewrite()
        regex_cookie_pattern = re.compile(r"\bdomain=(\.?([\w-]+\.)+\w+)\b", flags=re.IGNORECASE)
        regex_cookie_path_pattern = re.compile(r"(?P<prefix>[pP]ath)=(?P<path>[\w\._/-]+?;)")

        # Request Domains Rewriter, see client_requests_text_rewrite()
        # 该正则用于匹配类似于下面的东西
        #   [[[http(s):]//]www.mydomain.com/]extdomains/(https-)target.com
        # 兼容各种urlencode/escape
        #
        # 注意, 若想阅读下面的正则表达式, 请一定要在 Pycharm 的正则高亮下进行
        # 否则不对可能的头晕/恶心负责
        # 下面那个正则, 在组装以后的样子大概是这样的(已大幅简化):
        # 假设b.test.com是本机域名
        #   ((https?:/{2})?b\.test\.com/)?extdomains/(https-)?((?:[\w-]+\.)+\w+)\b
        #
        # 对应的 unittest 见 TestRegex.test__regex_request_rewriter_extdomains()
        regex_extdomains_pattern = re.compile(
            r"""(?P<domain_prefix>"""
            + (  # [[[http(s):]//]www.mydomain.com/]
                r"""(?P<scheme>"""
                + (  # [[http(s):]//]
                    (  # [http(s):]
                        r"""(?:https?(?P<colon>{REGEX_COLON}))?""".format(REGEX_COLON=REGEX_COLON)  # https?:
                    )
                    + r"""(?P<scheme_slash>%s)(?P=scheme_slash)""" % REGEX_SLASH  # //
                )
                + r""")?"""
                + REGEX_MY_HOST_NAME
                + r"""(?P<slash2>(?(scheme_slash)(?P=scheme_slash)|{REGEX_SLASH}))""".format(  # www.mydomain.com[:port] 本部分的正则在上面单独组装
                    REGEX_SLASH=REGEX_SLASH
                )  # # /
            )
            + r""")?"""
            + r"""extdomains(?(slash2)(?P=slash2)|{REGEX_SLASH})(?P<is_https>https-)?""".format(
                REGEX_SLASH=REGEX_SLASH
            )
            + r"""(?P<real_domain>(?:[\w-]+\.)+\w+)\b""",  # extdomains/(https-)  # target.com
            flags=re.IGNORECASE,
        )
        regex_main_domain_pattern = re.compile(REGEX_MY_HOST_NAME)

        # 用于移除掉cookie中类似于 zmirror_verify=75bf23086a541e1f; 的部分
        regex_zmirror_verify_header_pattern = re.compile(r"""zmirror_verify=[a-zA-Z0-9]+\b;? ?""")

        # assemble these regex patterns into a dict
        self.re_patterns: dict[str, re.Pattern] = {
            "basic_url": regex_basic_url_pattern,  # 用于匹配url的正则表达式, 不含路径和query param
            "url": regex_adv_url_pattern,
            "main_domain": regex_main_domain_pattern,
            "ext_domains": regex_extdomains_pattern,
            "cookie": regex_cookie_pattern,
            "cookie_path": regex_cookie_path_pattern,
            "verify_header": regex_zmirror_verify_header_pattern,
        }
        self.re_consts = {
            "COLON": REGEX_COLON,
            "SLASH": REGEX_SLASH,
            "QUOTE": REGEX_QUOTE,
        }

    def extract_path_and_query(self, full_url=None, no_query=False):
        """
        Convert http://foo.bar.com/aaa/p.html?x=y to /aaa/p.html?x=y

        Args:
         - no_query: bool, if True, will not include query string
         - full_url: str, the url to be processed, if None, will use current request url

        return: path and query string(if need) of the url
        """
        if full_url is None:
            full_url = request.url
        split = urlsplit(full_url)
        result = split.path or "/"
        if not no_query and split.query:
            result += "?" + split.query
        return result

    def encoding_detect(self, byte_content: bytes):
        """
        试图解析并返回二进制串的编码, 如果失败, 则返回 None
        :param byte_content: 待解码的二进制串
        :type byte_content: bytes
        :return: 编码类型或None
        :rtype: Union[str, None]
        """

        if conf.force_decode_with_charsets is not None:
            return conf.force_decode_with_charsets
        if conf.possible_charsets:
            for charset in conf.possible_charsets:
                try:
                    byte_content.decode(encoding=charset)
                except:
                    pass
                else:
                    return charset
        # if cchardet_available:  # detect the encoding using cchardet (if we have)
        #     return c_chardet(byte_content)["encoding"]

        return None

    def is_target_domain_use_https(self, domain):
        """请求目标域名时是否使用https"""
        if conf.force_https_domains == "NONE" or conf.force_https_domains is None:
            return False
        if conf.force_https_domains == "ALL":
            return True
        if domain in conf.force_https_domains:
            return True
        else:
            return False

    def client_requests_text_rewrite(self, raw_text):
        """
        Rewrite proxy domain to origin domain, extdomains supported.
        Also Support urlencoded url.
        This usually used in rewriting request params

        eg. http://foo.bar/extdomains/accounts.google.com to http://accounts.google.com
        eg2. foo.bar/foobar to www.google.com/foobar
        eg3. http%3a%2f%2fg.zju.tools%2fextdomains%2Faccounts.google.com%2f233
                to http%3a%2f%2faccounts.google.com%2f233

        :type raw_text: str
        :rtype: str
        """

        def replace_to_real_domain(match_obj: re.Match):
            scheme = get_group("scheme", match_obj)  # type: str
            colon = match_obj.group("colon")  # type: str
            scheme_slash = get_group("scheme_slash", match_obj)  # type: str
            _is_https = bool(get_group("is_https", match_obj))  # type: bool
            real_domain = match_obj.group("real_domain")  # type: str

            result = ""
            if scheme:
                if "http" in scheme:
                    if _is_https or self.is_target_domain_use_https(real_domain):
                        result += "https" + colon
                    else:
                        result += "http" + colon

                result += scheme_slash * 2

            result += real_domain

            return result

        # 使用一个复杂的正则进行替换, 这次替换以后, 理论上所有 extdomains 都会被剔除
        # 详见本文件顶部, regex_request_rewriter_extdomains 本体
        replaced = self.re_patterns["ext_domains"].sub(replace_to_real_domain, raw_text)

        if conf.developer_string_trace is not None and conf.developer_string_trace in replaced:
            # debug用代码, 对正常运行无任何作用
            logger.info(
                "StringTrace: appears client_requests_text_rewrite, code line no. ", current_line_number()
            )

        # 正则替换掉单独的, 不含 /extdomains/ 的主域名
        replaced = self.re_patterns["main_domain"].sub(conf.target_domain, replaced)

        # 为了保险起见, 再进行一次裸的替换
        replaced = replaced.replace(conf.my_host_name, conf.target_domain)

        # logger.debug("ClientRequestedUrl: ", raw_text, "<- Has Been Rewrited To ->", replaced)
        return replaced


class Base:
    def __init__(self, parse: ZmirrorThreadLocal, shares: Shares) -> None:
        self.parse = parse
        self.G = shares


__all__ = ["Shares", "Base", "logger", "conf"]
