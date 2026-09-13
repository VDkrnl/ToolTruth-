
import re
from datetime import datetime, timezone
class ClaimExtractor:
    """Deterministic structural extractor for simulator JSON."""
    def extract(self, result: dict) -> list[dict]:
        claims=[]
        ts=result.get("as_of_timestamp") or result.get("timestamp") or datetime.now(timezone.utc).isoformat()
        for key,value in result.items():
            if key in {"error","as_of_timestamp"}: continue
            if isinstance(value,(str,int,float,bool)):
                claims.append({"claim":f"{key}={value}","field":key,"value":value,"timestamp":ts,"source":"simulator","confidence":1.0})
        return claims
