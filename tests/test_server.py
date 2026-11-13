import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from modeldock.server import Handler


def test_dev_bridge_origin_and_request_validation(environment):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api"
        body = json.dumps(dict(command="state", args={})).encode()
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Origin": "https://example.invalid"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
        request = Request(url, data=body, headers={"Content-Type": "text/plain"})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 400
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:1420"},
        )
        with urlopen(request) as response:
            from modeldock import __version__

            assert json.load(response)["data"]["version"] == __version__
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
