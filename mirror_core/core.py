from flask import Flask, jsonify, request

from utils.util import *

from .page_generator import PageGenerator
from .post_request import ResponseRewriter
from .prior_request import RequestRewriter
from .request_remote import RequestSender
from .shares import Shares
from .threadlocal import ZmirrorThreadLocal

app = Flask(__name__)


class LeoMirrorApp:
    def __init__(self) -> None:
        self.init_app()
        self.inited = True

    def init_app(self) -> None:
        self.app = app
        self.parse = ZmirrorThreadLocal()
        self.G = Shares()

        self.req_rewriter = RequestRewriter(self.parse, self.G)
        self.req_sender = RequestSender(self.parse, self.G)
        self.resp_rewriter = ResponseRewriter(self.parse, self.G)
        self.page_generator = PageGenerator(self.parse)

    def run(self, host="127.0.0.1", port=80, debug=False) -> None:
        port = self.G.conf.my_port or port
        host = self.G.conf.my_host_name or host
        if not hasattr(self, "app") or not self.inited:
            self.init_app()
        self.app.run(host, port, debug=debug)

    def home(self):
        if request.method.lower() == "get":
            return self.page_generator.generate_simple_page("Hello from LeoMirror!")
        else:
            return jsonify({"message": "Hello from LeoMirror!"})

    def entry_point(self, input_path):
        try:
            self.req_rewriter.assemle_parse()
            self.req_sender.request_remote_site()
            resp = self.resp_rewriter.generate_our_response()
            return resp
        except:
            self.G.logger.error("Error occurred while generating response")
            traceback.print_exc()
            return self.page_generator.generate_error_page(
                errormsg="Error occurred while generating response", is_traceback=True
            )


mirror_app = LeoMirrorApp()


# @app.route("/", methods=["GET", "POST"])
# def home():
#     return mirror_app.home()


@app.route("/", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE", "HEAD", "PATCH"])
@app.route("/<path:input_path>", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE", "HEAD", "PATCH"])
def entry_point(input_path=None):
    return mirror_app.entry_point(input_path)
