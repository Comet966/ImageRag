"""Private JSON-lines stdio bridge; the renderer never receives the API key."""

import json
import sys

from backend.core import SearchService, ServiceError


def send(message):
    print(json.dumps(message, ensure_ascii=False), flush=True)


def main():
    service = SearchService()
    send({"event": "ready"})
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                method = request.get("method")
                if method == "status":
                    result = service.status()
                elif method == "photos":
                    result = service.photos()
                elif method == "search":
                    result = service.search(request.get("query", ""), limit=request.get("limit", 12), media_type=request.get("media_type", "all"))
                elif method == "index":
                    result = service.index(lambda value: send({"event": "index-progress", "data": value}))
                else:
                    raise ServiceError("未知请求。")
                send({"id": request["id"], "result": result})
            except ServiceError as exc:
                send({"id": request.get("id"), "error": str(exc)})
            except Exception as exc:
                # Do not serialize raw exceptions: SDK errors can include request data.
                print(f"Worker failure: {type(exc).__name__}", file=sys.stderr, flush=True)
                send({"id": request.get("id"), "error": f"处理失败（{type(exc).__name__}），请查看终端或重试。"})
    finally:
        service.close()


if __name__ == "__main__":
    main()
