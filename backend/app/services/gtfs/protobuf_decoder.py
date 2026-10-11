"""
Phase 44: GTFS-Realtime protobuf decoding.

Authorized GTFS-RT feeds are normally served as binary protobuf (FeedMessage). This converts a
FeedMessage into the same dict shape the existing JSON pipeline already validates, so geographic
filtering, deduplication, malformed-entity isolation and last-known-good handling all stay in
one place (GTFSParser / BMTCTransitDataProvider).
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("nammablr.gtfs_rt_protobuf")

try:  # gtfs-realtime-bindings is listed in backend/requirements.txt
    from google.protobuf.json_format import MessageToDict
    from google.transit import gtfs_realtime_pb2

    PROTOBUF_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when the dependency is missing
    PROTOBUF_AVAILABLE = False


def decode_feed_message(payload: bytes) -> Optional[Dict[str, Any]]:
    """Returns the FeedMessage as a dict, or None when the bytes are not a valid FeedMessage."""
    if not PROTOBUF_AVAILABLE:
        logger.warning("[TRANSIT] Protobuf GTFS-RT payload received but gtfs-realtime-bindings is not installed.")
        return None
    try:
        msg = gtfs_realtime_pb2.FeedMessage()
        msg.ParseFromString(payload)
        if not msg.HasField("header"):
            return None
        data = MessageToDict(msg, preserving_proto_field_name=True)
        # MessageToDict renders uint64 timestamps as strings; normalise the ones the pipeline reads.
        for ent in data.get("entity", []):
            veh = ent.get("vehicle")
            if isinstance(veh, dict) and isinstance(veh.get("timestamp"), str) and veh["timestamp"].isdigit():
                veh["timestamp"] = int(veh["timestamp"])
        return data
    except Exception as e:
        logger.warning("[TRANSIT] Malformed GTFS-RT protobuf payload rejected: %s", type(e).__name__)
        return None
