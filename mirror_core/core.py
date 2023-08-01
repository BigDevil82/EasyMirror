from flask import Flask, jsonify, request

from .page_generator import PageGenerator
from .prior_request import RequestRewriter
from .post_request import ResponseRewriter
from .request_remote import RequestSender
from .shares import Shares
from .threadlocal import ZmirrorThreadLocal
from utils.util import *


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
        if not hasattr(self, "app") or not self.inited:
            self.init_app()
        self.app.run(host, port, debug=debug)

    @app.route("/", methods=["GET", "POST"])
    def home(self):
        if request.method.lower() == "get":
            return self.page_generator.generate_simple_page("Hello from LeoMirror!")
        else:
            return jsonify({"message": "Hello from LeoMirror!"})

    @app.route("/<path:input_path>", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE", "HEAD", "PATCH"])
    def entry_point(self):
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
