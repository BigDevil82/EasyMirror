import traceback

from flask import make_response

import CONSTS
from utils.util import *
from shares import logger
from threadlocal import ZmirrorThreadLocal


class PageGenerator:
    def __init__(self, parse: ZmirrorThreadLocal) -> None:
        self.parse = parse

    def generate_simple_page(self, content, code=200, content_type="text/html"):
        """
        :type content: Union[str, bytes]
        :type code: int
        :type content_type: str
        :rtype: Response
        """
        if isinstance(content, str):
            content = content.encode()
        return make_response(content, code, {"Content-Type": content_type})

    def generate_error_page(
        self, errormsg="Unknown Error", error_code=500, is_traceback=False, content_only=False
    ):
        """

        :type content_only: bool
        :type errormsg: Union(str, bytes)
        :type error_code: int
        :type is_traceback: bool
        :rtype: Union[Response, str]
        """
        if is_traceback:
            traceback.print_exc()
            logger.error(errormsg)

        if isinstance(errormsg, bytes):
            errormsg = errormsg.decode()

        dump_file_path = dump_zmirror_snapshot(msg=errormsg)

        request_detail = ""
        for attrib in filter(lambda x: x[0] != "_" and x[-2:] != "__", dir(self.parse)):
            request_detail += "<tr><td>{attrib}</td><td>{value}</td></tr>".format(
                attrib=attrib, value=html_escape(str(self.parse.__getattribute__(attrib)))
            )

        error_page = """<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">
    <title>zmirror internal error</title>
    <style>code{{background-color: #cccaca;}}</style>
    </head>
    <body>
    <h1>zmirror internal error</h1>
    An fatal error occurs. 服务器中运行的zmirror出现一个内部错误.<br>

    <hr>
    <h2>If you are visitor 如果你是访客</h2>
    This site is temporary unavailable because some internal error<br>
    Please contact your site admin. <br>
    该镜像站暂时出现了临时的内部故障, 请联系网站管理员<br>

    <hr>
    <h2>If you are admin</h2>
    You can find full detail log in your server's log.<br>
    For apache, typically at <code>/var/log/apache2/YOUR_SITE_NAME_error.log</code><br>
    tips: you can use <code>tail -n 100 -f YOUR_SITE_NAME_error.log</code> to view real-time log<br>
    <br>
    If you can't solve it by your self, here are some ways may help:<br>
    <ul>
        <li>contact the developer by email: <a href="mailto:i@z.codes" target="_blank">aploium &lt;i@z.codes&gt;</a></li>
        <li>seeking for help in zmirror's <a href="https://gitter.im/zmirror/zmirror" target="_blank">online chat room</a></li>
        <li>open an <a href="https://github.com/aploium/zmirror/issues" target="_blank">issue</a> (as an bug report) in github</li>
    </ul>
    <h3>Snapshot Dump</h3>
    An snapshot has been dumped to <code>{dump_file_path}</code> <br>
    You can load it using (Python3 code) <code>pickle.load(open(r"{dump_file_path}","rb"))</code><br>
    The snapshot contains information which may be helpful for debug
    <h3>Detail</h3>
    <table border="1"><tr><th>Attrib</th><th>Value</th></tr>
    {request_detail}
    </table>
    <h3>Additional Information</h3>
    <pre>{errormsg}</pre>
    <h3>Traceback</h3>
    <pre>{traceback_str}</pre>
    <hr>
    <div style="font-size: smaller">Powered by <em>zmirror {version}</em><br>
    <a href="{official_site}" target="_blank">{official_site}</a></div>
    </body></html>""".format(
            errormsg=errormsg,
            request_detail=request_detail,
            traceback_str=html_escape(traceback.format_exc()) if is_traceback else "None or not displayed",
            dump_file_path=dump_file_path,
            version=CONSTS.__VERSION__,
            official_site=CONSTS.__GITHUB_URL__,
        )

        if not content_only:
            return make_response(error_page.encode(), error_code)
        else:
            return error_page
