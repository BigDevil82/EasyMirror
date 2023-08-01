import os
import importlib
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

        self._automatic_domains_whitelist_enable = True
        self._domains_whitelist_auto_add_glob_list = ()

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
        self._text_like_mime_types = ("text", "json", "javascript", "xml")
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
        Your domain name, eg: 'www.foobar.com[:80]' used to access your mirror site
        including port if have one, not include scheme
        """
        return self._my_host_name

    @my_host_name.setter
    def my_host_name(self, value):
        if self._my_port is not None:
            self._my_host_name = f"{value}:{self._my_port}"
        else:
            self._my_host_name = value

    @property
    def my_host_name_no_port(self):
        return self._my_host_name.split(":")[0]

    @property
    def my_port(self):
        return self._my_port

    @my_port.setter
    def my_port(self, value):
        self._my_port = value

    @property
    def my_scheme(self):
        return self._my_scheme

    @my_scheme.setter
    def my_scheme(self, value):
        self._my_scheme = value

    @property
    def my_scheme_escaped(self):
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
        return self._is_dev

    @is_dev.setter
    def is_dev(self, value):
        self._is_dev = value

    @property
    def target_domain(self):
        return self._target_domain

    @target_domain.setter
    def target_domain(self, value):
        if value is None or value == "":
            raise ValueError("target_domain can not be empty")
        self._target_domain = value

    @property
    def target_scheme(self):
        return self._target_scheme

    @target_scheme.setter
    def target_scheme(self, value):
        self._target_scheme = value

    @property
    def external_domains(self):
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
        return self._target_domain_alias

    @target_domain_alias.setter
    def target_domain_alias(self, value):
        value = [] if value is None else value
        self._target_domain_alias = value.append(self.target_domain)

    @property
    def allowed_domains(self):
        if len(self._allowed_domains) != 0:
            return self._allowed_domains
        else:
            self._allowed_domains = set([self.target_domain] + self.external_domains)
            for _domain in self.external_domains:  # for support domain with port
                self._allowed_domains.add(urlsplit("http://" + _domain).hostname)
            for _domain in self.target_domain_alias:
                self._allowed_domains.add(_domain)

    @property
    def force_https_domains(self):
        return self._force_https_domains

    @force_https_domains.setter
    def force_https_domains(self, value):
        self._force_https_domains = value

    @property
    def verbose_level(self):
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
        return self._builtin_server_debug

    @builtin_server_debug.setter
    def builtin_server_debug(self, value):
        self._builtin_server_debug = value

    @property
    def builtin_server_extra_options(self):
        return self._builtin_server_extra_options

    @builtin_server_extra_options.setter
    def builtin_server_extra_options(self, value):
        self._builtin_server_extra_options = value

    @property
    def is_use_proxy(self):
        return self._is_use_proxy

    @is_use_proxy.setter
    def is_use_proxy(self, value):
        self._is_use_proxy = value

    @property
    def proxy_settings(self):
        return self._proxy_settings

    @proxy_settings.setter
    def proxy_settings(self, value):
        self._proxy_settings = value

    @property
    def automatic_domains_whitelist_enable(self):
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
    def global_ua_white_name(self):
        return self._global_ua_white_name

    @global_ua_white_name.setter
    def global_ua_white_name(self, value):
        self._global_ua_white_name = value

    @property
    def spider_ua_white_list(self):
        return self._spider_ua_white_list

    @spider_ua_white_list.setter
    def spider_ua_white_list(self, value):
        self._spider_ua_white_list = value

    @property
    def force_decode_with_charsets(self):
        return self._force_decode_with_charsets

    @force_decode_with_charsets.setter
    def force_decode_with_charsets(self, value):
        self._force_decode_with_charsets = value

    @property
    def possible_charsets(self):
        return self._possible_charsets

    @possible_charsets.setter
    def possible_charsets(self, value):
        self._possible_charsets = value

    @property
    def connection_keep_alive_enable(self):
        return self._connection_keep_alive_enable

    @connection_keep_alive_enable.setter
    def connection_keep_alive_enable(self, value):
        self._connection_keep_alive_enable = value

    @property
    def local_cache_enable(self):
        return self._local_cache_enable

    @local_cache_enable.setter
    def local_cache_enable(self, value):
        self._local_cache_enable = value

    @property
    def stream_transfer_enable(self):
        return self._stream_transfer_enable

    @stream_transfer_enable.setter
    def stream_transfer_enable(self, value):
        self._stream_transfer_enable = value

    @property
    def stream_buffer_size(self):
        return self._stream_buffer_size

    @stream_buffer_size.setter
    def stream_buffer_size(self, value):
        self._stream_buffer_size = value

    @property
    def stream_transfer_async_preload_max_packages_size(self):
        return self._stream_transfer_async_preload_max_packages_size

    @stream_transfer_async_preload_max_packages_size.setter
    def stream_transfer_async_preload_max_packages_size(self, value):
        self._stream_transfer_async_preload_max_packages_size = value

    @property
    def cron_task_enable(self):
        return self._cron_task_enable

    @cron_task_enable.setter
    def cron_task_enable(self, value):
        self._cron_task_enable = value

    @property
    def cron_task_list(self):
        return self._cron_task_list

    @cron_task_list.setter
    def cron_task_list(self, value):
        self._cron_task_list = value

    @property
    def custom_text_rewriter_enable(self):
        return self._custom_text_rewriter_enable

    @custom_text_rewriter_enable.setter
    def custom_text_rewriter_enable(self, value):
        self._custom_text_rewriter_enable = value

    @property
    def text_like_mime_types(self):
        return self._text_like_mime_types

    @text_like_mime_types.setter
    def text_like_mime_types(self, value):
        self._text_like_mime_types = value

    @property
    def custom_inject_content(self):
        return self._custom_inject_content

    @custom_inject_content.setter
    def custom_inject_content(self, value):
        self._custom_inject_content = value

    @property
    def developer_string_trace(self):
        return self._developer_string_trace

    @developer_string_trace.setter
    def developer_string_trace(self, value):
        self._developer_string_trace = value

    @property
    def developer_dump_all_files(self):
        return self._developer_dump_all_files

    @developer_dump_all_files.setter
    def developer_dump_all_files(self, value):
        self._developer_dump_all_files = value

    @property
    def developer_disable_ssrf_check(self):
        return self._developer_disable_ssrf_check

    @developer_disable_ssrf_check.setter
    def developer_disable_ssrf_check(self, value):
        self._developer_disable_ssrf_check = value

    @property
    def developer_disable_ssl_verify(self):
        return self._developer_disable_ssl_verify

    @developer_disable_ssl_verify.setter
    def developer_disable_ssl_verify(self, value):
        self._developer_disable_ssl_verify = value
