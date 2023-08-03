import importlib
import os
from urllib.parse import urlsplit

from utils.ColorfulPyPrint import ColorfulPrinter

printer = ColorfulPrinter(2, 0)


class Config:
    def __init__(self, conf_path=None, **kwargs) -> None:
        """
        Configurations for running a proxy website

        Args:
         - conf_path: path to the config file, if not specified, will use the default config, currently only support python file
         - kwargs: key-value pairs, will override the default config
           supported config items and help infomation can be found by calling `config_instance.help()`
        """
        self.__set_default_configs()

        if conf_path is not None:
            confs_from_file = self.__load_config_from_file(conf_path)
            confs_from_file.update(kwargs)

        user_confs = confs_from_file if conf_path is not None else kwargs

        supported_props = self.__get_all_properties()
        for k, v in user_confs.items():
            if k in supported_props:
                setattr(self, k, v)
            else:
                # find the most similar one
                guess = self.__find_best_match(k, supported_props)
                if guess is not None:
                    guess = "do you mean " + guess + "?"
                printer.warn(f"unsupported config item: {k}, discared. {guess}")

    def __load_config_from_file(self, conf_path: str) -> dict:
        if not os.path.exists(conf_path):
            raise FileNotFoundError(f"Config file not found: {conf_path}")
        if not conf_path.endswith(".py"):
            raise ValueError(f"Only support python config file, got: {conf_path}")
        # load config from file
        conf_dict = importlib.import_module(conf_path.rstrip(".py")).__dict__
        # remove the magic variables
        conf_dict = {k: v for k, v in conf_dict.items() if not k.startswith("__")}
        return conf_dict

    def __find_best_match(self, user_input, string_list):
        """
        Find the most similar string in a list of strings to a user input.
        """
        best_match = None
        best_score = 0

        for string in string_list:
            score = 0
            for char in user_input:
                if char in string:
                    score += 1
            if score > best_score:
                best_score = score
                best_match = string

        best_match = None if best_score / len(user_input) < 0.6 else best_match

        return best_match

    def __set_default_configs(self):
        ######### basic settings #########
        self._my_host_name = "127.0.0.1"
        self._my_port = 3000
        self._my_scheme = "http://"
        self._is_dev = False
        self._target_domain = "www.google.com"
        self._target_scheme = "https://"
        self._external_domains = []
        self._target_domain_alias = []
        self._allowed_domains = []
        self._force_https_domains = None

        ######### advanced settings #########
        self._verbose_level = 2

        self._builtin_server_host = "0.0.0.0"
        self._builtin_server_debug = False
        self._builtin_server_extra_options = {}

        self._is_use_proxy = False
        self._proxy_settings = None

        self._custom_allowed_origin = None
        self._automatic_domains_whitelist_enable = True
        self._domains_whitelist_auto_add_glob_list = ()
        self._aggressive_cookies_rewrite = None

        self._global_ua_white_name = "qiniu-imgstg-spider"
        self._spider_ua_white_list = ("qiniu", "cdn")

        self._force_decode_with_charsets = None
        self._possible_charsets = ["utf-8", "gbk", "big5", "latin1"]

        self._connection_keep_alive_enable = True
        self._local_cache_enable = True

        self._stream_transfer_enable = True
        self._stream_buffer_size = 1024 * 16  # 16KB
        self._stream_transfer_async_preload_max_packages_size = 15

        self._cron_task_enable = True
        self._cron_task_list = [
            # builtin cache flush, unless you really know what you are doing, please do not remove these two tasks
            #   lower priority would be execute first
            # 对内置缓存的清理, 除非你真的知道你在做什么, 否则请不要移除这两个定时任务
            #   priority值越低, 运行顺序的优先级越高
            dict(name="cache_clean_soft", priority=42, interval=60 * 15, target="cache_clean"),
            dict(
                name="cache_clean_force_all",
                priority=42,
                interval=3600 * 24 * 7,
                target="cache_clean",
                kwargs={"is_force_flush": True},
            ),
            # below is the complete syntax.
            # dict(name='just a name', priority=10, interval=60 * 10, target='your_own_cron_function', args=(1,2,), kwargs={'a':1}),
        ]

        self._custom_text_rewriter_enable = False
        self._text_like_mime_types = set(["text", "json", "javascript", "xml"])
        self._custom_inject_content = {}

        ######### developer settings #########
        self._developer_string_trace = None
        self._developer_dump_all_files = False
        self._developer_disable_ssrf_check = False
        self._developer_disable_ssl_verify = False

        ######### some default settings #########
        self.allowed_remote_response_headers = {
            "content-type",
            "date",
            "expires",
            "cache-control",
            "last-modified",
            "server",
            "location",
            "accept-ranges",
            "access-control-allow-origin",
            "access-control-allow-headers",
            "access-control-allow-methods",
            "access-control-expose-headers",
            "access-control-max-age",
            "access-control-allow-credentials",
            "timing-allow-origin",
        }

    def __get_all_properties(self):
        cls = self.__class__
        props = []
        for name in dir(cls):
            attr = getattr(cls, name)
            if isinstance(attr, property):
                props.append(name)
        return props

    def help(self):
        """
        print out the doc string for each setting item
        """
        # Get a list of all properties and their docstrings
        props = self.__get_all_properties()
        prop_docs = []
        cls = self.__class__
        for name in props:
            attr = getattr(cls, name)
            doc_string = attr.__doc__ or ""
            prop_docs.append((name, doc_string.strip()))
        for name, doc in prop_docs:
            print(f"{name}:")
            print(f"\t{doc}")
            print()

    def __repr__(self) -> str:
        return f"<Config {self.__dict__}>"

    def __str__(self) -> str:
        output = "configurations:\n"
        for k, v in self.__dict__.items():
            output += f"{k.lstrip('_')} = {v}\n"
        return output

    @property
    def my_host_name(self):
        """
        Your domain name, eg: 'www.foobar.com' used to access your mirror site
        including port if have one, not include scheme
        """
        return self._my_host_name if not self._is_dev else "127.0.0.1"

    @my_host_name.setter
    def my_host_name(self, value):
        self._my_host_name = value

    @property
    def my_host_name_with_port(self):
        if self._my_port == 80 and self._my_scheme == "http://":
            return self._my_host_name
        if self._my_port == 443 and self._my_scheme == "https://":
            return self._my_host_name
        return self._my_host_name + f":{self._my_port}"

    @property
    def my_port(self):
        """
        Your port, if use the default value(80 for http, 443 for https), please set it to None
        otherwise please set your port (number)
        an non-standard port MAY prevent the gfw's observe, but MAY also cause compatibility problems
        """
        if self._my_port is None and self._my_scheme == "http://":
            return 80
        if self._my_port is None and self._my_scheme == "https://":
            return 443
        return self._my_port

    @my_port.setter
    def my_port(self, value):
        self._my_port = value

    @property
    def my_scheme(self):
        """
        Your domain's scheme, 'http://' or 'https://', it affects the user.
        """
        return self._my_scheme

    @my_scheme.setter
    def my_scheme(self, value):
        self._my_scheme = value

    @property
    def my_scheme_escaped(self):
        """
        replace '/' with '\\\\/' in my_scheme
        """
        return self._my_scheme.replace("/", r"\/")

    @property
    def my_scheme_and_host(self):
        """
        host name with scheme, eg: 'http://www.foobar.com[:80]'
        """
        return self._my_scheme + self._my_host_name

    @property
    def my_scheme_host_escaped(self):
        return self.my_scheme_and_host.replace("/", r"\/")

    @property
    def is_dev(self):
        """
        is in development mode, if True, will use 127.0.0.1 as my_host_name, and set verbose level to 3 if not specified
        """
        return self._is_dev

    @is_dev.setter
    def is_dev(self, value):
        env_dev = os.environ.get("dev", None)
        is_dev = value or (env_dev is not None and env_dev.lower() in ("1", "true", "yes"))
        self._is_dev = is_dev

    @property
    def target_domain(self):
        """
        Target main domain
        Notice: ONLY the main domain and external domains are ALLOWED to cross this proxy
        """
        return self._target_domain

    @target_domain.setter
    def target_domain(self, value):
        if value is None or value == "":
            raise ValueError("target_domain can not be empty")
        self._target_domain = value

    @property
    def target_scheme(self):
        """
        Target domain's scheme, 'http://' or 'https://', it affects the server only.
        """
        return self._target_scheme

    @target_scheme.setter
    def target_scheme(self, value):
        self._target_scheme = value

    @property
    def external_domains(self):
        """
        domain(s) also included in the proxyzone, mostly are the main domain's static file domains or sub domains
        tips: you can find a website's external domains by using the developer tools of your browser,
        # it will log all network traffics for you
        """
        return self._external_domains

    @external_domains.setter
    def external_domains(self, value: list[str]):
        if value is None:
            self._external_domains = []
        else:
            self._external_domains = list(
                [d.strip("./ \t").replace("https://", "").replace("http://", "") for d in value]
            )

    @property
    def target_domain_alias(self):
        """
        these domains would be regarded as the `target_domain`, and do the same process
        eg: kernel.org is the same of www.kernel.org format: ('kernel.org',)
        """
        return self._target_domain_alias

    @target_domain_alias.setter
    def target_domain_alias(self, value):
        value = [] if value is None else value
        value.append(self.target_domain)
        self._target_domain_alias = value

    @property
    def allowed_domains(self):
        """
        all allowed domains including target_domain, external_domains and target_domain_alias
        """
        if len(self._allowed_domains) != 0:
            return self._allowed_domains
        else:
            self._allowed_domains = set([self.target_domain] + self.external_domains)
            for _domain in self.external_domains:  # for support domain with port
                self._allowed_domains.add(urlsplit("http://" + _domain).hostname)
            for _domain in self.target_domain_alias:
                self._allowed_domains.add(_domain)
            return self._allowed_domains

    @property
    def force_https_domains(self):
        """
        'ALL' for all, 'NONE' for none(case sensitive), ('foo.com','bar.com','www.blah.com') for custom
        """
        return self._force_https_domains

    @force_https_domains.setter
    def force_https_domains(self, value):
        self._force_https_domains = value

    @property
    def verbose_level(self):
        """
        Verbose level (0~4) 0:important and error 1:warning 2:info  3/4:debug. Default is 3 (for first time runner)
        """
        if self._verbose_level is None and self._is_dev:
            return 3
        return self._verbose_level

    @verbose_level.setter
    def verbose_level(self, value):
        self._verbose_level = value

    @property
    def builtin_server_host(self):
        return self._builtin_server_host

    @builtin_server_host.setter
    def builtin_server_host(self, value):
        self._builtin_server_host = value

    @property
    def builtin_server_debug(self):
        """
        If you want to use the builtin server to listen Internet (NOT recommend)
        please modify the following configs
        set built_in_server_host='0.0.0.0' and built_in_server_debug=False
        """
        return self._builtin_server_debug

    @builtin_server_debug.setter
    def builtin_server_debug(self, value):
        self._builtin_server_debug = value

    @property
    def builtin_server_extra_options(self):
        """
        other params which will be passed to flask builtin server
        please see :func:`flask.client.Flask.fun`
        and :func:`werkzeug.serving.run_simple` for more information
        eg: {"processes":4, "hostname":"localhost"}
        """
        return self._builtin_server_extra_options

    @builtin_server_extra_options.setter
    def builtin_server_extra_options(self, value):
        self._builtin_server_extra_options = value

    @property
    def is_use_proxy(self):
        """
        Global proxy option, True or False (case sensitive)
        Tip: If you want to make an GOOGLE mirror in China, you need an foreign proxy.
        However, if you run this script in foreign server, which can access google directly, set it to False
        """
        return self._is_use_proxy

    @is_use_proxy.setter
    def is_use_proxy(self, value):
        self._is_use_proxy = value

    @property
    def proxy_settings(self):
        """
        If is_use_proxy = False, the following setting would NOT have any effect
        DO NOT support socks4/5 proxy. If you want to use socks proxy, please use Privoxy to convert them to http(s) proxy.
        """
        return self._proxy_settings

    @proxy_settings.setter
    def proxy_settings(self, value):
        self._proxy_settings = value

    @property
    def custom_allowed_origin(self):
        return self._custom_allowed_origin

    @custom_allowed_origin.setter
    def custom_allowed_origin(self, value):
        self._custom_allowed_origin = value

    @property
    def automatic_domains_whitelist_enable(self):
        """
        Automatic Domains Whitelist
        by given wild match domains (glob syntax, '*.example.com'), if we got domains match these cases,
        it would be automatically added to the `external_domains`
        # However, before you restart your server, you should check the 'automatic_domains_whitelist.log' file,
        and manually add domains to the config, or it would not work after you restart your server
        You CANNOT relay on the automatic whitelist, because the basic (but important) rewrite require specified domains to work.
        For More Supported Pattern Please See: https://docs.python.org/3/library/fnmatch.html#module-fnmatch
        """
        return self._automatic_domains_whitelist_enable

    @automatic_domains_whitelist_enable.setter
    def automatic_domains_whitelist_enable(self, value):
        self._automatic_domains_whitelist_enable = value

    @property
    def domains_whitelist_auto_add_glob_list(self):
        return self._domains_whitelist_auto_add_glob_list

    @domains_whitelist_auto_add_glob_list.setter
    def domains_whitelist_auto_add_glob_list(self, value):
        self._domains_whitelist_auto_add_glob_list = value

    @property
    def aggressive_cookies_rewrite(self):
        return self._aggressive_cookies_rewrite

    @aggressive_cookies_rewrite.setter
    def aggressive_cookies_rewrite(self, value):
        self._aggressive_cookies_rewrite = value

    @property
    def global_ua_white_name(self):
        """
        If client's ua CONTAINS this, it's access will be granted.Only one value allowed.
        this white name also affects any other client filter (Human/IP verification, etc..)
        Please don't use this if you don't use filters.
        """
        return self._global_ua_white_name

    @global_ua_white_name.setter
    def global_ua_white_name(self, value):
        """
        If client's ua CONTAINS this, it's access will be granted.Only one value allowed.
        this white name also affects any other client filter (Human/IP verification, etc..)
        Please don't use this if you don't use filters.
        """
        self._global_ua_white_name = value

    @property
    def spider_ua_white_list(self):
        return self._spider_ua_white_list

    @spider_ua_white_list.setter
    def spider_ua_white_list(self, value):
        self._spider_ua_white_list = value

    @property
    def force_decode_with_charsets(self):
        """
        for some modern websites (google/wiki, etc), we can assume it well always use utf-8 encoding.
        or for some old-styled sites, we could also force the program to use gbk encoding (just for example)
        this should reduce the content encoding detect time.
        """
        return self._force_decode_with_charsets

    @force_decode_with_charsets.setter
    def force_decode_with_charsets(self, value):
        self._force_decode_with_charsets = value

    @property
    def possible_charsets(self):
        """
        program will test these charsets one by one, if `force_decode_remote_using_encode` is None
        this will be helpful to solve Chinese GBK issues
        """
        return self._possible_charsets

    @possible_charsets.setter
    def possible_charsets(self, value):
        self._possible_charsets = value

    @property
    def connection_keep_alive_enable(self):
        """
        Keep-Alive Per domain
        """
        return self._connection_keep_alive_enable

    @connection_keep_alive_enable.setter
    def connection_keep_alive_enable(self, value):
        self._connection_keep_alive_enable = value

    @property
    def local_cache_enable(self):
        """
        Cache remote static files to your local storage. And access them directly from local storge if necessary.
        an 304 response support is implanted inside
        """
        return self._local_cache_enable

    @local_cache_enable.setter
    def local_cache_enable(self, value):
        self._local_cache_enable = value

    @property
    def stream_transfer_enable(self):
        """
        We can transfer some content (eg:video) in stream mode
        in non-stream mode, our server have to receive all remote response first, then send it to user
        However, in stream mode, we would receive and send data piece-by-piece (small pieces)
        Notice: local cache would not be available for stream content, please don't add image to stream list
        IMPORTANT: NEVER ADD TEXT-LIKE CONTENT TYPE TO STREAM
        """
        return self._stream_transfer_enable

    @stream_transfer_enable.setter
    def stream_transfer_enable(self, value):
        self._stream_transfer_enable = value

    @property
    def stream_buffer_size(self):
        """
        streamed content fetch size (per package)
        """
        return self._stream_buffer_size

    @stream_buffer_size.setter
    def stream_buffer_size(self, value):
        self._stream_buffer_size = value

    @property
    def stream_transfer_async_preload_max_packages_size(self):
        """
        streamed content async preload -- max preload packages number
        """
        return self._stream_transfer_async_preload_max_packages_size

    @stream_transfer_async_preload_max_packages_size.setter
    def stream_transfer_async_preload_max_packages_size(self, value):
        self._stream_transfer_async_preload_max_packages_size = value

    @property
    def cron_task_enable(self):
        """
        Cron Tasks, if you really know what you are doing, please do not disable this option
        """
        return self._cron_task_enable

    @cron_task_enable.setter
    def cron_task_enable(self, value):
        self._cron_task_enable = value

    @property
    def cron_task_list(self):
        """
        If you want to add your own cron tasks, please create the function in 'custom_func.py', and add it's name in `target`
        minimum task delay is 3 minutes (180 seconds), any delay that less than 3 minutes would be regarded as 3 minutes
        """
        return self._cron_task_list

    @cron_task_list.setter
    def cron_task_list(self, value):
        self._cron_task_list = value

    @property
    def custom_text_rewriter_enable(self):
        """
        You can do some custom modifications/rewrites to the response content.
        # If enabled, every remote text response (html/css/js...) will be passed to your own rewrite function first,
        custom rewrite would be applied BEFORE any builtin content rewrites
        so, the response passed to your function is exactly the same to the remote server's response.
        You need to write your own
        """
        return self._custom_text_rewriter_enable

    @custom_text_rewriter_enable.setter
    def custom_text_rewriter_enable(self, value):
        self._custom_text_rewriter_enable = value

    @property
    def text_like_mime_types(self):
        """
        If mime contains any of these keywords, it would be regarded as text
        some websites(such as twitter), would send some strange mime which also represent txt ('x-mpegurl')
        in these cases, you can add them here
        default value: ("text", "json", "javascript", "xml")
        """
        return tuple(self._text_like_mime_types)

    @text_like_mime_types.setter
    def text_like_mime_types(self, value):
        self._text_like_mime_types = self._text_like_mime_types.union(set(value))

    @property
    def custom_inject_content(self):
        """
        inject custom content to the html reponse
        """
        return self._custom_inject_content

    @custom_inject_content.setter
    def custom_inject_content(self, value):
        self._custom_inject_content = value

    @property
    def developer_string_trace(self):
        """
        for development diagnose, if not None, will track string in code execution
        """
        return self._developer_string_trace

    @developer_string_trace.setter
    def developer_string_trace(self, value):
        self._developer_string_trace = value

    @property
    def developer_dump_all_files(self):
        """
        dump all request and reponse data to local disk
        """
        return self._developer_dump_all_files

    @developer_dump_all_files.setter
    def developer_dump_all_files(self, value):
        self._developer_dump_all_files = value

    @property
    def developer_disable_ssrf_check(self):
        """
        temporarily disable ssrf check
        """
        return self._developer_disable_ssrf_check

    @developer_disable_ssrf_check.setter
    def developer_disable_ssrf_check(self, value):
        self._developer_disable_ssrf_check = value

    @property
    def developer_disable_ssl_verify(self):
        """
        temporarily disable ssl verify
        """
        return self._developer_disable_ssl_verify

    @developer_disable_ssl_verify.setter
    def developer_disable_ssl_verify(self, value):
        self._developer_disable_ssl_verify = value
