"""Story 后端启动入口：uvicorn :8100。

HOST 默认 127.0.0.1（本地直接跑）；Docker 里由 compose 设为 0.0.0.0。
"""
import os

import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8100"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
