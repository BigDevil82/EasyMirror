from collections import Counter
import queue
import threading
from time import process_time, time
from urllib.parse import urljoin, urlsplit

from flask import Response, request
from requests import Response as requests_Response

from CONSTS import __VERSION__ as pkg_version
from shares import Shares, logger, conf
from threadlocal import ZmirrorThreadLocal
from utils.util import *


class ResponseRewriter:
    def __init__(self, parse: ZmirrorThreadLocal, shares: Shares) -> None:
        self.parse = parse
        self.G = shares

    def parse_remote_response(self):
        """
        处理远程服务器的响应，包括：
            1. 提取响应的mime
            2. 判断是否以stream(流)式传输响应内容
            3. 提取cache control header, 判断是否允许缓存
        """
        # extract response's mime to thread local var
        self.parse.content_type = self.parse.remote_response.headers.get("Content-Type", "")
        self.parse.mime = extract_mime_from_content_type(self.parse.content_type)

        # 是否以stream(流)式传输响应内容
        #   关于flask的stream传输, 请看官方文档 http://flask.pocoo.org/docs/0.11/patterns/streaming/
        #   如果启用stream传输, 并且响应的mime在启用stream的类型中, 就使用stream传输
        #   关于stream模式的更多内容, 请看 config_default.py 中 `enable_stream_content_transfer` 的部分
        #   如果你正在用PyCharm, 只需要按住Ctrl然后点下面↓↓这个变量↓↓就行
        self.parse.streame_our_response = conf.stream_transfer_enable and is_mime_streamable(self.parse.mime)

        # extract cache control header, if not cache, we should disable local cache
        self.parse.cache_control = self.parse.remote_response.headers.get("Cache-Control", "")
        # 判断响应是否允许缓存. 使用相当保守的缓存策略
        self.parse.cacheable = (
            "no-store" not in self.parse.cache_control
            and "must-revalidate" not in self.parse.cache_control
            and "max-age=0" not in self.parse.cache_control
            and "private" not in self.parse.cache_control
            and self.parse.remote_response.request.method == "GET"
            and self.parse.remote_response.status_code == 200
        )

        logger.debug(
            "Response Content-Type:",
            self.parse.content_type,
            "IsStreamable:",
            self.parse.streame_our_response,
            "cacheable:",
            self.parse.cacheable,
            "Line",
            current_line_number(),
            v=4,
        )

    def url_regex_pattern(self):
        """
        用于匹配响应文本中的url的正则表达式
        包含以下捕获组：
            scheme: http(s):
            scheme_slash: // or /
            quote: " or '
            domain: target.domain
            suffix_slash: // or / or None
        :rtype: re.Pattern
        """

        # 统计各个后缀出现的频率, 并且按照出现频率降序排列, 有助于提升正则效率
        tld_freq = Counter(re.escape(x.split(".")[-1]) for x in conf.allowed_domains)
        all_remote_tld = sorted(list(tld_freq.keys()), key=lambda tld: tld_freq[tld], reverse=True)
        re_all_remote_tld = "(?:" + "|".join(all_remote_tld) + ")"

        re_scheme = r"""(?:https?(?P<colon>{REGEX_COLON}))?""".format(
            REGEX_COLON=self.G.re_consts["COLON"]
        )  # http(s): or nothing(note the ? at the end)
        re_scheme_slash = r"""(?P<scheme_slash>{SLASH})(?P=scheme_slash)""".format(
            SLASH=self.G.re_consts["SLASH"]
        )  # //
        re_quote = r"""(?P<quote>{REGEX_QUOTE})""".format(REGEX_QUOTE=self.G.re_consts["QUOTE"])
        re_domain = r"""(?P<domain>([a-zA-Z0-9-]+\.){1,5}%s)\b""" % re_all_remote_tld
        # explain: (?(name)yes-pattern|no-pattern)
        #  if the group with given name matched, then use yes-pattern, else use no-pattern, and if no-pattern is omitted, then use empty string
        re_suffix_slash = r"""(?P<suffix_slash>(?(scheme_slash)(?P=scheme_slash)|{SLASH}))?""".format(
            self.G.re_consts["SLASH"]
        )  # suffix slash is optional(not the ? at the end)
        # right quote (if we have left quote)
        re_right_quote = r"""(?(quote)(?P=quote))"""

        re_whole_url: re.Pattern = re.compile(
            f"(?:{re_scheme}{re_scheme_slash}|{re_quote}){re_domain}{re_suffix_slash}{re_right_quote}"
        )

        return re_whole_url

        return re.compile(
            r"""(?:"""
            + (  # [[http(s):]//] or [\?["']] or %27 %22 or &quot;
                r"""(?P<scheme>"""
                + (  # [[http(s):]//]
                    (  # [http(s):]
                        r"""(?:https?(?P<colon>{REGEX_COLON}))?""".format(
                            REGEX_COLON=self.G.re_consts["COLON"]
                        )  # https?:
                    )
                    + r"""(?P<scheme_slash>%s)(?P=scheme_slash)""" % self.G.re_consts["SLASH"]  # //
                )
                + r""")"""
                + r"""|"""
                +
                # [\?["']] or %27 %22 or &quot
                r"""(?P<quote>{REGEX_QUOTE})""".format(REGEX_QUOTE=self.G.re_consts["QUOTE"])
            )
            + r""")"""
            +
            # End prefix.
            # Begin domain
            r"""(?P<domain>([a-zA-Z0-9-]+\.){1,5}%s)\b""" % re_all_remote_tld
            +
            # Optional suffix slash
            # explain: (?(name)yes-pattern|no-pattern)
            #  if the group with given name matched, then use yes-pattern, else use no-pattern, and if no-pattern is omitted, then use empty string
            r"""(?P<suffix_slash>(?(scheme_slash)(?P=scheme_slash)|{SLASH}))?""".format(
                SLASH=self.G.re_consts["SLASH"]
            )
            +
            # right quote (if we have left quote)
            r"""(?(quote)(?P=quote))"""
        )

    def rewrite_remote_to_mirror_url(self, remote_resp):
        """
        将远程服务器响应文本中的url重写为镜像站的url
        :param text: 远程响应文本
        :type text: str
        :return: 重写后的响应文本
        :rtype: str
        """

        def to_mirror_url(m):
            remote_domain = get_group("domain", m)
            suffix_slash = get_group("suffix_slash", m)
            slash = get_group("scheme_slash", m) or suffix_slash or "/"
            colon = get_group("colon", m) or guess_colon_from_slash(slash)
            quote = get_group("quote", m)

            _my_host_name = conf.my_host_name.replace(":", colon) if conf.my_port else conf.my_host_name

            if remote_domain in conf.target_domain_alias:
                # 主域名
                core = _my_host_name + suffix_slash
            else:
                # 外部域名
                core = _my_host_name + slash + "extdomains" + slash + remote_domain + suffix_slash

            if quote:  # no scheme "target.domain"
                return quote + core + quote
            else:  # http(s)://target.domain  //target.domain
                if get_group("colon", m):  # http(s)://target.domain
                    return conf.my_scheme.replace(":", colon).replace("/", slash) + core
                else:  # //target.domain
                    return slash * 2 + core

        return self.url_regex_pattern.sub(to_mirror_url, remote_resp)

    def regex_url_reassemble(self, match_obj: re.Match):
        """
        Reassemble url parts split by the regex.
        :param match_obj: re.Match object matched by G.re_patterns["url"]
        :return: re assembled url string (included prefix(url= etc..) and suffix.)
        :rtype: str
        """

        prefix = get_group("prefix", match_obj)
        quote_left = get_group("quote_left", match_obj)
        quote_right = get_group("quote_right", match_obj)
        scheme = get_group("scheme", match_obj)
        match_domain = get_group("domain", match_obj)
        path = get_group("path", match_obj)
        suffix = get_group("right_suffix", match_obj)

        whole_match_string = match_obj.group()

        if r"\/" in path or r"\/" in scheme:
            require_slash_escape = True
            path = un_esc_str(path)
        else:
            require_slash_escape = False

        # path must be not blank
        # if (
        #     not path  # path is blank
        #     # only url(something) and @import are allowed to be unquoted
        #     or ("url" not in prefix and "import" not in prefix)
        #     and (not quote_left or quote_right == ")")
        #     # for "key":"value" type replace, we must have at least one '/' in url path (for the value to be regard as url)
        #     or (":" in prefix and "/" not in path)
        #     # if we have quote_left, it must equals to the right
        #     or (quote_left and quote_left != quote_right)
        #     # in javascript, those 'path' contains one or only two slash, should not be rewrited (for potential error)
        #     # or (self.parse.mime == 'application/javascript' and path.count('/') < 2)
        #     # in javascript, we only rewrite those with explicit scheme ones.
        #     # v0.21.10+ in "key":"value" format, we should ignore those path without scheme
        #     or (not scheme and ("javascript" in self.parse.mime or '"' in prefix))
        # ):
        #     logger.debug("returned_un_touch", whole_match_string, v=5)
        #     return whole_match_string

        ## rewrite the above code to make it more readable
        # If path is blank or only "url" and "import" are allowed to be unquoted and the quotes are balanced, return the original string
        if not path or (
            "url" not in prefix and "import" not in prefix and (not quote_left or quote_right == ")")
        ):
            return whole_match_string

        # If the "key":"value" type replace doesn't have at least one '/' in the url path or the quotes are unbalanced, return the original string
        if ":" in prefix and "/" not in path or (quote_left and quote_left != quote_right):
            return whole_match_string

        # If we're in JavaScript and the url does not have an explicit scheme, return the original string
        if not scheme and ("javascript" in self.parse.mime or '"' in prefix):
            return whole_match_string

        # # v0.19.0+ Automatic Domains Whitelist (Experimental)
        # if conf.automatic_domains_whitelist_enable:
        #     self(match_domain) todo

        # logger.debug(match_obj.groups(), v=5)

        domain = match_domain or self.parse.remote_domain
        # logger.debug('rewrite match_obj:', match_obj, 'domain:', domain, v=5)

        # skip if the domain are not in our proxy list
        if domain not in conf.allowed_domains:
            # logger.debug('return untouched because domain not match', domain, whole_match_string, v=5)
            return whole_match_string  # return raw, do not change

        # this resource's absolute url path to the domain root.
        # logger.debug('match path', path, "remote path", self.parse.remote_path, v=5)
        path = urljoin(self.parse.remote_path, path)  # type: str

        if not path.startswith("/"):
            # 当整合后的path不以 / 开头时, 如果当前是主域名, 则不处理, 如果是外部域名则加上 / 前缀
            path = "/" + path

        if domain in conf.external_domains:
            url_no_scheme = urljoin(domain, path)
            path = "/extdomains/" + url_no_scheme

        if not scheme:
            scheme_domain = ""
        elif "http" not in scheme:
            scheme_domain = "//" + conf.my_host_name
        else:
            scheme_domain = conf.my_scheme_and_host

        full_url = urljoin(scheme_domain, path)

        if require_slash_escape:
            full_url = esc_str(full_url)

        # reassemble!
        # prefix: src=  quote_left: "
        # path: /extdomains/target.com/foo/bar.js?love=luciaZ
        reassembled = prefix + quote_left + full_url + quote_right + suffix

        # logger.debug('---------------------', v=5)
        return reassembled

    def response_text_rewrite(self, resp_text):
        """
        rewrite urls in text-like content (html,css,js)
        :type resp_text: str
        :rtype: str
        """

        # v0.9.2+: advanced url rewrite engine
        resp_text = self.G.re_patterns["url"].sub(self.regex_url_reassemble, resp_text)

        if conf.developer_string_trace is not None and conf.developer_string_trace in resp_text:
            # debug用代码, 对正常运行无任何作用
            logger.info("StringTrace: appears after advanced rewrite, code line no. ", current_line_number())

        # v0.28.0 实验性功能, 在v0.28.3后默认启用
        resp_text = self.rewrite_remote_to_mirror_url(resp_text)

        if conf.developer_string_trace is not None and conf.developer_string_trace in resp_text:
            # debug用代码, 对正常运行无任何作用
            logger.info(
                "StringTrace: appears after basic mirrorlization, code line no. ", current_line_number()
            )

        # # for cookies set string (in js) replace
        # # eg: ".twitter.com" --> "foo.com"
        # resp_text = resp_text.replace('".' + target_domain_root + '"', '"' + my_host_name_no_port + '"')
        # resp_text = resp_text.replace("'." + target_domain_root + "'", "'" + my_host_name_no_port + "'")
        # resp_text = resp_text.replace("domain=." + target_domain_root, "domain=" + my_host_name_no_port)
        # resp_text = resp_text.replace('"' + target_domain_root + '"', '"' + my_host_name_no_port + '"')
        # resp_text = resp_text.replace("'" + target_domain_root + "'", "'" + my_host_name_no_port + "'")

        # if developer_string_trace is not None and developer_string_trace in resp_text:
        #     # debug用代码, 对正常运行无任何作用
        #     infoprint(
        #         "StringTrace: appears after js cookies string rewrite, code line no. ", current_line_number()
        #     )

        # resp_text = resp_text.replace('lang="zh-Hans"', '', 1)
        return resp_text

    def response_content_rewrite(self):
        """
        Rewrite requests response's content's url. Auto skip binary (based on MIME).
        :return: Tuple[bytes, float]
        """

        _start_time = time()
        _content = self.parse.remote_response.content
        req_time_body = time() - _start_time

        if not is_mime_represents_text(self.parse.mime, conf.text_like_mime_types):
            # simply don't touch binary response content
            logger.debug("Binary", self.parse.content_type)
            return _content, req_time_body

        # Do text rewrite if remote response is text-like (html, css, js, xml, etc..)
        logger.debug(
            "Text-like", self.parse.content_type, self.parse.remote_response.text[:15], _content[:15]
        )
        # 自己进行编码检测, 因为 requests 内置的编码检测在天朝GBK面前非常弱鸡
        encoding = self.G.encoding_detect(self.parse.remote_response.content)
        if encoding is not None:
            self.parse.remote_response.encoding = encoding

        # simply copy the raw text, for custom rewriter function first.
        resp_text = self.parse.remote_response.text

        if conf.developer_string_trace is not None and conf.developer_string_trace in resp_text:
            # debug用代码, 对正常运行无任何作用
            logger.info(
                "StringTrace: appears in the RAW remote response text, code line no. ", current_line_number()
            )

        # try to apply custom rewrite function
        if conf.custom_text_rewriter_enable:
            resp_text2 = self.G.custom_response_text_rewriter(
                resp_text, self.parse.mime, self.parse.remote_url
            )
            if isinstance(resp_text2, str):
                resp_text = resp_text2
            elif isinstance(resp_text2, tuple) or isinstance(resp_text2, list):
                resp_text, is_skip_builtin_rewrite = resp_text2
                if is_skip_builtin_rewrite:
                    logger.info("Skip_builtin_rewrite", request.url)
                    return resp_text.encode(encoding="utf-8"), req_time_body

            if conf.developer_string_trace is not None and conf.developer_string_trace in resp_text:
                # debug用代码, 对正常运行无任何作用
                logger.info(
                    "StringTrace: appears after custom text rewrite, code line no. ", current_line_number()
                )

        # then do the normal rewrites
        resp_text = self.response_text_rewrite(resp_text)

        if conf.developer_string_trace is not None and conf.developer_string_trace in resp_text:
            # debug用代码, 对正常运行无任何作用
            logger.info("StringTrace: appears after builtin rewrite, code line no. ", current_line_number())

        # 在页面中插入自定义内容
        # 详见 default_config.py 的 `Custom Content Injection` 部分
        if conf.custom_inject_content and self.parse.mime == "text/html":
            for position, confs in conf.custom_inject_content.items():  # 遍历设置中的所有位置
                for item in confs:  # 每个位置中的条目
                    # 判断正则是否匹配当前url, 不匹配跳过
                    pattern = item.get("url_regex")
                    if pattern is not None and not re.match(pattern, self.parse.url_no_scheme):
                        continue

                    # 将内容插入到html
                    resp_text: str = inject_content(position, resp_text, item["content"])

        return resp_text.encode(encoding="utf-8"), req_time_body  # return bytes

    def response_cookies_deep_copy(self):
        pass

    def response_cookie_rewrite(self, cookie_string):
        pass

    def encode_mirror_url(
        self, remote_url: str, remote_domain: str = None, has_scheme: bool = True, escaped: bool = False
    ) -> str:
        if escaped:
            unesc_remote_url = un_esc_str(remote_url)
        else:
            unesc_remote_url = remote_url
        splited = urlsplit(unesc_remote_url)

        if "/extdomains/" == splited.path[:12]:
            return remote_url

        domain = remote_domain or splited.netloc or self.parse.remote_domain or conf.target_domain
        if domain not in conf.allowed_domains:
            return remote_url

        if has_scheme:
            if "//" == unesc_remote_url[:2]:
                scheme_host = "//" + conf.my_host_name
            elif splited.scheme:
                scheme_host = conf.my_scheme_and_host
            else:
                scheme_host = ""
        else:
            scheme_host = ""

        if self.G.is_external_domain(domain):
            middle_part = "/extdomains/" + domain
        else:
            middle_part = ""

        path_and_query = splited.path + ("?" + splited.query if splited.query else "")
        fragment = splited.fragment if splited.fragment else ""

        mirror_url = urljoin(scheme_host, middle_part + "/", path_and_query.strip("/"))
        mirror_url += "#" + fragment if fragment else ""

        if escaped:
            mirror_url = esc_str(mirror_url)

        return mirror_url

    def _preload_streamed_response_content_async(
        self, requests_response: requests_Response, buffer_queue: queue.Queue
    ):
        """
        stream模式下, 预读远程响应的content
        :param requests_response_obj:
        :type buffer_queue: queue.Queue
        """
        for particle_content in requests_response.iter_content(conf.stream_buffer_size):
            try:
                buffer_queue.put(particle_content, timeout=10)
            except queue.Full:  # coverage: exclude
                traceback.print_exc()
                exit()
            if conf.verbose_level >= 3:
                logger.debug("BufferSize", buffer_queue.qsize())
        buffer_queue.put(None, timeout=10)
        exit()

    def _update_content_in_local_cache(self, url, content, method="GET"):
        """更新 local_cache 中缓存的资源, 追加content
        在stream模式中使用"""
        if conf.local_cache_enable and method == "GET" and self.G.cache.is_cached(url):
            info_dict = self.G.cache.get_info(url)
            resp = self.G.cache.get_obj(url)
            resp.set_data(content)

            # 当存储的资源没有完整的content时, without_content 被设置为true
            # 此时该缓存不会生效, 只有当content被添加后, 缓存才会实际生效
            # 在stream模式中, 因为是先接收http头, 然后再接收内容, 所以会出现只有头而没有内容的情况
            # 此时程序会先将只有头部的响应添加到本地缓存, 在内容实际接收完成后再追加内容
            info_dict["without_content"] = False

            logger.debug("LocalCache_UpdateCache", url, content[:30], len(content), v=4)

            self.G.cache.put_obj(
                url,
                resp,
                obj_size=len(content),
                expires=self.G.get_expire_from_mime(self.parse.mime),
                last_modified=info_dict.get("last_modified"),
                info_dict=info_dict,
            )

    def iter_streamed_response_async(self):
        """异步, 一边读取远程响应, 一边发送给用户"""
        total_size = 0
        _start_time = time()

        _content_buffer = b""
        _disable_cache_temporary = False

        buffer_queue = queue.Queue(maxsize=conf.stream_transfer_async_preload_max_packages_size)

        t = threading.Thread(
            target=self._preload_streamed_response_content_async,
            args=(self.parse.remote_response, buffer_queue),
            daemon=True,
        )
        t.start()

        while True:
            try:
                particle_content = buffer_queue.get(timeout=15)
            except queue.Empty:  # coverage: exclude
                logger.warn("WeGotAnStreamTimeout")
                traceback.print_exc()
                return
            buffer_queue.task_done()

            if particle_content is not None:
                # 由于stream的特性, content会被消耗掉, 所以需要额外储存起来
                if conf.local_cache_enable and not _disable_cache_temporary:
                    if len(_content_buffer) > 8 * 1024 * 1024:  # 8MB
                        _disable_cache_temporary = True
                        _content_buffer = None
                    else:
                        _content_buffer += particle_content

                yield particle_content
            else:
                # todo
                # if self.parse.url_no_scheme in url_to_use_cdn:
                #     # 更新记录中的响应的长度
                #     url_to_use_cdn[self.parse.url_no_scheme][2] = len(_content_buffer)

                if conf.local_cache_enable and not _disable_cache_temporary:
                    self._update_content_in_local_cache(
                        self.parse.remote_url,
                        _content_buffer,
                        method=self.parse.remote_response.request.method,
                    )
                return

            total_size += len(particle_content)
            speed = total_size / 1024 / (time() - _start_time + 0.000001)
            logger.debug("total_size:", total_size, "total_speed(KB/s):", speed, v=4)

    def rewrite_resp_headers(self, resp: Response):
        """
        Copy and parse remote server's response headers, generate our flask response object

        :type resp, Response
        :return: flask response object
        :rtype: Response
        """

        logger.debug("RemoteRespHeaders", self.parse.remote_response.headers)
        # --------------------- 将远程响应头筛选/重写并复制到我们的响应中 -----------------------
        # 筛选远程响应头时采用白名单制, 只有在 `allowed_remote_response_headers` 中的远程响应头才会被发送回浏览器
        for header_key in self.parse.remote_response.headers:
            header_key_lower = header_key.lower()
            # Add necessary response headers from the origin site, drop other headers
            if header_key_lower in conf.allowed_remote_response_headers:
                if header_key_lower == "location":
                    # 对于重定向的 location 的重写, 改写为zmirror的url
                    _location = self.parse.remote_response.headers[header_key]

                    if conf.custom_text_rewriter_enable:
                        # location头也会调用自定义重写函数进行重写, 并且有一个特殊的MIME: mwm/headers-location
                        # 这部分以后可能会单独独立出一个自定义重写函数
                        _location = self.G.custom_response_text_rewriter(
                            _location, "mwm/headers-location", self.parse.remote_url
                        )

                    resp.headers[header_key] = self.encode_mirror_url(_location)

                elif header_key_lower == "content-type":
                    # force add utf-8 to content-type if it is text
                    if is_mime_represents_text(self.parse.mime) and "utf-8" not in self.parse.content_type:
                        resp.headers[header_key] = self.parse.mime + "; charset=utf-8"
                    else:
                        resp.headers[header_key] = self.parse.remote_response.headers[header_key]

                elif header_key_lower in ("access-control-allow-origin", "timing-allow-origin"):
                    # if custom_allowed_origin is None:
                    #     resp.headers[header_key] = myurl_prefix
                    # elif custom_allowed_origin == "_*_":  # coverage: exclude
                    #     _origin = (
                    #         request.headers.get("origin") or request.headers.get("Origin") or myurl_prefix
                    #     )
                    #     resp.headers[header_key] = _origin
                    # else:
                    #     resp.headers[header_key] = custom_allowed_origin
                    pass

                else:
                    resp.headers[header_key] = self.parse.remote_response.headers[header_key]

            # If we have the Set-Cookie header, we should extract the raw ones
            #   and then change the cookie domain to our domain
            if header_key_lower == "set-cookie":
                for cookie_string in self.response_cookies_deep_copy():
                    resp.headers.add("Set-Cookie", self.response_cookie_rewrite(cookie_string))

        logger.debug("OurRespHeaders:\n", resp.headers)

        return resp

    def generate_our_response(self):
        """
        生成我们的响应
        :rtype: Response
        """
        if self.parse.streame_our_response:
            self.parse.time["req_time_body"] = 0
            # 异步传输内容, 不进行任何重写, 返回一个生成器
            content = self.iter_streamed_response_async()
        else:
            # 如果不是异步传输, 则(可能)进行重写
            content, self.parse.time["req_time_body"] = self.response_content_rewrite()

        # 创建基础的Response对象
        resp = Response(content, status=self.parse.remote_response.status_code)
        # rewrite remote response's headers
        resp = self.rewrite_resp_headers(resp)

        # add extra headers
        if self.parse.time["req_time_header"] >= 0.00001:
            self.parse.set_extra_resp_header("X-Header-Req-Time", "%.4f" % self.parse.time["req_time_header"])
        if self.parse.time.get("start_time") is not None and not self.parse.streame_our_response:
            # remote request time should be excluded when calculating total time
            self.parse.set_extra_resp_header("X-Body-Req-Time", "%.4f" % self.parse.time["req_time_body"])
            self.parse.set_extra_resp_header(
                "X-Compute-Time", "%.4f" % (process_time() - self.parse.time["start_time"])
            )
        self.parse.set_extra_resp_header("X-Powered-By", "zmirror/%s" % pkg_version)
        for k, v in self.parse.extra_resp_headers.items():
            resp.headers.set(k, v)

        # set cookies
        for name, cookie_string in self.parse.extra_cookies.items():
            resp.headers.add("Set-Cookie", cookie_string)

        # dump request and response data to file
        if conf.developer_dump_all_files and not self.parse.streame_our_response:
            dump_zmirror_snapshot("traffic")

        return resp
