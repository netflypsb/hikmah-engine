"""Encyclopedia writing checks — hikmah-engine stub."""
import re

DIALECTIC_LABEL_RE = re.compile(r"thesis|antithesis|synthesis", re.IGNORECASE)
NUMBER_TOKEN_RE = re.compile(r"\d+")

def check_encyclopedia(content, fm, **params):
    return []
