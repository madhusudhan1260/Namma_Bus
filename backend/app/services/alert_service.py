from datetime import datetime, timezone
from typing import List, Optional
import logging

from ..models.transit import ServiceAlert
from ..core.config import settings

logger = logging.getLogger("nammablr.alert_service")


class AlertService:
    """
    Manages municipal service alerts, corridor disruption notices,
    and GTFS-RT ServiceAlert entity mapping.
    Distinguishes official realtime alerts from simulated baseline notices.
    """

    def __init__(self):
        self._alerts: List[ServiceAlert] = [
            ServiceAlert(
                id="alert-orr-metro-work",
                route_number="500D",
                stop_name="Central Silk Board Junction",
                title="ORR Metro Construction Slowdown",
                description="Heavy congestion near Central Silk Board flyover and Agara Lake junction due to ongoing metro work. Expect 8-12 min transit delays during peak hours.",
                severity="WARNING",
                active_period_start=datetime.now(timezone.utc),
                affected_entities=["500D", "KIA-8", "stop-silk-board", "stop-agara"],
                is_official_realtime=False,
            ),
            ServiceAlert(
                id="alert-hosur-road-flyover",
                route_number="356",
                stop_name="Electronic City Toll Gate",
                title="Hosur Elevated Expressway Normal Flow",
                description="Clear transit corridor along Hosur Road toward Electronic City with minimal bus lane delays.",
                severity="INFO",
                active_period_start=datetime.now(timezone.utc),
                affected_entities=["356", "stop-electronic-city"],
                is_official_realtime=False,
            ),
            ServiceAlert(
                id="alert-airport-kia-freq",
                route_number="KIA-8",
                stop_name="Kempegowda International Airport",
                title="Vayu Vajra KIA-8 Scheduled Frequency Active",
                description="Airport feeder buses operating on standard 20-minute departures from Electronic City via Silk Board.",
                severity="INFO",
                active_period_start=datetime.now(timezone.utc),
                affected_entities=["KIA-8"],
                is_official_realtime=False,
            ),
        ]

    def get_alerts(
        self,
        route_number: Optional[str] = None,
        stop_name: Optional[str] = None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        active_only: bool = True,
    ) -> List[ServiceAlert]:
        filtered = self._alerts
        if active_only:
            filtered = [a for a in filtered if a.is_active]
        if source:
            s_match = source.lower().strip()
            filtered = [a for a in filtered if a.source.lower() == s_match]
        if route_number:
            r_clean = route_number.upper().replace(" ", "").replace("-", "")
            filtered = [
                a for a in filtered
                if (a.route_number and a.route_number.upper().replace(" ", "").replace("-", "") == r_clean)
                or (any(r_clean in e.upper() for e in a.affected_entities))
            ]
        if stop_name:
            s_clean = stop_name.lower().strip()
            filtered = [
                a for a in filtered
                if (a.stop_name and s_clean in a.stop_name.lower())
                or (any(s_clean in e.lower() for e in a.affected_entities))
            ]
        if severity:
            filtered = [a for a in filtered if a.severity.upper() == severity.upper()]
        return filtered

    def add_alert(self, alert: ServiceAlert):
        self._alerts = [a for a in self._alerts if a.id != alert.id]
        self._alerts.append(alert)

    def add_realtime_alert(self, alert: ServiceAlert):
        alert.source = "gtfs_rt"
        alert.is_official_realtime = True
        # Prevent duplicates
        self._alerts = [a for a in self._alerts if a.id != alert.id]
        self._alerts.append(alert)

    def reset(self):
        # Restore baseline
        self.__init__()


alert_service = AlertService()
