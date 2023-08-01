from time import time
from urllib.parse import urlsplit
from flask import request
import requests

from connection_pool import get_session
from shares import Shares, conf, logger
from threadlocal import ZmirrorThreadLocal
from utils.util import current_line_number


class RequestSender:
    def __init__(self, parse: ZmirrorThreadLocal, shares: Shares) -> None:
        self.parse = parse
        self.G = shares

    def try_decode_request_data(self):
        """
        解析出浏览者发送过来的data, 如果是文本, 则进行重写
        如果是文本, 则对文本内容进行重写后返回str
        如果是二进制则, 则原样返回, 不进行任何处理 (bytes)
        :rtype: Union[str, bytes, None]
        """
        data: bytes = request.get_data()  # type: bytes

        # 尝试解析浏览器传入的东西的编码
        encoding = self.G.encoding_detect(data)

        if encoding is not None:
            try:
                data_str = data.decode(encoding=encoding)  # type: str
            except:
                # 解码失败, data是二进制内容或无法理解的编码, 原样返回, 不进行重写
                encoding = None
            else:
                # data是文本内容, 则进行重写, 并返回str
                data_str = self.client_requests_text_rewrite(data_str)  # type: str

        # 下面这个if是debug用代码, 对正常运行无任何作用
        if conf.developer_string_trace:  # coverage: exclude
            if isinstance(data, str):
                data = data.encode(encoding=encoding)
            if conf.developer_string_trace.encode(encoding=encoding) in data:
                logger.info(
                    "StringTrace: appears after client_requests_bin_rewrite, code line no. ",
                    current_line_number(),
                )

        self.parse.request_data, self.parse.request_data_encoding = data, encoding
        return data, encoding

    def send_request(self, url, method="GET", headers=None, param_get=None, data=None):
        """
        实际发送请求到目标服务器, 对于重定向, 原样返回给用户
        被request_remote_site_and_parse()调用
        """
        final_hostname = urlsplit(url).netloc
        logger.debug("FinalRequestUrl", url, "FinalHostname", final_hostname)
        # Only external in-zone domains are allowed (SSRF check layer 2)
        if final_hostname not in conf.allowed_domains and not conf.developer_disable_ssrf_check:
            raise ConnectionAbortedError(
                "Trying to access an OUT-OF-ZONE domain(SSRF Layer 2):", final_hostname
            )

        # set zero data to None instead of b''
        if not data:
            data = None

        prepared_req = requests.Request(
            method,
            url,
            headers=headers,
            params=param_get,
            data=data,
        ).prepare()

        # get session
        if conf.connection_keep_alive_enable:
            _session = get_session(final_hostname)
        else:
            _session = requests.Session()

        # Send real requests
        self.parse.time["req_start_time"] = time()
        r = _session.send(
            prepared_req,
            proxies=conf.proxy_settings,
            allow_redirects=False,  # disable redirect
            stream=conf.stream_transfer_enable,
            verify=not conf.developer_disable_ssl_verify,
        )
        # remote request time
        self.parse.time["req_time_header"] = time() - self.parse.time["req_start_time"]
        logger.debug("RequestTime:", self.parse.time["req_time_header"], v=4)

        # Some debug output
        logger.debug(
            r.request.method, "FinalSentToRemoteRequestUrl:", r.url, "\nRem Resp Stat: ", r.status_code
        )
        logger.debug("RemoteRequestHeaders: ", r.request.headers)
        if data:
            logger.debug("RemoteRequestRawData: ", r.request.body, v=5)
        logger.debug("RemoteResponseHeaders: ", r.headers)

        return r

    def request_remote_site(self):
        """
        请求远程服务器(high-level), 并在返回404/500时进行 domain_guess 尝试
        """

        self.parse.request_data, self.parse.request_data_encoding = self.try_decode_request_data()
        # 请求被镜像的网站
        # 注意: 在zmirror内部不会处理重定向, 重定向响应会原样返回给浏览器
        self.parse.remote_response = self.send_request(
            self.parse.remote_url,
            method=request.method,
            headers=self.parse.client_header,
            data=self.parse.request_data_encoded,
        )

        if self.parse.remote_response.url != self.parse.remote_url:
            logger.warn(
                "requests's remote url",
                self.parse.remote_response.url,
                "does no equals our rewrited url",
                self.parse.remote_url,
            )

        # if 400 <= self.parse.remote_response.status_code <= 599:
        #     # 猜测url所对应的正确域名
        #     logger.debug("Domain guessing for", request.url)
        #     result = guess_correct_domain()
        #     if result is not None:
        #         self.parse.remote_response = result
