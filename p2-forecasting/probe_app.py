import os
import resource

# Imported only to measure the memory the real forecast API will use.
import feast  # noqa: F401
import lightgbm  # noqa: F401
import pandas  # noqa: F401
import pyarrow  # noqa: F401
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    max_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return {
        "status": "ok",
        "max_rss_mb": round(max_rss_mb, 1),
        "repo_root_copied": os.path.exists("/app/README.md"),
    }
