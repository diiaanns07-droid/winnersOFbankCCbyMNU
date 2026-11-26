"""python -m bcc_review.v2.web [--port 8014] [--provider auto] [--data-dir .bcc_web]"""
from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
